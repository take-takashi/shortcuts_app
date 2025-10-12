import argparse
import subprocess
import sys
from pathlib import Path


def parse_args(argv):
    """
    引数を解析する。

    Args:
        argv (list): コマンドライン引数のリスト。sys.argv[1:]を想定。

    Returns:
        argparse.Namespace: 解析された引数を持つオブジェクト。

    Raises:
        argparse.ArgumentError: 引数の解析に失敗した場合。
    """
    parser = argparse.ArgumentParser(
        description="yt-dlpで指定URLからファイルをダウンロードするスクリプト"
    )
    parser.add_argument("url", help="ダウンロードするファイルのURL")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="保存先ディレクトリ。存在しない場合は作成されます。",
    )
    parser.add_argument(
        "--output-template",
        default="%(title)s.%(ext)s",
        help="yt-dlpの出力テンプレート（-oと同じ形式）。",
    )
    return parser.parse_args(argv)


def download_with_ytdlp(url: str) -> Path:
    """
    yt-dlpを呼び出し、指定したURLからファイルをダウンロードする。

    Args:
        url (str): ダウンロード元URL。
        output_dir (Path): 保存先ディレクトリ。
        output_template (str): yt-dlpの出力テンプレート。

    Returns:
        Path: ダウンロードされたファイルのパス。

    Raises:
        subprocess.CalledProcessError: yt-dlpの実行に失敗した場合。
        FileNotFoundError: yt-dlpが出力したファイルが見つからない場合。
    """
    cmd = [
        "yt-dlp",
        "-f",
        "bv[ext=mp4]+ba[ext=m4a]/bv+ba/best[ext=mp4]/best",
        url,
        "--trim-filename",
        "95",
        "--cookies-from-browser",
        "safari",
        "--age-limit",
        "1985",
        "--write-thumbnail",
        "--embed-thumbnail",
        "-o",
        "~/Downloads/%(title)s.%(ext)s",
    ]

    completed = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
    )

    stdout_lines = [
        line.strip() for line in completed.stdout.splitlines() if line.strip()
    ]
    if not stdout_lines:
        raise FileNotFoundError("yt-dlpが出力ファイルのパスを返しませんでした。")

    file_path = Path(stdout_lines[-1])
    if not file_path.exists():
        raise FileNotFoundError(f"yt-dlpが返したパスが存在しません: {file_path}")

    return file_path


def main(argv=None) -> int:
    try:
        if argv is None:
            argv = sys.argv[1:]

        args = parse_args(argv)

        # output_dir = Path(args.output_dir).expanduser().resolve()
        # output_dir.mkdir(parents=True, exist_ok=True)

        downloaded_file = download_with_ytdlp(args.url)
        print(f"ダウンロード完了: {downloaded_file}")

        return 0
    except subprocess.CalledProcessError as e:
        print("yt-dlpの実行に失敗しました。")
        if e.stderr:
            print(e.stderr.strip())
        return e.returncode or 1
    except Exception as e:
        print(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
