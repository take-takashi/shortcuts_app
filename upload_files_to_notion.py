import concurrent.futures
import datetime
import json
import logging
import logging.config
import os
import sys
from dataclasses import dataclass

import requests
from dotenv import load_dotenv
from notion_client import Client

# ===== Config Begin ===========================================================
# .envを読み込む
load_dotenv()
# 環境変数として取得
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_VERSION = "2022-06-28"
LOG_DIR = os.getenv("LOG_DIR", "~/Downloads")

# ===== Config End =============================================================


@dataclass
class MimeTypeInfo:
    """
    MIMEタイプと対応するファイルタイプの情報を表すデータクラス。

    属性:
        mime_type (str): MIMEタイプの文字列（例: 'image/png'）。
        file_type (str): 対応するファイルタイプで、Notionのアップロード時に使用（例: 'image, video'）。
    """

    mime_type: str
    file_type: str


class MyNotionClient:
    token: str
    notion: Client
    version: str
    CHUNK_SIZE: int = 10 * 1024 * 1024  # 10MB
    logger: logging.Logger

    def __init__(
        self,
        token: str,
        version: str = "2022-06-28",
        logger: logging.Logger = logging.getLogger(__name__),
    ):
        self.token = token
        self.notion = Client(auth=token)
        self.version = version
        self.logger = logger

    def create_notion_page(self, database_id: str, title: str) -> str:
        """
        指定したNotionデータベースに、指定したタイトルで新しいページを作成します。

        引数:
            database_id (str): ページを作成するNotionデータベースのID。
            title (str): 新しく作成するNotionページのタイトル。

        例外:
            Exception: ページ作成に失敗した場合、またはレスポンスが有効なNotionページオブジェクトでない場合に発生します。

        戻り値:
            作成したpege_id。
        """

        try:
            # TODO: タイトルが「名前」固定になっている
            response = self.notion.pages.create(
                parent={"database_id": database_id},
                properties={"名前": {"title": [{"text": {"content": title}}]}},
            )

            # 200OK以外はエラーを投げる
            if response.get("object") != "page":
                raise Exception("Failed to create page: Not a page object")

            # 作成したpage_idを返す
            return response.get("id")

        except Exception as e:
            raise Exception(f"Failed to create page: {e}")

        # End of create_notion_page method

    def upload_file(self, page_id: str, file_path: str):
        """
        指定したNotionページにファイルをアップロードします。

        引数:
            page_id (str): ファイルをアップロードするNotionページのID。
            file_path (str): アップロードするファイルのパス。

        例外:
            Exception: ファイルアップロードに失敗した場合に発生します。

        戻り値:
            なし
        """

        # TODO: 5GBを超える場合は、パートに分割してアップロードしたい（優先度：低　ffmpg使用か）

        try:
            # 20MB以下ならsingle_part、20MB超ならmulti_partとする（Notion APIの仕様）
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            mode = "single_part" if file_size <= 20 * 1024 * 1024 else "multi_part"

            # ファイルからMIMEタイプとファイルタイプを取得
            mime_type_info = self.get_mime_type_from_extension(file_path)
            payload = {}

            # Step 1: Create a File Upload object
            # 20MBを超えるかどうかでpayloadを変える必要がある
            if mode == "single_part":
                payload = {
                    "filename": file_name,
                }
            elif mode == "multi_part":
                # 10MBごとの分割数を計算
                number_of_parts = (file_size + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE
                payload = {
                    "filename": file_name,
                    "content_type": mime_type_info.mime_type,
                    "mode": "multi_part",
                    "number_of_parts": number_of_parts,
                }

            file_create_response = requests.post(
                "https://api.notion.com/v1/file_uploads",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "Notion-Version": self.version,
                },
            )

            if file_create_response.status_code != 200:
                raise Exception(
                    f"File creation failed with status code {file_create_response.status_code}: {file_create_response.text}"
                )

            file_upload_id = json.loads(file_create_response.text)["id"]
            self.logger.info(f"File upload ID: {file_upload_id}")

            # Step 2: Upload file contents
            upload_url = f"https://api.notion.com/v1/file_uploads/{file_upload_id}/send"
            upload_headers = {
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": self.version,
            }

            if mode == "single_part":
                with open(file_path, "rb") as f:
                    # Provide the MIME content type of the file as the 3rd argument.
                    files = {"file": (file_name, f, mime_type_info.mime_type)}

                    # ファイルそのものをアップロード
                    upload_response = requests.post(
                        url=upload_url,
                        headers=upload_headers,
                        files=files,
                    )

                    if upload_response.status_code != 200:
                        raise Exception(
                            f"File upload failed with status code {upload_response.status_code}: {upload_response.text}"
                        )

            elif mode == "multi_part":
                ## チャンクごとにアップロードする一時関数を定義
                def upload_chunk(part_number: int, chunk: bytes):
                    files = {
                        "file": (file_name, chunk, mime_type_info.mime_type),
                        "part_number": (None, str(part_number)),
                    }
                    self.logger.info(
                        f"Uploading part {part_number} of {number_of_parts}..."
                    )

                    response = requests.post(
                        url=upload_url,
                        headers=upload_headers,
                        files=files,
                    )
                    if response.status_code != 200:
                        raise Exception(
                            f"Failed to upload part {part_number}: {response.status_code} - {response.text}"
                        )

                with open(file_path, "rb") as f:
                    chunks = [
                        (i + 1, f.read(self.CHUNK_SIZE)) for i in range(number_of_parts)
                    ]

                # TODO CHECK: 一旦、5並列で実行する
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [
                        executor.submit(upload_chunk, part_number, chunk)
                        for part_number, chunk in chunks
                    ]
                    concurrent.futures.wait(futures)

                # 全チャンクのアップロードが成功した場合は、完了通知を送信
                complete_url = (
                    f"https://api.notion.com/v1/file_uploads/{file_upload_id}/complete"
                )
                complete_headers = {
                    "accept": "application/json",
                    "Authorization": f"Bearer {self.token}",
                    "Notion-Version": self.version,
                }

                # 完了通知を送信
                complete_response = requests.post(
                    complete_url,
                    headers=complete_headers,
                )

                if complete_response.status_code != 200:
                    raise Exception(
                        f"Failed to complete file upload with status code {complete_response.status_code}: {complete_response.text}"
                    )

            # Step 3: Attach the file to a page or block

            add_url = f"https://api.notion.com/v1/blocks/{page_id}/children"

            add_headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Notion-Version": self.version,
            }

            # MIMEタイプによってdataが変わる
            add_data = {
                "children": [
                    {
                        "type": mime_type_info.file_type,
                        mime_type_info.file_type: {
                            "caption": [
                                {
                                    "type": "text",
                                    "text": {"content": file_name, "link": None},
                                    "annotations": {
                                        "bold": False,
                                        "italic": False,
                                        "strikethrough": False,
                                        "underline": False,
                                        "code": False,
                                        "color": "default",
                                    },
                                    "plain_text": file_name,
                                    "href": "null",
                                }
                            ],
                            "type": "file_upload",
                            "file_upload": {"id": file_upload_id},
                        },
                    }
                ]
            }

            # ページの末尾にファイルを添付する
            add_response = requests.patch(
                add_url,
                headers=add_headers,
                data=json.dumps(add_data),
            )

            if add_response.status_code != 200:
                raise Exception(
                    f"Failed to attach file to page with status code {add_response.status_code}: {add_response.text}"
                )

        except Exception as e:
            raise Exception(f"Notionへのアップロードに失敗しました: {e}")

        # End of upload_file method

    def get_mime_type_from_extension(self, file_path: str) -> MimeTypeInfo:
        """
        指定されたファイルパスの拡張子から、MIMEタイプおよびファイルタイプを判定します。

        引数:
            filepath (str): MIMEタイプを判定したいファイルのパス。

        戻り値:
            MimeTypeInfo: MIMEタイプおよびファイルタイプを含むオブジェクト。拡張子が未対応の場合は
                デフォルトで "application/octet-stream" および "image" を返します。
        """

        extension = os.path.splitext(file_path)[1].lower()
        mime_types = {
            ".mp4": MimeTypeInfo(mime_type="application/mp4", file_type="video"),
            ".jpg": MimeTypeInfo(mime_type="image/jpeg", file_type="image"),
            ".jpeg": MimeTypeInfo(mime_type="image/jpeg", file_type="image"),
            ".png": MimeTypeInfo(mime_type="image/png", file_type="image"),
            ".gif": MimeTypeInfo(mime_type="image/gif", file_type="image"),
            ".webp": MimeTypeInfo(mime_type="image/webp", file_type="image"),
            ".mp3": MimeTypeInfo(mime_type="audio/mpeg", file_type="audio"),
            ".m4a": MimeTypeInfo(mime_type="audio/mp4", file_type="audio"),
        }
        return mime_types.get(
            extension,
            MimeTypeInfo(mime_type="application/octet-stream", file_type="image"),
        )


