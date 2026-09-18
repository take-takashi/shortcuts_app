#!/usr/bin/env python3
"""Restore Shortcuts in a folder to Finder's contextual menu on macOS."""

from __future__ import annotations

import argparse
import plistlib
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# `shortcuts list --show-identifiers`の各行末尾にあるUUIDを抽出する正規表現。
UUID_AT_END = re.compile(
    r"\(([0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})\)\s*$"
)
# pbsのNSServicesStatusで使われるShortcutsサービスのキー末尾。
SERVICE_SUFFIX = " - runShortcutAsService"
# ショートカットを表示する場所。Finderの右クリックメニューなどを指定する。
PRESENTATION_MODES = {
    "ContextMenu": True,
    "FinderPreview": True,
    "ServicesMenu": True,
    "TouchBar": False,
}


def run(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    """指定したmacOSコマンドを実行し、失敗した場合は例外を送出する。"""
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def shortcut_ids(folder_name: str) -> list[str]:
    """指定フォルダーに含まれるショートカットの識別子を取得する。"""
    result = run(
        [
            "shortcuts",
            "list",
            "--folder-name",
            folder_name,
            "--show-identifiers",
        ],
        capture_output=True,
    )

    # `shortcuts list` currently has no JSON output option, so parse its
    # stable identifier suffix rather than depending on the shortcut name.
    ids = UUID_AT_END.findall(result.stdout)
    return list(dict.fromkeys(ids))


def update_plist(plist_path: Path, ids: list[str]) -> None:
    """pbsのplistを更新し、指定したショートカットをFinderメニューに登録する。"""
    with plist_path.open("rb") as file:
        plist = plistlib.load(file)

    if not isinstance(plist, dict):
        raise ValueError("pbs plist is not a dictionary")

    services = plist.setdefault("NSServicesStatus", {})
    if not isinstance(services, dict):
        raise ValueError("NSServicesStatus is not a dictionary")

    for shortcut_id in ids:
        key = f"(null) - {shortcut_id}{SERVICE_SUFFIX}"
        entry = services.get(key)
        if not isinstance(entry, dict):
            entry = {}
            services[key] = entry

        modes = entry.get("presentation_modes")
        if not isinstance(modes, dict):
            modes = {}
            entry["presentation_modes"] = modes

        # Update only the presentation modes and preserve any other pbs data.
        modes.update(PRESENTATION_MODES)
        print(f"upsert: {shortcut_id}")

    with plist_path.open("wb") as file:
        plistlib.dump(plist, file)


def restart_services() -> None:
    """pbsを再読み込みし、Finderを再起動して変更を反映する。"""
    subprocess.run(
        ["killall", "pbs"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    run(["/System/Library/CoreServices/pbs", "-update"])

    subprocess.run(
        ["killall", "Finder"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="Restore Shortcuts in a folder to Finder's contextual menu.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-f",
        "--folder",
        dest="folder_name",
        default="QuickActions",
        metavar="NAME",
        help="対象にするショートカットフォルダー名",
    )
    return parser.parse_args()


def main() -> int:
    """ショートカットの取得、plist更新、サービス再読み込みを実行する。"""
    args = parse_args()
    folder_name = args.folder_name
    print(f"Reading shortcuts from folder: {folder_name}")

    ids = shortcut_ids(folder_name)
    if not ids:
        print(f"No shortcuts found in folder: {folder_name}", file=sys.stderr)
        return 1

    print(f"Found {len(ids)} shortcut(s):")
    for shortcut_id in ids:
        print(f"  {shortcut_id}")

    with tempfile.TemporaryDirectory(prefix="fix-finder-quick-actions-") as directory:
        plist_path = Path(directory) / "pbs.plist"
        run(["defaults", "export", "pbs", str(plist_path)])
        update_plist(plist_path, ids)
        run(["defaults", "import", "pbs", str(plist_path)])

    restart_services()
    print("\nFinder Quick Actions restored.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        command = " ".join(error.cmd) if isinstance(error.cmd, list) else str(error.cmd)
        print(f"Command failed: {command}", file=sys.stderr)
        if detail:
            print(detail, file=sys.stderr)
        raise SystemExit(error.returncode or 1)
    except (OSError, plistlib.InvalidFileException, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
