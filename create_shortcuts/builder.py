"""ショートカットの手順データを生成し、実行せずに書き出す。"""

import os
import plistlib
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, Self

InputMode = Literal["to stdin", "as arguments"]


def _text(value: str, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{label}は文字列で指定してください。")
    return value


class Shortcut:
    """対応アクションを順に追加し、plistまたは署名済みファイルにする。"""

    def __init__(self, name: str):
        self.name = _text(name, "名前")
        self._actions: list[dict[str, Any]] = []

    def _add(self, identifier: str, parameters: dict[str, Any]) -> Self:
        self._actions.append(
            {
                "WFWorkflowActionIdentifier": identifier,
                "WFWorkflowActionParameters": parameters,
            }
        )
        return self

    def comment(self, text: str) -> Self:
        return self._add(
            "is.workflow.actions.comment",
            {
                "WFCommentActionText": _text(text, "コメント", allow_empty=True),
            },
        )

    def alert(self, title: str, message: str = "", *, cancel: bool = True) -> Self:
        if type(cancel) is not bool:
            raise ValueError("cancelはboolで指定してください。")
        return self._add(
            "is.workflow.actions.alert",
            {
                "WFAlertActionTitle": _text(title, "確認のタイトル"),
                "WFAlertActionMessage": _text(message, "確認の本文", allow_empty=True),
                "WFAlertActionCancelButtonShown": cancel,
            },
        )

    def run_shell(
        self,
        script: str,
        *,
        shell: str = "/bin/zsh",
        input_mode: InputMode = "to stdin",
    ) -> Self:
        _text(script, "スクリプト")
        _text(shell, "シェル")
        if not shell.startswith("/"):
            raise ValueError("シェルは絶対パスで指定してください。")
        if input_mode not in ("to stdin", "as arguments"):
            raise ValueError(
                "input_modeはto stdinまたはas argumentsを指定してください。"
            )
        return self._add(
            "is.workflow.actions.runshellscript",
            {
                "Script": script,
                "Shell": shell,
                "InputMode": input_mode,
            },
        )

    def to_plist(self) -> dict[str, Any]:
        """取り出した辞書の編集が、元の定義へ影響しないようコピーする。"""
        return {
            "WFWorkflowName": self.name,
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
            "WFWorkflowActions": deepcopy(self._actions),
        }

    def export(self, output: str | Path, *, sign: bool = True) -> Path:
        """署名済み.shortcut、または閲覧用の未署名XML.plistを新規出力する。"""
        if type(sign) is not bool:
            raise ValueError("signはboolで指定してください。")
        output = Path(output).expanduser().absolute()
        suffix = ".shortcut" if sign else ".plist"
        if output.suffix != suffix:
            raise ValueError(f"出力先は{suffix}にしてください。")
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"既存ファイルは上書きしません: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".shortcut-", dir=output.parent
        ) as temporary:
            base = Path(temporary)
            generated = base / ("unsigned" + suffix)
            fmt = plistlib.FMT_BINARY if sign else plistlib.FMT_XML
            generated.write_bytes(plistlib.dumps(self.to_plist(), fmt=fmt))
            if sign:
                unsigned = generated
                generated = base / "signed.shortcut"
                # Appleへ送信するのは手順データ。アクション自体は実行しない。
                subprocess.run(
                    [
                        "/usr/bin/shortcuts",
                        "sign",
                        "--mode",
                        "anyone",
                        "--input",
                        str(unsigned),
                        "--output",
                        str(generated),
                    ],
                    check=True,
                    timeout=120,
                )
            if (
                not generated.is_file()
                or generated.is_symlink()
                or generated.stat().st_size == 0
            ):
                raise RuntimeError("出力ファイルが作成されませんでした。")
            # 同一ファイルシステム上で公開し、競合時も既存ファイルを守る。
            os.link(generated, output)
        return output
