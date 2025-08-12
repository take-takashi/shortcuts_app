import os
import sys

from dotenv import load_dotenv

from MyFfmpegHelper import MyFfmpegHelper
from MyLoggerHelper import MyLoggerHelper
from MyNotionHelper import MyNotionHelper

"""
一つのファイルをNotionの指定データベースにアップロードする。
データベースのページ名は`basename`とする。
すでに`basename`のページが存在する場合、そのページに追加でアップロードする。
5GiBを超えるファイルはアップロードしないが、
ファイルが動画の場合はPart分割してアップロードを行う。
"""

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
        file = files[0]

        # ページを特定または作成するためのキーとして、最初のファイルのbasenameを使用
        basename_without_ext = os.path.splitext(os.path.basename(file))[0]

        # basenameをタイトルに持つページが既に存在するか確認
        page_id = notion.get_page_id_by_title(
            NOTION_DATABASE_ID, basename_without_ext, "名前"
        )

        if page_id:
            logger.info(
                f"既存のページが見つかりました: page_id={page_id}, title='{basename_without_ext}'"
            )
        else:
            # 存在しない場合は、新しい空のページを作成
            logger.info(
                f"既存のページが見つからないため、新規ページを作成します: title='{basename_without_ext}'"
            )
            page_id = notion.create_blank_page(
                database_id=NOTION_DATABASE_ID,
            )
            # 新規作成したページのタイトルを設定
            notion.change_page_title(page_id, basename_without_ext)
            logger.info(
                f"新規ページを作成しました: page_id={page_id}, title='{basename_without_ext}'"
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
