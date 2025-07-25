import os
import sys

from dotenv import load_dotenv

from MyFfmpegHelper import MyFfmpegHelper
from MyLoggerHelper import MyLoggerHelper
from MyNotionHelper import MyNotionHelper

# ===== Config Begin ==========================================================
# .envを読み込む
load_dotenv()
# 環境変数として取得
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_VERSION = "2022-06-28"
LOG_DIR = os.getenv("LOG_DIR", "~/Downloads")

# ===== Config End ============================================================
logger = MyLoggerHelper.setup_logger(__name__, LOG_DIR)


def main():
    try:
        logger.info("===== スクリプトを開始します。")

        if NOTION_TOKEN is None or NOTION_DATABASE_ID is None:
            raise Exception("環境変数が設定されていません。")

        # コマンドライン引数を取得
        args = sys.argv[1:]
        logger.info(f"Arguments: {args}")

        # Notionクライアントのインスタンスを作成
        notion = MyNotionHelper(
            token=NOTION_TOKEN,
            version=NOTION_VERSION,
            logger=logger,
        )

        # コマンドライン引数をそれぞれファイルパスとして処理する
        files = args

        # Notionデータベースに空のページを作成
        # ※複数のファイルをアップロードした場合は、最後のファイルの名前になる
        page_id = notion.create_blank_page(
            database_id=NOTION_DATABASE_ID,
        )

        for file in files:
            # fileの存在確認
            if not os.path.isfile(file):
                logger.error(f"File not found: {file}")
                continue

            # 動画ファイルかどうかの判定
            flg_video = False

            # ファイルのサイズをチェックし、5GB以下であればそのままアップロード
            file_size = os.path.getsize(file)
            if file_size > 5 * 1024 * 1024 * 1024:  # 5GB
                # 動画ファイルかどうかを判別し、動画ファイルであれば動画用のアップロードを行う
                if MyFfmpegHelper.is_video(file):
                    flg_video = True
                else:
                    # 動画ファイル以外の5GiB超えのファイルはアップロードしない
                    logger.warning(
                        f"5GBを超えるファイルはアップロードしません。: {file} (size: {file_size} bytes)"
                    )
                    continue

            # ページタイトルをファイル名に変更
            notion.change_page_title(page_id, os.path.basename(file))

            # ファイルをページにアップロードする
            if flg_video:
                notion.upload_video(page_id, file)
            else:
                notion.upload_file(page_id, file)

            logger.info(f"Successfully processed file: {file}")

            # エラーなく添付できたらファイルを削除する

    except Exception as e:
        logger.error(e)
        sys.exit(1)

    # end of main function


if __name__ == "__main__":
    main()
    exit(0)
