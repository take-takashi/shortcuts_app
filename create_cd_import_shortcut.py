"""ショートカット.appに追加できる、署名済みの取り込み用ファイルを作る。"""

import argparse
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

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


def workflow() -> dict:
    """旧形式のplistを構成し、macOS標準コマンドで署名できるようにする。"""
    return {
        "WFWorkflowName": NAME,
        "WFWorkflowClientVersion": "2600.0.1",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowTypes": [],
        "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowIcon": {
            "WFWorkflowIconGlyphNumber": 59793,
            "WFWorkflowIconStartColor": 4282601983,
        },
        "WFWorkflowActions": [
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.comment",
                "WFWorkflowActionParameters": {
                    "WFCommentActionText": "Mac専用。TerminalでCD取り込み・Notion登録を起動します。完了状況はTerminalで確認してください。各Macに~/github/shortcuts_appとdiskflow、mise環境、Notionの.env設定が必要です。このショートカットに認証情報は含まれません。",
                },
            },
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.alert",
                "WFWorkflowActionParameters": {
                    "WFAlertActionTitle": "新しいCDをNotionへ取り込みますか？",
                    "WFAlertActionMessage": "CDを読み込み、AACと原本ZIPをNotionへ登録します。すでに取り込み済みのCDを再度実行すると重複登録になる場合があります。続けるとTerminalが開きます。処理の完了はTerminalで確認してください。",
                    "WFAlertActionCancelButtonShown": True,
                },
            },
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.runshellscript",
                "WFWorkflowActionParameters": {
                    "Script": LAUNCH_SCRIPT,
                    "Shell": "/bin/zsh",
                    "InputMode": "to stdin",
                },
            },
        ],
    }


def build(output: Path) -> Path:
    """生成・署名だけを行う。インポートも取り込みも自動では実行しない。"""
    output = output.expanduser().absolute()
    if output.suffix != ".shortcut":
        raise ValueError("出力先は.shortcutにしてください。")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"既存ファイルは上書きしません: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".cd-shortcut-", dir=output.parent
    ) as temporary:
        base = Path(temporary)
        unsigned = base / "unsigned.shortcut"
        unsigned.write_bytes(plistlib.dumps(workflow(), fmt=plistlib.FMT_BINARY))
        signed = base / "signed.shortcut"
        # anyone署名はAppleの検証を利用する。送る内容は上記の起動処理のみ。
        subprocess.run(
            [
                "/usr/bin/shortcuts",
                "sign",
                "--mode",
                "anyone",
                "--input",
                str(unsigned),
                "--output",
                str(signed),
            ],
            check=True,
            timeout=120,
        )
        if not signed.is_file() or signed.is_symlink() or signed.stat().st_size == 0:
            raise RuntimeError("署名済みファイルが作成されませんでした。")
        # 同じファイルシステム上で、既存の出力を上書きせず公開する。
        os.link(signed, output)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="ショートカット.app用のCD取り込みファイルを生成・署名します。取り込みは開始しません。"
    )
    parser.add_argument(
        "--output", type=Path, default=Path.home() / "Downloads" / f"{NAME}.shortcut"
    )
    args = parser.parse_args(argv)
    try:
        print(build(args.output))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"作成できませんでした: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
