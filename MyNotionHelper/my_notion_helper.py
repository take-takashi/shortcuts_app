import hashlib
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import requests
from notion_client import Client

from pyav_split_by_5gib import split_video

NOTION_MAX_VIDEO_SIZE = 5 * 1024**3
NOTION_VIDEO_SPLIT_SIZE = NOTION_MAX_VIDEO_SIZE - 100 * 1024**2


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
            response = self.notion.databases.query(  # type: ignore
                database_id=database_id,
                # プロパティ「処理済」が未チェックのアイテムを取得
                filter={"property": "処理済", "checkbox": {"equals": False}},
            )

            return response.get("results", [])  # type: ignore

        # 何かしらのエラーが発生した場合は空のリストを返す
        except Exception as e:
            raise Exception(f"Notionデータベースの取得に失敗しました: {e}")

    def get_page_id_by_title(
        self,
        database_id: str,
        title: str,
        property_name: str = "Name",
        *,
        strict: bool = False,
    ) -> str | None:
        """
        指定されたデータベース内で、タイトルに一致するページのIDを取得します。
        """
        try:
            response = self.notion.databases.query(
                database_id=database_id,
                filter={
                    # "property": "タイトル",  # Notionのタイトルプロパティは通常「タイトル」
                    # "property": "Name",  # 自分のページでは「Name」だったため変更
                    "property": property_name,
                    "title": {"equals": title},
                },
            )
            results = response.get("results")  # type: ignore[reportAttributeAccessIssue]
            if strict and results and len(results) > 1:
                raise ValueError(f"同じ名前のタグが複数あります: {title}")
            if results and len(results) > 0:
                return results[0]["id"]
            return None
        except Exception as e:
            if strict:
                raise
            self.logger.error(
                f"Failed to get page ID by title '{title}' in database '{database_id}': {e}"
            )
            return None

    def get_or_create_tag_page(
        self, database_id: str, title: str, category: str, *, strict: bool = False
    ) -> str | None:
        """
        指定されたデータベースでタイトルに一致するページを取得、なければ作成します。
        作成する場合、指定されたカテゴリも設定します。
        """
        # まずページを検索
        page_id = self.get_page_id_by_title(database_id, title, strict=strict)
        if page_id:
            return page_id

        # ページがなければ作成
        self.logger.info(
            f"'{title}' not found in database {database_id}. Creating new page..."
        )
        try:
            properties = {
                "Name": {"title": [{"text": {"content": title}}]},
                "Category": {"select": {"name": category}},
            }
            new_page_response: dict = self.notion.pages.create(
                parent={"database_id": database_id}, properties=properties
            )  # type: ignore
            new_page_id = new_page_response.get("id")
            if new_page_id:
                self.logger.info(f"Created page with ID: {new_page_id}")
                return new_page_id
            else:
                if strict:
                    raise RuntimeError(f"タグページIDを取得できません: {title}")
                self.logger.error(f"Failed to create page for title '{title}'.")
                return None
        except Exception as e:
            if strict:
                raise
            self.logger.error(f"Failed to get or create page for title '{title}': {e}")
            return None

    # NotionのDBに空のページを作成する関数
    def create_blank_page(self, database_id: str) -> str:
        """
        指定したNotionデータベースに空のページを作成します。

        引数:
            database_id (str): ページを作成する対象のNotionデータベースID。

        戻り値:
            str: 作成されたページのID。

        例外:
            Exception: ページの作成に失敗した場合に発生します。
        """
        try:
            response = self.notion.pages.create(
                parent={"database_id": database_id},
            )  # type: ignore

            # 200OK以外はエラーを投げる
            if response.get("object") != "page":  # type: ignore
                raise Exception("Failed to create page: Not a page object")

            # 作成したpage_idを返す
            return response.get("id") or ""  # type: ignore
        except Exception as e:
            raise Exception(f"Failed to create page: {e}")

    # End of create_blank_page method

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
            blocks: dict = self.notion.blocks.children.list(block_id=page_id)  # type: ignore

            # ブロック群が取得できなかったときは失敗
            if blocks is None:
                return False

            children = blocks["results"]

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
    def get_item_property_url(self, item) -> str:
        """
        Notionアイテムのプロパティから「URL」フィールドの値を取得します。

        引数:
            item (dict): Notion APIから取得した1件のデータベースアイテム。

        戻り値:
            str: アイテムの「URL」プロパティに設定されたURL文字列。
                 プロパティが存在しない場合や未設定の場合は空文字列を返します。

        例外:
            Exception: プロパティの取得に失敗した場合（フォーマット不整合など）。
        """

        # アイテムのプロパティからURLを取得
        try:
            if "URL" in item["properties"]:
                return item["properties"]["URL"]["url"]
            else:
                return ""
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

    def add_comment(self, page_id: str, comment: str) -> Any:
        """Notionページにコメントを追加する。"""
        if not comment.strip():
            raise ValueError("コメントが空です。")

        # Notionのrich_text要素は1件あたり最大2000文字。
        chunk_size = 1900
        rich_text = [
            {"type": "text", "text": {"content": comment[i : i + chunk_size]}}
            for i in range(0, len(comment), chunk_size)
        ]
        if len(rich_text) > 100:
            raise ValueError("コメントが長すぎます（rich_text要素は最大100件です）。")

        try:
            return self.notion.comments.create(
                parent={"page_id": page_id},
                rich_text=rich_text,
            )
        except Exception as e:
            raise Exception(f"ページID「{page_id}」へのコメント投稿に失敗しました: {e}")

    def upload_file_data(self, file_path: str) -> str:
        """実体だけを送信し、添付前のfile_upload IDを返す。"""

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
                    "content_type": mime_type_info.mime_type,
                    "mode": "single_part",
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
                timeout=(10, 180),
            )

            file_create_response.raise_for_status()
            file_upload_id = file_create_response.json()["id"]
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
                        timeout=(10, 180),
                    )
                    upload_response.raise_for_status()

            elif mode == "multi_part":
                # ZIP全体をメモリに載せず、10MiBずつ送る。各パートの再送は冪等。
                with open(file_path, "rb") as source:
                    for part_number in range(1, number_of_parts + 1):
                        chunk = source.read(self.CHUNK_SIZE)
                        if not chunk:
                            raise ValueError("送信中にファイルサイズが変わりました。")
                        for attempt in range(3):
                            self.logger.info(
                                "送信中: %s (%d/%d)",
                                file_name,
                                part_number,
                                number_of_parts,
                            )
                            try:
                                response = requests.post(
                                    url=upload_url,
                                    headers=upload_headers,
                                    files={
                                        "file": (
                                            file_name,
                                            chunk,
                                            mime_type_info.mime_type,
                                        ),
                                        "part_number": (None, str(part_number)),
                                    },
                                    timeout=(10, 180),
                                )
                                response.raise_for_status()
                                break
                            except requests.RequestException as exc:
                                status = (
                                    exc.response.status_code
                                    if exc.response is not None
                                    else None
                                )
                                if attempt == 2 or (
                                    status is not None
                                    and status < 500
                                    and status != 429
                                ):
                                    raise
                                delay = 2**attempt
                                if exc.response is not None and status == 429:
                                    try:
                                        delay = min(
                                            120,
                                            max(
                                                1,
                                                float(
                                                    exc.response.headers.get(
                                                        "Retry-After", delay
                                                    )
                                                ),
                                            ),
                                        )
                                    except (ValueError, TypeError):
                                        pass
                                time.sleep(delay)
                        del chunk
                # 失敗したパートがある場合はここに到達しない。
                complete_response = requests.post(
                    f"https://api.notion.com/v1/file_uploads/{file_upload_id}/complete",
                    headers=upload_headers,
                    timeout=(10, 180),
                )
                complete_response.raise_for_status()

            return file_upload_id
        except Exception:
            self.logger.error("Notionへのファイル送信に失敗しました。")
            raise

    def upload_file(self, page_id: str, file_path: str):
        """従来の呼び出し用。送信・本文添付・ファイルプロパティ更新を行う。"""
        upload_id = self.upload_file_data(file_path)
        name = os.path.basename(file_path)
        kind = self.get_mime_type_from_extension(file_path).file_type
        self.attach_uploaded_file(page_id, upload_id, name, kind)
        self.update_file_property(page_id, [self.upload_reference(name, upload_id)])

    @staticmethod
    def upload_reference(name: str, upload_id: str) -> dict:
        # Notionのファイルプロパティの名前はUTF-16で100コード単位まで。
        # 長い名前だけ短縮し、ハッシュで同じ接頭辞のファイルを区別する。
        def units(text: str) -> int:
            return len(text.encode("utf-16-le")) // 2

        if units(name) > 100:
            stem, extension = os.path.splitext(name)
            if units(extension) > 32:
                stem, extension = name, ""
            digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
            suffix = f"-{digest}{extension}"
            remaining = 100 - units(suffix)
            prefix = ""
            for character in stem:
                size = units(character)
                if size > remaining:
                    break
                prefix += character
                remaining -= size
            name = prefix + suffix
        return {"name": name, "type": "file_upload", "file_upload": {"id": upload_id}}

    def attach_uploaded_file(
        self,
        page_id: str,
        upload_id: str,
        name: str,
        kind: str,
        *,
        position: dict | None = None,
    ) -> str:
        """本文へ1ブロックを追加し、再開用にブロックIDを返す。"""
        media: dict[str, Any] = {
            "type": "file_upload",
            "file_upload": {"id": upload_id},
            "caption": [{"type": "text", "text": {"content": name}}],
        }
        if kind == "file":
            media["name"] = name
        payload: dict[str, Any] = {
            "children": [{"object": "block", "type": kind, kind: media}]
        }
        if position is not None:
            payload["position"] = position
        response = requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            # 位置指定だけ新APIを使用し、既存database queryの互換性を保つ。
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": "2026-03-11"
                if position is not None
                else self.version,
            },
            json=payload,
            timeout=(10, 180),
        )
        response.raise_for_status()
        return response.json()["results"][0]["id"]

    def set_page_icon(self, page_id: str, upload_id: str) -> None:
        """期限付きURLではなく、アップロード実体をアイコンに使う。"""
        response = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": "2026-03-11",
            },
            json={"icon": {"type": "file_upload", "file_upload": {"id": upload_id}}},
            timeout=(10, 180),
        )
        response.raise_for_status()

    def update_file_property(
        self, page_id: str, files: list[dict], *, prepend: bool = False
    ) -> None:
        """最初のfilesプロパティを更新し、既存添付と新規添付の順序を保つ。"""
        page = cast(dict[str, Any], self.notion.pages.retrieve(page_id=page_id))
        for name, prop in page.get("properties", {}).items():
            if prop.get("type") != "files":
                continue
            incoming_names = {entry["name"] for entry in files}
            existing = []
            for entry in prop.get("files", []):
                if entry["name"] in incoming_names:
                    continue
                kind = entry["type"]
                key = "id" if kind == "file_upload" else "url"
                existing.append(
                    {"name": entry["name"], "type": kind, kind: {key: entry[kind][key]}}
                )
            ordered = files + existing if prepend else existing + files
            self.notion.pages.update(
                page_id=page_id, properties={name: {"files": ordered}}
            )
            return

    def file_upload_is_ready(self, upload_id: str) -> bool:
        """未添付アップロードの期限切れを、再開時に確認する。"""
        response = requests.get(
            f"https://api.notion.com/v1/file_uploads/{upload_id}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": self.version,
            },
            timeout=(10, 180),
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return response.json().get("status") == "uploaded"

    def get_max_upload_size(self) -> int:
        """プラン上限と分割アップロードの閾値を混同しない。"""
        user = cast(dict[str, Any], self.notion.users.me())
        limit = (
            user.get("bot", {})
            .get("workspace_limits", {})
            .get("max_file_upload_size_in_bytes")
        )
        if type(limit) is not int or limit <= 0:
            raise ValueError("Notionワークスペースのファイル上限を取得できません。")
        return limit

    def create_music_page(
        self,
        metadata: dict,
        database_id: str,
        album_id: str | None,
        album_artist_id: str | None,
    ) -> str:
        """ページ作成と音声送信の間で再開情報を保存できるよう共通化する。"""

        # Notionのページプロパティを作成（ファイルプロパティはupload_file関数で処理）
        properties = {
            "タイトル": {
                "title": [{"text": {"content": metadata.get("title", "No Title")}}]
            },
            "No": {"rich_text": [{"text": {"content": metadata.get("track", "-")}}]},
            "トラックアーティスト": {
                "rich_text": [
                    {"text": {"content": metadata.get("artist", "No Artist")}}
                ]
            },
        }

        # アルバムのリレーションプロパティを追加
        if album_id:
            properties["アルバム"] = {"relation": [{"id": album_id}]}  # type: ignore
        else:
            properties["アルバム"] = {"relation": []}  # type: ignore

        # アルバムアーティストのリレーションプロパティを追加
        if album_artist_id:
            properties["アルバムアーティスト"] = {"relation": [{"id": album_artist_id}]}  # type: ignore
        else:
            properties["アルバムアーティスト"] = {"relation": []}  # type: ignore

        response = cast(
            dict[str, Any],
            self.notion.pages.create(
                parent={"database_id": database_id}, properties=properties
            ),
        )
        page_id = response.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise RuntimeError("曲ページIDを取得できません。")
        return page_id

    def add_music_info_to_db(
        self, metadata: dict, file_path: str, database_id: str, tags_database_id: str
    ):
        """従来の単曲アップロードも同じページ作成・送信処理を使う。"""
        album_id = self.get_or_create_tag_page(
            tags_database_id, metadata.get("album", "No Album"), "音楽"
        )
        artist_id = self.get_or_create_tag_page(
            tags_database_id, metadata.get("album_artist", "No Album Artist"), "音楽"
        )
        page_id = self.create_music_page(metadata, database_id, album_id, artist_id)
        self.upload_file(page_id=page_id, file_path=file_path)

    # 指定したNotionページに動画をアップロードする関数（5GiB超え分割機能有）
    def upload_video(self, page_id: str, file_path: str):
        """
        指定したNotionページに動画をアップロードします。
        5GiBを超える動画はPyAVで分割し、同じページへ順番にアップロードします。

        引数:
            page_id (str): ファイルをアップロードするNotionページのID。
            file_path (str): アップロードするファイルのパス。

        例外:
            Exception: ファイルアップロードまたは分割に失敗した場合に発生します。

        戻り値:
            なし
        """
        if not os.path.isfile(file_path):
            raise Exception(f"File not found: {file_path}")

        source_path = Path(file_path).expanduser().resolve()
        if source_path.stat().st_size <= NOTION_MAX_VIDEO_SIZE:
            self.upload_file(page_id, str(source_path))
            return

        self.logger.info(
            "動画がNotionの5GiB上限を超えているため、PyAVで分割します: %s",
            source_path,
        )
        with tempfile.TemporaryDirectory(
            prefix=".notion-video-parts-",
            dir=str(source_path.parent),
        ) as temporary_directory:
            part_paths = split_video(
                source_path,
                output_dir=Path(temporary_directory),
                max_size=NOTION_VIDEO_SPLIT_SIZE,
            )
            self.logger.info("動画を%d個のパートに分割しました。", len(part_paths))

            # 同じpage_idにpart001, part002...の順で追加する。
            for index, part_path in enumerate(part_paths, start=1):
                self.logger.info(
                    "Notionページへ動画パートをアップロード中 (%d/%d): %s",
                    index,
                    len(part_paths),
                    part_path.name,
                )
                self.upload_file(page_id, str(part_path))

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
            ".zip": MimeTypeInfo(mime_type="application/zip", file_type="file"),
        }
        return mime_types.get(
            extension,
            MimeTypeInfo(mime_type="application/octet-stream", file_type="image"),
        )
