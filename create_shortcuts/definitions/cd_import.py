"""新しいCDの取り込みとNotion登録を起動するショートカットの定義。"""

import argparse
import subprocess
import sys
from pathlib import Path

from create_shortcuts import Shortcut

NAME = "CDをNotionへ（ショートカット）"
# iCloudで別のMacへ同期しても、このMacのユーザー名は埋め込まない。
LAUNCH_SCRIPT = """set -eu
launcher="$HOME/github/shortcuts_app/import_cd_to_notion.command"
if [ ! -x "$launcher" ]; then
    printf '%s\\n' "起動スクリプトが見つかりません: $launcher" >&2
    exit 1
fi
/usr/bin/open -a Terminal "$launcher"
"""


def create_shortcut() -> Shortcut:
    """CD用の文言と起動処理だけを定義し、保存形式は共通処理へ任せる。"""
    shortcut = Shortcut(NAME)
    shortcut.comment(
        "Mac専用。TerminalでCD取り込み・Notion登録を起動します。完了状況はTerminalで確認してください。各Macに~/github/shortcuts_appとdiskflow、mise環境、Notionの.env設定が必要です。このショートカットに認証情報は含まれません。"
    )
    shortcut.alert(
        "新しいCDをNotionへ取り込みますか？",
        "CDを読み込み、AACと原本ZIPをNotionへ登録します。すでに取り込み済みのCDを再度実行すると重複登録になる場合があります。続けるとTerminalが開きます。処理の完了はTerminalで確認してください。",
        cancel=True,
    )
    shortcut.run_shell(LAUNCH_SCRIPT, shell="/bin/zsh")
    return shortcut


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="ショートカット.app用のCD取り込みファイルを生成・署名します。取り込みは開始しません。"
    )
    parser.add_argument(
        "--output", type=Path, default=Path.home() / "Downloads" / f"{NAME}.shortcut"
    )
    args = parser.parse_args(argv)
    try:
        print(create_shortcut().export(args.output))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"作成できませんでした: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
