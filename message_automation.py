"""Shortcuts.appから受け取った固定コマンドを実行する。"""

import fcntl
import logging
import math
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import TextIO

SCRIPT_DIR = Path(__file__).resolve().parent
MAX_MESSAGE_LENGTH = 4096
LOG_DIR_ENV = "MESSAGE_AUTOMATION_LOG_DIR"
DEFAULT_LOG_DIR = Path.home() / "Library/Logs/shortcuts_app"
# ログの出力先を変えても、同じユーザーのバックグラウンド処理は重複起動させない。
STATE_DIR = Path.home() / "Library/Application Support/shortcuts_app"
NOTION_LOCK_NAME = "auto-notion.lock"
CAFFEINATE_LOCK_NAME = "caffeinate.lock"
NOTION_WORKER_ARG = "--notion-worker"
TAILSCALE_PATHS = (
    "/opt/homebrew/bin/tailscale",
    "/usr/local/bin/tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    str(Path.home() / "Applications/Tailscale.app/Contents/MacOS/Tailscale"),
)
CAFFEINATE_PATHS = ("/usr/bin/caffeinate",)
CAFFEINATE_STOP_TIMEOUT_SECONDS = 3.0
CAFFEINATE_PID_WAIT_SECONDS = 0.5

logger = logging.getLogger(__name__)
_log_handler: logging.Handler | None = None


def get_log_dir() -> Path:
    value = os.getenv(LOG_DIR_ENV, "").strip() or str(DEFAULT_LOG_DIR)
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return path if path.is_absolute() else SCRIPT_DIR / path


def configure_logger() -> None:
    """受付・完了・失敗を日別ログへ記録する。設定できなければ起動しない。"""
    global _log_handler
    if _log_handler is not None:
        logger.removeHandler(_log_handler)
        _log_handler.close()
        _log_handler = None

    log_dir = get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"message_automation-{date.today():%Y%m%d}.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - pid=%(process)d - %(message)s")
    )
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    _log_handler = handler


