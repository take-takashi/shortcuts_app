import argparse
import os
from dotenv import load_dotenv
import ffmpeg
from notion_client import Client

def get_audio_metadata(file_path):
    """
    ffmpegを使って音声ファイルのメタデータを取得する
    """
    try:
        # ffprobeでメタデータを取得
        probe = ffmpeg.probe(file_path)
        # format.tagsにメタデータが格納されている
        metadata = probe.get('format', {}).get('tags', {})
        return metadata
    except ffmpeg.Error as e:
        print(f"Error reading metadata: {e.stderr}")
        return None

def add_to_notion(metadata, file_path):
    """
    取得したメタデータをNotionデータベースに追加する
    """
    load_dotenv()
    notion_token = os.getenv("NOTION_API_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not notion_token or not database_id:
        print("Error: NOTION_API_TOKEN or NOTION_DATABASE_ID not found in .env file")
        return

    notion = Client(auth=notion_token)

    # Notionのページプロパティを作成
    # TODO: NotionのDBカラム名に合わせてキーを修正する必要がある
    properties = {
        "タイトル": {
            "title": [{"text": {"content": metadata.get("title", "No Title")}}] 
        },
        "アーティスト": {
            "rich_text": [{"text": {"content": metadata.get("artist", "No Artist")}}] 
        },
        "アルバム": {
            "rich_text": [{"text": {"content": metadata.get("album", "No Album")}}] 
        },
        "トラックNo": {
            "number": int(metadata.get("track", 0))
        },
        "ファイル": {
            "files": [{"name": os.path.basename(file_path), "type": "external", "external": {"url": f"file://{file_path}"}}]
        }
    }

    try:
        notion.pages.create(
            parent={"database_id": database_id},
            properties=properties
        )
        print("Successfully added to Notion.")
    except Exception as e:
        print(f"Error adding to Notion: {e}")


def main():
    """
    メイン処理
    """
    # コマンドライン引数の設定
    parser = argparse.ArgumentParser(description="Extract metadata from an audio file and add it to Notion.")
    parser.add_argument("file_path", help="The path to the audio file.")
    args = parser.parse_args()

    # メタデータの取得
    metadata = get_audio_metadata(args.file_path)

    if metadata:
        # Notionへの追加
        add_to_notion(metadata, args.file_path)

if __name__ == "__main__":
    main()