def setup_logger(dir: str = "") -> logging.Logger:
    """
    JSON設定ファイルに基づいてロガーをセットアップし、返します。

    この関数は以下の手順を実行します:
    1. 'logging_config.json' からロギング設定を読み込む。
    2. クロスプラットフォームでユーザーのDownloadsディレクトリを取得し、存在しなければ作成する。
    3. スクリプト名と日付からログファイル名を生成する。
    4. ログ設定のファイルハンドラのパスを生成したログファイルに書き換える。
    5. ログ設定を適用し、ロガーインスタンスを返す。

    戻り値:
        logging.Logger: 設定済みのロガーインスタンス

    """
    logger = logging.getLogger(__name__)
    with open("logging_config.json", "r") as f:
        config = json.load(f)
    # Downloadsディレクトリの取得（クロスプラットフォーム）
    downloads_dir = dir
    os.makedirs(downloads_dir, exist_ok=True)  # 念のため存在確認
    # 実行ファイル名からログファイル名を決定
    script_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    today = datetime.datetime.now().strftime("%Y%m%d")
    log_filename = f"{script_name}-{today}.log"
    log_path = os.path.join(downloads_dir, log_filename)
    # ファイルハンドラのファイル名を動的に置き換え
    config["handlers"]["file"]["filename"] = log_path
    # ログ設定を適用
    logging.config.dictConfig(config)
    return logger


