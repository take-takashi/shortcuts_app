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
    test_metadata = {
        "title": "Test Title",
        "artist": "Test Artist",
        "album": "Test Album",
        "album_artist": "Test Album Artist",
        "track": "1/10",
    }
    test_file_path = "/path/to/dummy/file.m4a"
    test_db_id = "dummy_db_id"
    tags_database_id = "dummy_tags_db_id"
    notion_helper.notion.pages.create.return_value = {"id": "page-id"}

    with (
        patch.object(
            notion_helper,
            "get_or_create_tag_page",
            side_effect=["album-tag-id", "album-artist-tag-id"],
        ) as get_or_create_tag_page,
        patch.object(notion_helper, "upload_file") as upload_file,
    ):
        notion_helper.add_music_info_to_db(
            test_metadata, test_file_path, test_db_id, tags_database_id
        )

    get_or_create_tag_page.assert_any_call(tags_database_id, "Test Album", "音楽")
    get_or_create_tag_page.assert_any_call(
        tags_database_id, "Test Album Artist", "音楽"
    )
    notion_helper.notion.pages.create.assert_called_once()
    call_kwargs = notion_helper.notion.pages.create.call_args.kwargs
    assert call_kwargs["parent"] == {"database_id": test_db_id}
    properties = call_kwargs["properties"]
    assert properties["タイトル"]["title"][0]["text"]["content"] == "Test Title"
    assert properties["No"]["rich_text"][0]["text"]["content"] == "1/10"
    assert (
        properties["トラックアーティスト"]["rich_text"][0]["text"]["content"]
        == "Test Artist"
    )
    assert properties["アルバム"]["relation"] == [{"id": "album-tag-id"}]
    assert properties["アルバムアーティスト"]["relation"] == [
        {"id": "album-artist-tag-id"}
    ]
    upload_file.assert_called_once_with(page_id="page-id", file_path=test_file_path)


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
