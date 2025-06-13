import json
import logging
import logging.config
import os
from dataclasses import dataclass

import requests
from notion_client import Client


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


class MyNotionHelper:
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

    # Notionデータベースからアイテムを取得する関数
    def get_items(self, database_id) -> list:
        try:
            response = self.notion.databases.query(
                database_id=database_id,
                # プロパティ「処理済」が未チェックのアイテムを取得
                filter={"property": "処理済", "checkbox": {"equals": False}},
            )
            return response.get("results", [])

        # 何かしらのエラーが発生した場合は空のリストを返す
        except Exception as e:
            raise Exception(f"Notionデータベースの取得に失敗しました: {e}")

    # 指定したNotionデータベースに、指定したタイトルで新しいページを作成する関数
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

    # 指定したNotionページ内のすべての子ブロック（コンテンツ）を削除する関数
    def delete_page_content(self, page_id: str) -> bool:
        """
        指定したNotionページ内のすべての子ブロック（コンテンツ）を削除します。
        引数:
            page_id (str): コンテンツを削除するNotionページのID。
        戻り値:
            bool: すべての子ブロックの削除に成功した場合はTrue、失敗した場合はFalse。
        例外:
            削除処理中に例外が発生した場合はエラーメッセージを出力します。
        """

        try:
            # 1. ページ内の子ブロックを取得
            children = self.notion.blocks.children.list(block_id=page_id)["results"]

            # 2. 各ブロックを削除
            for block in children:
                block_id = block["id"]
                self.notion.blocks.delete(block_id)

            return True

        except Exception as e:
            raise Exception(
                f"ページID「 {page_id}」のコンテンツ削除に失敗しました: {e}"
            )

    # アイテムのプロパティからURLを取得する関数
    def get_item_propertie_url(self, item) -> str:
        # アイテムのプロパティからURLを取得
        try:
            if "URL" in item["properties"]:
                return item["properties"]["URL"]["url"]
            else:
                return None
        except Exception as e:
            raise Exception(f"アイテムのプロパティからURLを取得できませんでした: {e}")

    # 指定したNotionページのタイトルを変更する関数
    def change_page_title(self, page_id: str, new_title: str) -> bool:
        """
        指定したNotionページのタイトルを変更します。
        引数:
            page_id (str): タイトルを変更するNotionページのID。
            new_title (str): 新しいタイトル。
        戻り値:
            bool: タイトルの変更に成功した場合はTrue、失敗した場合はFalse。
        例外:
            タイトル変更中に例外が発生した場合はエラーメッセージを出力します。
        """

        try:
            # ページのプロパティを更新
            self.notion.pages.update(
                page_id=page_id,
                properties={"title": {"title": [{"text": {"content": new_title}}]}},
            )
            return True

        except Exception as e:
            raise Exception(f"ページID「{page_id}」のタイトル変更に失敗しました: {e}")

    # Notionのページのプロパティ「処理済」を操作する関数
    def change_item_processed_status(
        self, item_id: str, property_name: str = "処理済", status: bool = True
    ) -> bool:
        """
        アイテムのチェックボックスプロパティ「処理済（デフォルト）」を更新する関数。

        Args:
            item_id (str): 更新するアイテムのID。
            status (bool): 新しいステータス（True: 処理済, False: 未処理）。
        """
        try:
            self.notion.pages.update(
                page_id=item_id, properties={property_name: {"checkbox": status}}
            )
            return True

        except Exception as e:
            raise Exception(
                f"アイテムID「 {item_id}」の「{property_name}」ステータス更新に失敗: {e}"
            )

    # 指定したNotionページにファイルをアップロードする関数
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
                with open(file_path, "rb") as f:
                    # チャンクサイズごとにファイルを読み込む
                    for part_number in range(1, number_of_parts + 1):
                        chunk = f.read(self.CHUNK_SIZE)
                        if not chunk:
                            break

                        files = {
                            # Provide the MIME content type of the file
                            # as the 3rd argument.
                            "file": (file_name, chunk, mime_type_info.mime_type),
                            # Use a file name of `None` to treat this as a regular
                            # form field and not a file.
                            "part_number": (None, str(part_number)),
                        }
                        self.logger.info(
                            f"Uploading part {part_number} of {number_of_parts}..."
                        )

                        # ファイルのチャンクをアップロード
                        upload_response = requests.post(
                            url=upload_url,
                            headers=upload_headers,
                            files=files,
                        )

                        if upload_response.status_code != 200:
                            raise Exception(
                                f"Failed to upload part {part_number}: {upload_response.status_code} - {upload_response.text}"
                            )

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

    # ファイルパスを渡して拡張子からMIMEタイプを返す関数
    def get_mime_type_from_extension(self, file_path: str) -> MimeTypeInfo:
        """
        指定されたファイルパスの拡張子から、MIMEタイプおよびファイルタイプを判定します。

        引数:
            filepath (str): MIMEタイプを判定したいファイルのパス。

        戻り値:
            MimeTypeInfo: MIMEタイプおよびファイルタイプを含むオブジェクト。拡張子が未対応の場合は
                デフォルトで "application/octet-stream" および "image" を返します。
        """

        # ファイルの拡張子を取得
        extension = os.path.splitext(file_path)[1].lower()
        # 拡張子からNotionに適したMIMEタイプを定義
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
