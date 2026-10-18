"""Shortcuts.appから受け取った固定コマンドを実行する。"""

import fcntl
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TextIO

SCRIPT_DIR = Path(__file__).resolve().parent
MAX_MESSAGE_LENGTH = 4096
LOG_DIR_ENV = "MESSAGE_AUTOMATION_LOG_DIR"
DEFAULT_LOG_DIR = Path.home() / "Library/Logs/shortcuts_app"
# ログの出力先を変えても、同じユーザーのNotion処理は重複起動させない。
STATE_DIR = Path.home() / "Library/Application Support/shortcuts_app"
NOTION_WORKER_ARG = "--notion-worker"

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


def acquire_notion_lock() -> TextIO | None:
    """起動前に排他ロックを取る。ファイルの存在やPIDの生死では判定しない。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_file = (STATE_DIR / "auto-notion.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    except Exception:
        lock_file.close()
        raise
    return lock_file


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
        expected = (STATE_DIR / "auto-notion.lock").stat()
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


def run_health() -> int:
    print("OK")
    return 0


# メッセージの値から実行内容を組み立てず、許可した処理だけを登録する。
ACTIONS: dict[str, Callable[[], int]] = {
    "auto:notion": run_notion,
    "health": run_health,
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
