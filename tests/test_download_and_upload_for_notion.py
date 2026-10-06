import subprocess
from unittest.mock import Mock, patch

import pytest

import download_and_upload_for_notion as workflow


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc",
        "https://music.youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "https://www.tiktok.com/@user/video/123",
        "https://x.com/user/status/123",
        "https://mobile.twitter.com/user/status/123",
        "https://t.co/short-link",
    ],
)
def test_ytdlp_domains_are_recognized(url):
    assert workflow.is_ytdlp_url(url)


def test_non_ytdlp_domain_is_not_recognized():
    assert not workflow.is_ytdlp_url("https://notyoutube.com/article")
    assert not workflow.is_ytdlp_url("https://example.com/article")


def test_x_url_detection_includes_legacy_and_subdomains():
    assert workflow.is_x_url("https://www.x.com/user/status/123")
    assert workflow.is_x_url("https://mobile.twitter.com/user/status/123")
    assert workflow.is_x_url("https://t.co/short-link")
    assert not workflow.is_x_url("https://notx.com/user/status/123")


@pytest.mark.parametrize(
    ("url", "should_delete_content"),
    [
        ("https://x.com/user/status/123", False),
        ("https://twitter.com/user/status/123", False),
        ("https://www.youtube.com/watch?v=abc", True),
    ],
)
def test_ytdlp_processing_preserves_page_content_only_for_x(
    url, should_delete_content
):
    notion = Mock()
    video = workflow.VideoInfo("Title", "/tmp/video.mp4", "/tmp/thumb.jpg", "mp4")

    with patch.object(workflow, "download_file", return_value=[video]):
        workflow.process_ytdlp_item(notion, {"id": "page-id"}, url)

    if should_delete_content:
        notion.delete_page_content.assert_called_once_with("page-id")
    else:
        notion.delete_page_content.assert_not_called()
    notion.upload_file.assert_called_once_with("page-id", "/tmp/thumb.jpg")
    notion.upload_video.assert_called_once_with("page-id", "/tmp/video.mp4")


def test_fetch_page_content_extracts_main_text_and_removes_navigation():
    response = Mock()
    response.headers = {"Content-Type": "text/html; charset=utf-8"}
    response.text = """<html><head><title>Article title</title></head>
    <body><header>Header noise</header><main><p>Main article</p>
    <script>ignore this script</script></main><footer>Footer noise</footer></body></html>"""

    with patch.object(workflow.requests, "get", return_value=response):
        title, text = workflow.fetch_page_content("https://example.com/article")

    response.raise_for_status.assert_called_once()
    assert title == "Article title"
    assert text == "Main article"
    assert "Header noise" not in text
    assert "Footer noise" not in text
    assert "ignore this script" not in text


def test_download_retries_without_browser_cookies_when_macos_denies_access():
    cookie_error = subprocess.CalledProcessError(
        1,
        "yt-dlp",
        stderr=(
            "ERROR: [Errno 1] Operation not permitted: "
            "'/Users/test/Library/Cookies/Cookies.binarycookies'"
        ),
    )
    success = subprocess.CompletedProcess(
        args=["yt-dlp"], returncode=0, stdout="", stderr=""
    )

    with (
        patch.dict("os.environ", {"YTDLP_COOKIES_FROM_BROWSER": "safari"}),
        patch.object(workflow, "resolve_executable", return_value="/usr/bin/yt-dlp"),
        patch.object(
            workflow.subprocess, "run", side_effect=[cookie_error, success]
        ) as run,
    ):
        assert workflow.download_file("https://www.tiktok.com/video/123") == []

    assert run.call_count == 2
    assert "--cookies-from-browser" in run.call_args_list[0].args[0]
    assert "--cookies-from-browser" not in run.call_args_list[1].args[0]


def test_summarize_with_pi_uses_noninteractive_mode_without_tools():
    result = Mock(returncode=0, stdout="A concise summary", stderr="")
    with (
        patch.object(workflow, "resolve_executable", return_value="/usr/bin/pi"),
        patch.object(workflow.subprocess, "run", return_value=result) as run,
    ):
        summary = workflow.summarize_with_pi(
            "https://example.com", "Title", "Page text"
        )

    assert summary == "A concise summary"
    command = run.call_args.args[0]
    assert "--print" in command
    assert "--no-tools" in command
    assert "--no-session" in command
    assert run.call_args.kwargs["timeout"] == workflow.PI_TIMEOUT_SECONDS


def test_summary_handler_posts_summary_as_notion_comment():
    notion = Mock()
    item = {"id": "page-id"}

    with (
        patch.object(
            workflow, "fetch_page_content", return_value=("Title", "Article body")
        ),
        patch.object(workflow, "summarize_with_pi", return_value="Summary"),
    ):
        workflow.process_summary_item(notion, item, "https://example.com/article")

    notion.add_comment.assert_called_once_with(
        "page-id",
        "ページ要約: Title\nURL: https://example.com/article\n\nSummary",
    )
