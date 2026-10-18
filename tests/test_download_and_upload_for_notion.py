import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import av
import pytest
from av.stream import Disposition
from PIL import Image

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


def test_tokiomotion_nested_url_is_unwrapped():
    malformed_url = (
        "https://www.tokyomotion.net/video/7047105/"
        "https%3A%2F%2Fwww.tokyomotion.net%2Fvideo%2F7047105%2F"
        "%25E7%258E%2589%25E5%259F%258E"
    )

    assert workflow.normalize_tokiomotion_url(malformed_url) == (
        "https://www.tokyomotion.net/video/7047105/%E7%8E%89%E5%9F%8E"
    )


def test_tokiomotion_normalization_leaves_other_urls_unchanged():
    url = "https://www.tokyomotion.net/video/7047105/%E7%8E%89%E5%9F%8E"

    assert workflow.normalize_tokiomotion_url(url) == url
    assert workflow.normalize_tokiomotion_url("https://example.com/article") == (
        "https://example.com/article"
    )


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


def test_parse_ytdlp_output_handles_json_escaped_values():
    title = 'A title with "quotes" and\na newline'
    video_path = '/tmp/video "quoted".mp4'
    output = "\n".join(
        [
            json.dumps(
                {"event": "meta", "id": "video-id", "title": title},
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "event": "done",
                    "video_path": video_path,
                    "video_name": 'video "quoted".mp4',
                    "ext": "mp4",
                },
                ensure_ascii=False,
            ),
        ]
    )
    result = subprocess.CompletedProcess(
        args=["yt-dlp"], returncode=0, stdout=output, stderr=""
    )

    assert workflow.parse_ytdlp_output(result) == (title, [Path(video_path)])


def test_ytdlp_command_does_not_request_ffmpeg():
    command = workflow.build_ytdlp_command(
        "/usr/bin/yt-dlp",
        "bv[ext=mp4]/bv",
        Path("/tmp/download"),
        "__video",
        "https://www.tiktok.com/video/123",
        write_thumbnail=True,
    )

    assert "--ffmpeg-location" not in command
    assert "--embed-thumbnail" not in command
    assert "--convert-thumbnails" not in command
    assert "--write-thumbnail" in command


def test_mux_media_embeds_thumbnail_without_external_ffmpeg(tmp_path):
    thumbnail_path = tmp_path / "thumbnail.jpg"
    output_path = tmp_path / "output.mp4"
    Image.new("RGB", (320, 240), "red").save(thumbnail_path)

    workflow.mux_media_with_thumbnail(
        workflow.SCRIPT_DIR / "tests/cbr_test.mp4",
        workflow.SCRIPT_DIR / "tests/sample.mp3",
        thumbnail_path,
        output_path,
        "Title",
    )

    with av.open(str(output_path)) as container:
        assert any(
            stream.disposition & Disposition.attached_pic
            for stream in container.streams
        )
        assert any(stream.type == "audio" for stream in container.streams)
        assert any(
            stream.type == "video"
            and not stream.disposition & Disposition.attached_pic
            for stream in container.streams
        )


@pytest.mark.parametrize("progressive", [False, True])
def test_download_handles_tiktok_image_thumbnail(tmp_path, progressive):
    """映像・音声別取得でも、一体型へのフォールバックでも.imageを扱う。"""
    def fake_run_ytdlp(command, cookie_browser):
        del cookie_browser
        selector = command[command.index("-f") + 1]
        if progressive and selector == "bv[ext=mp4]/bv":
            raise subprocess.CalledProcessError(
                1, command, stderr="Requested format is not available"
            )

        download_dir = Path(command[command.index("--paths") + 1])
        if selector == "ba[ext=m4a]/ba":
            media = download_dir / "Title.__audio.mp3"
            shutil.copyfile(workflow.SCRIPT_DIR / "tests/sample.mp3", media)
        else:
            marker = "__combined" if progressive else "__video"
            media = download_dir / f"Title.{marker}.mp4"
            shutil.copyfile(workflow.SCRIPT_DIR / "tests/cbr_test.mp4", media)
            # 再現したTikTokの実ファイルと同様に、拡張子.imageでJPEGを保存する。
            Image.new("RGB", (32, 48), "red").save(
                media.with_suffix(".image"), format="JPEG"
            )
        return subprocess.CompletedProcess(
            command, 0,
            stdout="\n".join([
                json.dumps({"event": "meta", "title": "TikTok title"}),
                json.dumps({"event": "done", "video_path": str(media)}),
            ]),
            stderr="",
        )

    with (
        patch.object(workflow, "resolve_executable", return_value="yt-dlp"),
        patch.object(workflow, "run_ytdlp", side_effect=fake_run_ytdlp) as run,
        patch.object(
            workflow.subprocess, "run", side_effect=AssertionError("外部コマンドは禁止")
        ),
    ):
        videos = workflow.download_file("https://vt.tiktok.com/test/", str(tmp_path))

    assert run.call_count == 2
    assert len(videos) == 1
    assert videos[0].video_title == "TikTok title"
    thumbnail = Path(videos[0].thumbnail_filepath)
    assert thumbnail.suffix == ".jpg"
    with Image.open(thumbnail) as image:
        assert image.format == "JPEG"
        assert image.size == (32, 48)
    with av.open(videos[0].video_filepath) as container:
        cover = next(
            stream for stream in container.streams.video
            if stream.disposition & Disposition.attached_pic
        )
        assert sum(1 for _ in container.decode(cover)) == 1
    assert not list(tmp_path.glob(".shortcuts-ytdlp-*"))


def test_select_downloaded_media_excludes_image_thumbnail(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    thumbnail = tmp_path / "video.image"
    Image.new("RGB", (16, 16)).save(thumbnail, format="JPEG")

    assert workflow.find_thumbnail(tmp_path) == thumbnail
    assert workflow.select_downloaded_media([video, thumbnail], "動画") == video


def test_move_thumbnail_normalizes_non_jpeg_images(tmp_path):
    source = tmp_path / "thumbnail.png"
    Image.new("RGBA", (3, 5), (255, 0, 0, 128)).save(source)

    destination = workflow.move_thumbnail(source, tmp_path, "video")

    assert destination == tmp_path / "video.jpg"
    assert destination.is_file()
    assert not source.exists()
    with Image.open(destination) as image:
        assert image.format == "JPEG"
        assert image.size == (3, 5)


def test_run_ytdlp_retries_without_browser_cookies_when_macos_denies_access():
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
    command = ["/usr/bin/yt-dlp", "-f", "best", "https://example.com/video"]

    with patch.object(
        workflow.subprocess, "run", side_effect=[cookie_error, success]
    ) as run:
        assert workflow.run_ytdlp(command, "safari") is success

    assert run.call_count == 2
    assert "--cookies-from-browser" in run.call_args_list[0].args[0]
    assert "--cookies-from-browser" not in run.call_args_list[1].args[0]


def test_summarize_with_pi_invokes_yomiyasu_without_tools():
    result = Mock(returncode=0, stdout="A concise summary", stderr="")
    with (
        patch.object(workflow.Path, "is_file", return_value=True),
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
    assert "--no-skills" in command
    assert command[command.index("--skill") + 1] == str(workflow.YOMIYASU_SKILL_DIR)
    assert command[-1].startswith("/skill:yomiyasu\n")
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
