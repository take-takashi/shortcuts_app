import argparse
import os
from dotenv import load_dotenv

from MyFfmpegHelper.my_ffmpeg_helper import MyFfmpegHelper
from MyNotionHelper.my_notion_helper import MyNotionHelper

def main():
    """
    メイン処理
    """
    # .envファイルから環境変数を読み込む
    load_dotenv()
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_MUSIC_ID")

    if not notion_token or not database_id:
        print("Error: NOTION_TOKEN or NOTION_DATABASE_MUSIC_ID not found in .env file")
        return

    # コマンドライン引数の設定
    parser = argparse.ArgumentParser(description="Extract metadata from an audio file and add it to Notion.")
    parser.add_argument("file_path", help="The path to the audio file.")
    args = parser.parse_args()

    # ファイルパスの展開
    file_path = os.path.expanduser(args.file_path)

    # --- ヘルパー関数を使って処理を実行 ---

    # 1. メタデータの取得
    metadata = MyFfmpegHelper.get_audio_metadata(file_path)

    if metadata:
        # 2. Notionヘルパーを初期化してNotionへの追加
        notion_helper = MyNotionHelper(token=notion_token)
        notion_helper.add_music_info_to_db(metadata, file_path, database_id)

if __name__ == "__main__":
    main()