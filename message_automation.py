"""Shortcuts.appから受け取った固定コマンドを実行する。"""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MAX_MESSAGE_LENGTH = 4096


def run_notion() -> int:
    script_path = SCRIPT_DIR / "download_and_upload_for_notion.py"
    if not script_path.is_file():
        print(f"実行するスクリプトが見つかりません: {script_path}", file=sys.stderr)
        return 1

    # shellを介さず、固定のスクリプトを引数リストで起動する。
    return subprocess.run(
        [sys.executable, str(script_path)],
        cwd=SCRIPT_DIR,
        check=False,
    ).returncode


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
        command = resolve_command(
            sys.stdin.read(MAX_MESSAGE_LENGTH + 1),
            sys.argv[1:],
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    return ACTIONS[command]()


if __name__ == "__main__":
    raise SystemExit(main())
