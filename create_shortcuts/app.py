"""登録一覧の確認とインポート画面の起動。登録内容を自動では変更しない。"""

import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

CACHE_DIR = Path.home() / "Library/Caches/shortcuts_app/create_shortcuts"


@dataclass(frozen=True)
class RegisteredShortcut:
    name: str
    identifier: str


def list_shortcuts() -> list[RegisteredShortcut]:
    result = subprocess.run(
        ["/usr/bin/shortcuts", "list", "--show-identifiers"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    shortcuts = []
    for number, line in enumerate(result.stdout.splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"(.+) \(([0-9a-fA-F-]{36})\)", line)
        if match is None:
            raise RuntimeError(
                f"ショートカット一覧の形式を読み取れません: {number}行目"
            )
        try:
            identifier = str(uuid.UUID(match[2])).upper()
        except ValueError as exc:
            raise RuntimeError(
                f"ショートカット一覧のIDが不正です: {number}行目"
            ) from exc
        shortcuts.append(RegisteredShortcut(match[1], identifier))
    return shortcuts


def resolve_target(name: str, *, new: bool = False) -> RegisteredShortcut | None:
    matches = [item for item in list_shortcuts() if item.name == name]
    if len(matches) > 1:
        raise RuntimeError(
            f"同じ名前の登録が複数あります。対象を整理してから再実行してください: {name}"
        )
    if matches:
        if new:
            raise RuntimeError(
                f"すでに登録済みです。--newを外して更新候補を確認してください: {name}"
            )
        return matches[0]
    if not new:
        raise RuntimeError(
            f"対象が見つかりません。登録名と定義のNAMEを確認してください。初回作成の場合だけ--newを指定します: {name}"
        )
    return None


def _filename(name: str) -> str:
    if not name or name in (".", "..") or any(c in name for c in "/\\\0\r\n"):
        raise ValueError("ショートカット名をファイル名として扱えません。")
    return name + ".shortcut"


def new_output_path(definition: str, name: str) -> Path:
    """毎回別のフォルダに同名ファイルを作り、以前の生成物を保持する。"""
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", definition) is None:
        raise ValueError("定義名はハイフン区切りの英数字で指定してください。")
    return CACHE_DIR / definition / uuid.uuid4().hex / _filename(name)


def check_output_name(path: Path, name: str) -> None:
    if path.name != _filename(name):
        raise ValueError(
            f"インポート時の名前を揃えるため、ファイル名は{_filename(name)}にしてください。"
        )


def open_import(
    path: Path,
    *,
    name: str,
    expected_target: RegisteredShortcut | None,
    new: bool = False,
) -> None:
    """署名中に対象が変わっていないか確認し、追加画面だけを開く。"""
    path = path.expanduser().absolute()
    check_output_name(path, name)
    if path.is_symlink() or not path.is_file():
        raise ValueError("署名済みの通常ファイルを指定してください。")
    current = resolve_target(name, new=new)
    if current != expected_target:
        raise RuntimeError(
            "署名中に対象の登録が変更されました。名前とUUIDを再確認してください。"
        )
    subprocess.run(
        ["/usr/bin/open", "-a", "Shortcuts", str(path)], check=True, timeout=30
    )
