import os
from dataclasses import dataclass

from dotenv import load_dotenv
from yt_dlp import YoutubeDL

from MyLoggerHelper import MyLoggerHelper
from MyNotionHelper import MyNotionHelper

from typing import Any, cast

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


@dataclass
class VideoInfo:
    """
    動画の情報を格納するためのデータクラス。

    属性:
        video_title (str): 動画のタイトル。
        video_filepath (str): 動画ファイルのパス。
        thumbnail_filepath (str): サムネイル画像のファイルパス。
    """

    video_title: str
    video_filepath: str
    thumbnail_filepath: str


# 動画ファイル、サムネイルファイルをダウンロードして情報を返す関数
def download_file(url: str, output_dir: str = "~/Downloads") -> VideoInfo:
    outtmpl = f"{output_dir}/%(title)s.%(ext)s"

    ydl_opts = {
        "outtmpl": outtmpl,
        "trim_file_name": 95,
        "writethumbnail": True,
        "format": "bv[ext=mp4]+ba[ext=m4a]/bv+ba/best[ext=mp4]/best",
        "age_limit": 1985,
        "cookies_from_browser": "safari",
    }

    try:
        with YoutubeDL(cast(Any, ydl_opts)) as ydl:
            # 動画のダウンロード
            info = ydl.extract_info(url, download=True)

            # 動画のダウンロードに失敗した場合
            if info is None:
                raise Exception("動画のダウンロードに失敗しました。")

            video_title = info.get("title")
            video_filepath = ydl.prepare_filename(info)

            # サムネイルファイルパスを探す
            thumbnail_filepath = None
            for thumb in info.get("thumbnails", []):
                if "filepath" in thumb:
                    thumbnail_filepath = thumb["filepath"]
                    break

            return VideoInfo(
                video_title=video_title or "",
                video_filepath=video_filepath or "",
                thumbnail_filepath=thumbnail_filepath or "",
            )

    except Exception as e:
        raise Exception(f"URL「{url}」の動画のダウンロードに失敗しました: {e}")


# ファイルパスの拡張子が.imageの場合、.jpgに名称変更する関数
def rename_image2jpg_extension(filepath: str) -> str:
    """
    指定されたファイルパスの拡張子が.imageの場合、.jpgに変更します。
    Args:
        filepath (str): 変更対象のファイルパス。
    Returns:
        str: 拡張子を変更した新しいファイルパス。
    """
    if filepath.endswith(".image"):
        new_filepath = filepath[:-6] + ".jpg"
        os.rename(filepath, new_filepath)
        # log(f"✅ 拡張子が「.image」だったのでファイル名を変更しました: {filepath} -> {new_filepath}")
        return new_filepath
    return filepath


# ======== Entry Point ========================================================
def main():
    try:
        logger.info("===== スクリプトを開始します。")

        if NOTION_TOKEN is None or NOTION_DATABASE_ID is None:
            raise Exception("環境変数が設定されていません。")

        # Notionクライアントのインスタンスを作成
        notion = MyNotionHelper(
            token=NOTION_TOKEN,
            version=NOTION_VERSION,
            logger=logger,
        )

        # データベースからアイテムを取得
        items = notion.get_items(NOTION_DATABASE_ID)

        if not items:
            logger.warning("⚠️Notionデータベースに対象のアイテムがありません。")
            return

        for item in items:
            # アイテムのプロパティからURLを取得
            logger.info(f"▶ アイテムID「{item['id']}」の処理を開始します。")
            url = notion.get_item_property_url(item)

            if url == "":
                logger.warning(
                    f"⚠️ アイテム {item['id']} に「URL」プロパティがありません。"
                )
                continue
            logger.info(f"▶ アイテムID「{item['id']}」のURL: {url}")

            # URLからファイルをダウンロード
            logger.info(f"▶ URL「{url}」の動画をダウンロード中...")

            try:
                video_info: VideoInfo = download_file(url)
            except Exception as e:
                logger.error(f"URL「{url}」の動画のダウンロードに失敗しました: {e}")
                continue

            logger.info(f"ダウンロードした動画のタイトル: {video_info.video_title}")
            logger.info(
                f"ダウンロードした動画のファイルパス: {video_info.video_filepath}"
            )
            logger.info(
                f"ダウンロードしたサムネイルのファイルパス: {video_info.thumbnail_filepath}"
            )
            logger.info(f"✅ URL「{url}」のダウンロードが完了しました。")

            # ダウンロードが完了したらNotionのページ内のコンテンツを削除
            # Xからのダウンロードはコンテンツを削除しないようにする
            if url.startswith("https://x.com/"):
                logger.info(
                    f"⚠️ URL「{url}」はXからのダウンロードのため、コンテンツを削除しません。"
                )
            else:
                logger.info(
                    f"▶ アイテムID「{item['id']}」のページコンテンツを削除中..."
                )
                notion.delete_page_content(item["id"])
                logger.info(
                    f"✅ アイテムID「{item['id']}」のページコンテンツを削除しました。"
                )
            # end if

            # ダウンロードが完了したらNotionのページタイトルを動画のタイトルに変更
            logger.info("▶ ページタイトルを変更中...")
            notion.change_page_title(item["id"], video_info.video_title)
            logger.info(
                f"✅ ページタイトルを「{video_info.video_title}」に変更しました。"
            )

            # ファイルがダウンロードできたら、Notionに動画をアップロード
            logger.info(
                f"▶ ファイル「{video_info.video_filepath}」の動画をNotionにアップロード中..."
            )
            notion.upload_file(item["id"], video_info.video_filepath)
            logger.info(
                f"✅ ファイル「{video_info.video_filepath}」の動画のアップロードが完了しました。"
            )

            # サムネイルの拡張子が.imageなら.jpgに変更
            logger.info(
                f"▶ ファイル「{video_info.thumbnail_filepath}」のサムネイルの拡張子を確認中..."
            )
            video_info.thumbnail_filepath = rename_image2jpg_extension(
                video_info.thumbnail_filepath
            )
            logger.info(
                f"✅ ファイル「{video_info.thumbnail_filepath}」のサムネイルの拡張子を確認・変更しました。"
            )

            # 動画のアップロードの次に画像を添付する
            logger.info(
                f"▶ アイテムID「{item['id']}」のサムネイルをNotionにアップロード中..."
            )
            notion.upload_file(item["id"], video_info.thumbnail_filepath)
            logger.info(
                f"✅ アイテムID「{item['id']}」のサムネイルのアップロードが完了しました。"
            )

            # アイテムのプロパティ「処理済」をチェックにする
            logger.info(
                f"▶ アイテムID「{item['id']}」の「処理済」ステータスを更新中..."
            )
            notion.change_item_processed_status(item["id"])
            logger.info(
                f"✅ アイテムID「{item['id']}」の「処理済」ステータスを更新しました。"
            )

            logger.info(f"✅ アイテムID {item['id']} の処理が完了しました。")
            # Continue

        logger.info("すべてのアイテムの処理が完了しました。")
        logger.info("===== スクリプトが終了しました。\n\n")
    except Exception as e:
        logger.error(e)
        return


# End

# ======== Main End ===========================================================
if __name__ == "__main__":
    main()
    exit(0)
