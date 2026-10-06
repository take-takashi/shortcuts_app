import os
from unittest.mock import MagicMock, patch

import pytest

from MyNotionHelper.my_notion_helper import MyNotionHelper


@pytest.fixture
def notion_helper():
    """MyNotionHelperのモックインスタンスを作成するフィクスチャ"""
    # モックされたClientインスタンスを返すようにpatchを適用
    with patch('notion_client.Client') as mock_client_class:
        # ClientのインスタンスをMagicMockに設定
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance
        
        # MyNotionHelperをダミートークンで初期化
        helper = MyNotionHelper(token="dummy_token")
        # ヘルパーにモッククライアントを注入
        helper.notion = mock_instance
        return helper

def test_add_music_info_to_db(notion_helper):
    """add_music_info_to_dbが正しい引数でnotion.pages.createを呼び出すかテスト"""
    # --- 準備 (Arrange) ---
    # テスト用のダミーデータ
    test_metadata = {
        "title": "Test Title",
        "artist": "Test Artist",
        "album": "Test Album",
        "track": "1/10"
    }
    test_file_path = "/path/to/dummy/file.m4a"
    test_db_id = "dummy_db_id"

    # --- 実行 (Act) ---
    notion_helper.add_music_info_to_db(test_metadata, test_file_path, test_db_id)

    # --- 検証 (Assert) ---
    # notion.pages.createが1回だけ呼び出されたことを確認
    notion_helper.notion.pages.create.assert_called_once()

    # 呼び出し時の引数を取得
    call_args, call_kwargs = notion_helper.notion.pages.create.call_args

    # parent引数が正しいか検証
    assert call_kwargs.get("parent") == {"database_id": test_db_id}

    # properties引数が正しいか検証
    properties = call_kwargs.get("properties", {})
    assert properties["タイトル"]["title"][0]["text"]["content"] == "Test Title"
    assert properties["アーティスト"]["rich_text"][0]["text"]["content"] == "Test Artist"
    assert properties["アルバム"]["rich_text"][0]["text"]["content"] == "Test Album"
    assert properties["No"]["rich_text"][0]["text"]["content"] == "1/10"
    assert properties["ファイル"]["files"][0]["name"] == "file.m4a"


def test_add_comment_posts_comment_to_page(notion_helper):
    notion_helper.add_comment("page-id", "A summary")

    notion_helper.notion.comments.create.assert_called_once_with(
        parent={"page_id": "page-id"},
        rich_text=[{"type": "text", "text": {"content": "A summary"}}],
    )


def test_add_comment_splits_long_text(notion_helper):
    comment = "a" * 2001
    notion_helper.add_comment("page-id", comment)

    rich_text = notion_helper.notion.comments.create.call_args.kwargs["rich_text"]
    assert len(rich_text) == 2
    assert "".join(item["text"]["content"] for item in rich_text) == comment


def test_add_comment_rejects_empty_text(notion_helper):
    with pytest.raises(ValueError, match="コメントが空"):
        notion_helper.add_comment("page-id", "  ")

    notion_helper.notion.comments.create.assert_not_called()