def main():
    try:
        # ロガーのセットアップ
        logger = setup_logger(LOG_DIR)

        # コマンドライン引数を取得
        args = sys.argv[1:]
        logger.info(f"Arguments: {args}")

        # Notionクライアントのインスタンスを作成
        notion = MyNotionClient(
            token=NOTION_TOKEN,
            version=NOTION_VERSION,
            logger=logger,
        )

        # コマンドライン引数をそれぞれファイルパスとして処理する
        files = args

        for file in files:
            # fileの存在確認
            if not os.path.isfile(file):
                logger.error(f"File not found: {file}")
                continue

            # ファイルのサイズをチェックし、5GB以下であればそのままアップロード
            file_size = os.path.getsize(file)
            if file_size > 5 * 1024 * 1024 * 1024:  # 5GB
                logging.warning(
                    f"5GBを超えるファイルはアップロードしません。: {file} (size: {file_size} bytes)"
                )
                continue

            # ファイル名のページをDBに対して作成する
            page_id = notion.create_notion_page(
                database_id=NOTION_DATABASE_ID,
                title=os.path.basename(file),  # ファイル名をタイトルとして使用
            )

            # ファイルのアップロード処理をここに追加する
            notion.upload_file(page_id, file)

            logging.info(f"Successfully processed file: {file}")

            # エラーなく添付できたらファイルを削除する

    except Exception as e:
        logger.error(e)
        sys.exit(1)

    # end of main function


if __name__ == "__main__":
    main()
    exit(0)
