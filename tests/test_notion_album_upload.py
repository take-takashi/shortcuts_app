from unittest.mock import Mock

import pytest
import requests

import MyNotionHelper.my_notion_helper as module
from MyNotionHelper.my_notion_helper import MyNotionHelper


@pytest.fixture
def helper():
    result = MyNotionHelper("dummy-token")
    result.notion = Mock()
    return result


def response(data=None, status=200):
    result = Mock(status_code=status, headers={})
    result.json.return_value = data or {}
    result.text = "mock response"
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


def test_zip_is_a_generic_file(helper):
    info = helper.get_mime_type_from_extension("capture.zip")
    assert (info.mime_type, info.file_type) == ("application/zip", "file")


def test_position_uses_new_api_without_breaking_database_version(helper, monkeypatch):
    patch = Mock(return_value=response({"results": [{"id": "image-block"}]}))
    monkeypatch.setattr(module.requests, "patch", patch)
    assert (
        helper.attach_uploaded_file(
            "page", "upload", "cover.jpg", "image", position={"type": "start"}
        )
        == "image-block"
    )
    kwargs = patch.call_args.kwargs
    assert kwargs["headers"]["Notion-Version"] == "2026-03-11"
    assert kwargs["json"]["position"] == {"type": "start"}
    assert kwargs["json"]["children"][0]["image"]["file_upload"] == {"id": "upload"}
    assert helper.version == "2022-06-28"
    assert kwargs["timeout"]


def test_icon_uses_uploaded_file_not_temporary_download_url(helper, monkeypatch):
    patch = Mock(return_value=response())
    monkeypatch.setattr(module.requests, "patch", patch)
    helper.set_page_icon("album-page", "cover-upload")
    assert patch.call_args.args[0].endswith("/pages/album-page")
    assert patch.call_args.kwargs["json"] == {
        "icon": {"type": "file_upload", "file_upload": {"id": "cover-upload"}}
    }


def test_file_property_puts_cover_and_zip_before_old_files(helper):
    helper.notion.pages.retrieve.return_value = {
        "properties": {
            "添付": {
                "type": "files",
                "files": [
                    {
                        "name": "old.txt",
                        "type": "file",
                        "file": {
                            "url": "https://notion.test/file",
                            "expiry_time": "soon",
                        },
                    },
                ],
            }
        }
    }
    files = [
        {"name": "cover.jpg", "type": "file_upload", "file_upload": {"id": "cover"}},
        {"name": "capture.zip", "type": "file_upload", "file_upload": {"id": "zip"}},
    ]
    helper.update_file_property("page", files, prepend=True)
    saved = helper.notion.pages.update.call_args.kwargs["properties"]["添付"]["files"]
    assert [f["name"] for f in saved] == ["cover.jpg", "capture.zip", "old.txt"]
    assert saved[-1]["file"] == {"url": "https://notion.test/file"}
    helper.notion.pages.retrieve.return_value["properties"]["添付"]["files"] = saved
    helper.update_file_property("page", files, prepend=True)
    assert (
        helper.notion.pages.update.call_args.kwargs["properties"]["添付"]["files"]
        == saved
    )


@pytest.mark.parametrize(
    "name",
    [
        "a" * 96 + ".jpg",  # ちょうど100コード単位
        "𝑻" * 48 + ".jpg",  # サロゲートペアを含めて100コード単位
    ],
)
def test_file_reference_keeps_names_at_the_limit(name):
    assert MyNotionHelper.upload_reference(name, "upload")["name"] == name


def test_file_reference_shortens_long_unicode_names_without_collisions():
    names = ["𝑻" * 50 + "ディズニー🎄" + tail + ".jpg" for tail in ("一", "二")]
    shortened = [
        MyNotionHelper.upload_reference(name, "upload")["name"] for name in names
    ]

    assert shortened[0] != shortened[1]
    assert shortened[0] == MyNotionHelper.upload_reference(names[0], "other")["name"]
    assert all(len(name.encode("utf-16-le")) // 2 <= 100 for name in shortened)
    assert all(name.endswith(".jpg") for name in shortened)


def test_upload_file_uses_short_name_for_property_and_preserves_local_name(
    helper, tmp_path
):
    helper.upload_file_data = Mock(return_value="upload")
    helper.attach_uploaded_file = Mock()
    helper.notion.pages.retrieve.return_value = {
        "properties": {"ファイル&メディア": {"type": "files", "files": []}}
    }
    # 実際の障害と同じく、Pythonの文字数は100以下でもUTF-16では100を超える。
    source = tmp_path / ("𝑻" * 48 + "🎄.jpg")
    source.write_bytes(b"image")

    helper.upload_file("page", str(source))

    helper.upload_file_data.assert_called_once_with(str(source))
    helper.attach_uploaded_file.assert_called_once_with(
        "page", "upload", source.name, "image"
    )
    properties = helper.notion.pages.update.call_args.kwargs["properties"]
    saved = properties["ファイル&メディア"]["files"][0]
    assert len(saved["name"].encode("utf-16-le")) // 2 <= 100
    assert saved["name"].endswith(".jpg")
    assert saved["file_upload"] == {"id": "upload"}
    assert source.exists()


def test_upload_size_is_obtained_from_workspace(helper):
    helper.notion.users.me.return_value = {
        "bot": {"workspace_limits": {"max_file_upload_size_in_bytes": 5242880}}
    }
    assert helper.get_max_upload_size() == 5242880


def test_missing_limit_is_not_assumed_to_be_paid_plan(helper):
    helper.notion.users.me.return_value = {"bot": {}}
    with pytest.raises(ValueError, match="上限"):
        helper.get_max_upload_size()


def test_multipart_failure_never_sends_complete(helper, monkeypatch, tmp_path):
    source = tmp_path / "capture.zip"
    with source.open("wb") as stream:
        stream.truncate(21 * 1024**2)
    post = Mock(
        side_effect=[
            response({"id": "upload"}),
            response(status=503),
            response(status=503),
            response(status=503),
        ]
    )
    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    with pytest.raises(requests.HTTPError):
        helper.upload_file_data(str(source))
    assert not any("/complete" in str(c) for c in post.call_args_list)


def test_multipart_streams_each_part_and_completes_only_after_success(
    helper, monkeypatch, tmp_path
):
    source = tmp_path / "capture.zip"
    with source.open("wb") as stream:
        stream.truncate(21 * 1024**2)
    sent = []

    def post(url=None, **kwargs):
        if url.endswith("/send"):
            sent.append(len(kwargs["files"]["file"][1]))
            assert kwargs["files"]["part_number"][1] == str(len(sent))
            return response()
        return response({"id": "upload"})

    monkeypatch.setattr(module.requests, "post", post)
    assert helper.upload_file_data(str(source)) == "upload"
    assert sent == [10 * 1024**2, 10 * 1024**2, 1024**2]


def test_strict_tag_lookup_does_not_create_after_query_failure(helper):
    helper.notion.databases.query.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        helper.get_or_create_tag_page("tags", "album", "音楽", strict=True)
    helper.notion.pages.create.assert_not_called()


def test_strict_tag_lookup_refuses_ambiguous_titles(helper):
    helper.notion.databases.query.return_value = {
        "results": [{"id": "one"}, {"id": "two"}]
    }
    with pytest.raises(ValueError, match="複数"):
        helper.get_or_create_tag_page("tags", "album", "音楽", strict=True)
    helper.notion.pages.create.assert_not_called()
