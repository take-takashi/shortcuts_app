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
