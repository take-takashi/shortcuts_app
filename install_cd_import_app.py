"""Spotlightから検索できるCD取り込みアプリを、macOS標準機能で作る。"""

import argparse
import json
import shlex
import subprocess
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def launcher_source(script: Path) -> str:
    # シェル用とAppleScript用の引用を別々に行う。
    command = json.dumps(shlex.quote(str(script)), ensure_ascii=False)
    return f"""on run
    tell application "Terminal"
        activate
        do script {command}
    end tell
end run
"""


def install(output: Path) -> Path:
    output = output.expanduser().absolute()
    if output.suffix != ".app":
        raise ValueError("出力先は.appにしてください。")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"既存アプリは上書きしません: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".cd-import-", dir=output.parent
    ) as temporary:
        base = Path(temporary)
        source = base / "launcher.applescript"
        source.write_text(
            launcher_source(SCRIPT_DIR / "import_cd_to_notion.command"),
            encoding="utf-8",
        )
        built = base / output.name
        subprocess.run(
            ["/usr/bin/osacompile", "-o", str(built), str(source)], check=True
        )
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"既存アプリは上書きしません: {output}")
        built.rename(output)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Spotlight用の「CDをNotionへ」アプリを作成します。"
    )
    parser.add_argument(
        "--output", type=Path, default=Path.home() / "Applications/CDをNotionへ.app"
    )
    args = parser.parse_args(argv)
    try:
        print(install(args.output))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"作成できませんでした: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