def acquire_lock(lock_name: str) -> TextIO | None:
    """起動前に排他ロックを取る。ファイルの存在やPIDの生死では判定しない。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_file = (STATE_DIR / lock_name).open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    except Exception:
        lock_file.close()
        raise
    return lock_file


def acquire_notion_lock() -> TextIO | None:
    """Notion処理の排他ロックを取る。"""
    return acquire_lock(NOTION_LOCK_NAME)


def acquire_caffeinate_lock() -> TextIO | None:
    """caffeinateの排他ロックを取る。"""
    return acquire_lock(CAFFEINATE_LOCK_NAME)


def run_notion() -> int:
    """ロックをワーカーへ引き継ぎ、Shortcutsには起動受付だけを返す。"""
    script_path = SCRIPT_DIR / "download_and_upload_for_notion.py"
    if not script_path.is_file():
        logger.error("実行するスクリプトが見つかりません: %s", script_path)
        print(f"実行するスクリプトが見つかりません: {script_path}", file=sys.stderr)
        return 1

    lock_file = acquire_notion_lock()
    if lock_file is None:
        logger.info("重複起動をスキップしました。command=auto:notion ALREADY_RUNNING")
        print("ALREADY_RUNNING")
        return 0

    # LOCK_UNやunlinkはしない。共有されたFDを閉じるだけにし、ワーカーの
    # ロックを維持する。ワーカー終了時にはOSが解放するので残骸の削除は不要。
    with lock_file:
        output_path = get_log_dir() / f"message_automation-notion-{date.today():%Y%m%d}.log"
        with output_path.open("a", encoding="utf-8") as output:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    str(SCRIPT_DIR / "message_automation.py"),
                    NOTION_WORKER_ARG,
                    str(lock_file.fileno()),
                ],
                cwd=SCRIPT_DIR,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                pass_fds=(lock_file.fileno(),),
            )
        logger.info(
            "バックグラウンド起動を受け付けました。command=auto:notion "
            "worker_pid=%s output=%s（完了ではありません）",
            worker.pid,
            output_path,
        )
        print(f"STARTED pid={worker.pid}")
    return 0


def run_notion_worker(lock_fd: int) -> int:
    """固定スクリプトの終了を待ち、結果をログへ記録する内部ワーカー。"""
    if lock_fd < 3:
        raise ValueError("ワーカーには起動元から渡されたロックFDが必要です。")

    with os.fdopen(lock_fd, "a+", encoding="utf-8") as lock_file:
        inherited = os.fstat(lock_file.fileno())
        expected = (STATE_DIR / NOTION_LOCK_NAME).stat()
        if (inherited.st_dev, inherited.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError("ワーカーのロックFDが一致しません。")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"worker_pid={os.getpid()}\n")
        lock_file.flush()

        script_path = SCRIPT_DIR / "download_and_upload_for_notion.py"
        started = time.monotonic()
        logger.info("本処理を開始します。command=auto:notion script=%s", script_path)
        try:
            # ワーカーだけが異常終了しても、本処理が生きている間はロックを保つ。
            # 標準出力・標準エラーは起動時に開いたファイルへ継承する。
            completed = subprocess.run(
                [sys.executable, "-u", str(script_path)],
                cwd=SCRIPT_DIR,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=(lock_file.fileno(),),
                check=False,
            )
        except Exception:
            logger.exception("本処理の実行に失敗しました。command=auto:notion")
            return 1

        elapsed = time.monotonic() - started
        if completed.returncode == 0:
            logger.info(
                "本処理が完了しました。command=auto:notion returncode=0 elapsed=%.1fs",
                elapsed,
            )
        else:
            logger.error(
                "本処理が失敗しました。command=auto:notion returncode=%s elapsed=%.1fs",
                completed.returncode,
                elapsed,
            )
        return completed.returncode if completed.returncode >= 0 else 1


def find_tailscale() -> str:
    """ShortcutsのPATHにない場合も、Homebrew版・アプリ版を探す。"""
    for candidate in ("tailscale", *TAILSCALE_PATHS):
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise FileNotFoundError(
        "Tailscale CLIが見つかりません。Tailscaleをインストールしてください。"
    )


def run_tailscale(enabled: bool) -> int:
    """既存の設定を維持して、接続・切断を行う。"""
    action = "on" if enabled else "off"
    arguments = ["up", "--timeout=20s"] if enabled else ["down"]
    try:
        completed = subprocess.run(
            [find_tailscale(), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(
            "Tailscaleの操作がタイムアウトしました。"
            "ターミナルで tailscale up を実行し、接続・ログインを確認してください。"
        ) from error

    # CLIの警告やログイン案内も残す。標準出力は成功時の固定メッセージだけ。
    for output in (completed.stdout, completed.stderr):
        if output.strip():
            logger.info("Tailscale CLI: %s", output.strip())
            print(output.rstrip(), file=sys.stderr)

    if completed.returncode != 0:
        message = (
            f"Tailscaleの切り替えに失敗しました。command=tailscale:{action} "
            f"returncode={completed.returncode}"
        )
        logger.error(message)
        print(message, file=sys.stderr)
        return completed.returncode if completed.returncode >= 0 else 1

    logger.info("Tailscaleの切り替えが完了しました。command=tailscale:%s", action)
    print("TAILSCALE_ON" if enabled else "TAILSCALE_OFF")
    return 0


def run_tailscale_on() -> int:
    return run_tailscale(True)


def run_tailscale_off() -> int:
    return run_tailscale(False)


def get_current_datetime() -> datetime:
    """現在時刻を取得する（テスト時の差し替え用）。"""
    return datetime.now()


def calculate_caffeinate_timeout(
    now: datetime | None = None,
) -> tuple[int, datetime]:
    """当日の23:59:59までの残り秒数と終了予定時刻を返す。"""
    current = now if now is not None else get_current_datetime()
    until = current.replace(hour=23, minute=59, second=59, microsecond=0)
    remaining = math.ceil((until - current).total_seconds())
    return max(remaining, 0), until


def find_caffeinate() -> str:
    """ShortcutsのPATHにない場合も、macOS標準パスからcaffeinateを探す。"""
    for candidate in ("caffeinate", *CAFFEINATE_PATHS):
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise FileNotFoundError("caffeinate CLIが見つかりません。")


def read_caffeinate_pid(lock_path: Path) -> int | None:
    """ロックファイルに記録されたcaffeinateのPIDを読み取る。"""
    try:
        content = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        if line.startswith("pid="):
            raw_pid = line.removeprefix("pid=").strip()
            if raw_pid.isdigit() and int(raw_pid) > 0:
                return int(raw_pid)
    return None


def is_caffeinate_process(pid: int) -> bool:
    """対象PIDが実際にcaffeinateプロセスであることを確認する。"""
    ps_executable = shutil.which("ps") or "/bin/ps"
    completed = subprocess.run(
        [ps_executable, "-p", str(pid), "-o", "comm="],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if completed.returncode != 0:
        return False
    command_name = completed.stdout.strip()
    return bool(command_name) and Path(command_name).name == "caffeinate"


def run_caffeinate_on() -> int:
    """当日23:59:59まで本体スリープを抑制するcaffeinateをバックグラウンド起動する。"""
    executable = find_caffeinate()
    timeout_seconds, until = calculate_caffeinate_timeout()
    if timeout_seconds <= 0:
        logger.info(
            "当日の期限を過ぎているため起動しませんでした。command=caffeinate:on until=%s",
            until.isoformat(timespec="seconds"),
        )
        print("ALREADY_EXPIRED")
        return 0

    lock_file = acquire_caffeinate_lock()
    if lock_file is None:
        logger.info("重複起動をスキップしました。command=caffeinate:on ALREADY_RUNNING")
        print("ALREADY_RUNNING")
        return 0

    # ロックFDをcaffeinateへ引き継ぎ、終了時にOSが自動でロック解放する構成にする。
    with lock_file:
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.flush()

        process = subprocess.Popen(
            [executable, "-is", "-t", str(timeout_seconds)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            pass_fds=(lock_file.fileno(),),
        )
        until_text = until.isoformat(timespec="seconds")
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"pid={process.pid}\nuntil={until_text}\n")
        lock_file.flush()

        logger.info(
            "スリープ抑制を開始しました。command=caffeinate:on pid=%s timeout=%ss until=%s",
            process.pid,
            timeout_seconds,
            until_text,
        )
        print(f"CAFFEINATE_ON pid={process.pid} until={until_text}")
    return 0


def _report_caffeinate_not_running(reason: str) -> int:
    """停止対象のcaffeinateが存在しないことをログと標準出力へ通知する。"""
    logger.info("%s command=caffeinate:off NOT_RUNNING", reason)
    print("NOT_RUNNING")
    return 0


def run_caffeinate_off() -> int:
    """このスクリプトが起動したcaffeinateだけを検証したうえで停止する。"""
    lock_path = STATE_DIR / CAFFEINATE_LOCK_NAME
    if not lock_path.exists():
        return _report_caffeinate_not_running("停止対象のcaffeinateは起動していません。")

    lock_file = acquire_caffeinate_lock()
    if lock_file is not None:
        lock_file.close()
        return _report_caffeinate_not_running("停止対象のcaffeinateは起動していません。")

    # 起動直後のPID書き込みと重なった場合に備え、短時間だけリトライする。
    pid = read_caffeinate_pid(lock_path)
    pid_deadline = time.monotonic() + CAFFEINATE_PID_WAIT_SECONDS
    while pid is None and time.monotonic() < pid_deadline:
        probe_lock = acquire_caffeinate_lock()
        if probe_lock is not None:
            probe_lock.close()
            return _report_caffeinate_not_running("停止前にcaffeinateが終了していました。")
        time.sleep(0.02)
        pid = read_caffeinate_pid(lock_path)

    if pid is None:
        message = "起動中のcaffeinateのPIDを取得できませんでした。"
        logger.error("%s command=caffeinate:off", message)
        print(message, file=sys.stderr)
        return 1

    # PID再利用による誤停止を防ぐため、対象がcaffeinateプロセスであることを確認する。
    if not is_caffeinate_process(pid):
        probe_lock = acquire_caffeinate_lock()
        if probe_lock is not None:
            probe_lock.close()
            return _report_caffeinate_not_running("停止前にcaffeinateが終了していました。")
        message = f"PID {pid} はcaffeinateプロセスではないため停止しませんでした。"
        logger.error("%s command=caffeinate:off", message)
        print(message, file=sys.stderr)
        return 1

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    # ロックが解放される（＝caffeinateプロセスが終了する）まで短時間待つ。
    stop_deadline = time.monotonic() + CAFFEINATE_STOP_TIMEOUT_SECONDS
    while True:
        probe_lock = acquire_caffeinate_lock()
        if probe_lock is not None:
            probe_lock.close()
            logger.info(
                "スリープ抑制を停止しました。command=caffeinate:off pid=%s",
                pid,
            )
            print("CAFFEINATE_OFF")
            return 0
        if time.monotonic() >= stop_deadline:
            break
        time.sleep(0.02)

    message = f"caffeinate(pid={pid})の終了を確認できませんでした。"
    logger.error("%s command=caffeinate:off", message)
    print(message, file=sys.stderr)
    return 1


def run_health() -> int:
    print("OK")
    return 0


# メッセージの値から実行内容を組み立てず、許可した処理だけを登録する。
ACTIONS: dict[str, Callable[[], int]] = {
    "auto:notion": run_notion,
    "health": run_health,
    "tailscale:on": run_tailscale_on,
    "tailscale:off": run_tailscale_off,
    "caffeinate:on": run_caffeinate_on,
    "caffeinate:off": run_caffeinate_off,
}


def parse_message(message: str) -> str:
    """MAC|<許可されたコマンド> 形式のメッセージを検証する。"""
    message = message.strip()
    if not message:
        raise ValueError("入力がありません。ショートカットの入力を渡してください。")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError("メッセージが長すぎます。")

    prefix, separator, command = message.partition("|")
    if prefix != "MAC" or not separator or "|" in command:
        raise ValueError("メッセージ形式が正しくありません。")
    if command not in ACTIONS:
        raise ValueError(f"許可されていないコマンドです: {command}")

    return command


def resolve_command(stdin_message: str, arguments: list[str]) -> str:
    """標準入力・引数のどちらから渡されてもコマンドを解決する。"""
    if len(arguments) > 1:
        raise ValueError("入力は1つのメッセージとして渡してください。")

    messages = []
    if stdin_message.strip():
        messages.append(stdin_message)
    if arguments and arguments[0].strip():
        messages.append(arguments[0])
    if not messages:
        raise ValueError("入力がありません。ショートカットの入力を渡してください。")

    commands = []
    errors = []
    for message in messages:
        try:
            commands.append(parse_message(message))
        except ValueError as error:
            errors.append(error)

    if not commands:
        raise errors[0]
    if len(set(commands)) > 1:
        raise ValueError("標準入力と引数で異なるコマンドが渡されました。")
    return commands[0]


def main() -> int:
    try:
        configure_logger()
    except OSError as error:
        print(f"ログファイルを設定できないため起動しません: {error}", file=sys.stderr)
        return 1

    # メッセージで実行内容を組み立てない。内部モードもNotionの固定処理だけ。
    # ワーカーはShortcutsの標準入力を読まず、終了まで独立して動作する。
    if sys.argv[1:2] == [NOTION_WORKER_ARG]:
        try:
            if len(sys.argv) != 3:
                raise ValueError("ワーカーの引数が正しくありません。")
            return run_notion_worker(int(sys.argv[2]))
        except Exception:
            logger.exception("バックグラウンドワーカーの起動に失敗しました。")
            return 1

    try:
        command = resolve_command(
            sys.stdin.read(MAX_MESSAGE_LENGTH + 1),
            sys.argv[1:],
        )
    except ValueError as error:
        logger.error("コマンドの解決に失敗しました: %s", error)
        print(error, file=sys.stderr)
        return 2

    logger.info("コマンドを受信しました: %s", command)
    try:
        return_code = ACTIONS[command]()
    except Exception as error:
        logger.exception("コマンドの実行に失敗しました: %s", command)
        print(f"コマンドの実行に失敗しました: {error}", file=sys.stderr)
        return 1
    logger.info("受付処理を終了します。command=%s returncode=%s", command, return_code)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
