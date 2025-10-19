import argparse
import os
import sys

from dotenv import load_dotenv

from MyFfmpegHelper import MyFfmpegHelper
from MyLoggerHelper import MyLoggerHelper

# ===== 前提条件 ==============================================================
# PCにffmpegをインストールしていること

# ===== Config Begin ==========================================================
# .envを読み込む
load_dotenv()
LOG_DIR = os.getenv("LOG_DIR", "~/Downloads")

# ===== Config End ============================================================
logger = MyLoggerHelper.setup_logger(__name__, LOG_DIR)


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
        description="動画ファイルを5GiBごとに分割するスクリプト"
    )
    parser.add_argument("files", nargs="+", help="ファイルのパス")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    try:
        # 起動引数処理
        if argv is None:
            argv = sys.argv[1:]

        args = parse_args(argv)

        # 処理するファイルは起動引数
        file = args.files[0]

        # ファイルの存在確認
        if not os.path.isfile(file):
            logger.error(f"File not found: {file}")
            return 1

        # 分割するファイルサイズを定義
        split_size = int(5 * 1024**3 - 1024**2)  # 5GiBとマージン

        logger.info(f"split_size = {split_size}")

        MyFfmpegHelper.split_video_lossless_by_keyframes(
            file, split_size_bytes=split_size, logger=logger
        )

        return 0

    except Exception as e:
        logger.error(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
