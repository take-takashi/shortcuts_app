import json
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import av
import pytest
from PIL import Image

import download_audio_from_html as workflow
from AudioInfoExtractor import AudioInfo
from MyFfmpegHelper.my_ffmpeg_helper import MyFfmpegHelper


@pytest.fixture
def aac_file(tmp_path):
    # PyAVだけで短いAAC音声を生成し、実行環境のFFmpeg CLIに依存しない。
    path = tmp_path / "source.m4a"
    with av.open(str(path), "w") as output:
        stream = output.add_stream("aac", rate=48000)
        stream.layout = "stereo"
        for i in range(48):
            frame = av.AudioFrame(format="fltp", layout="stereo", samples=1024)
            frame.sample_rate = 48000
            frame.pts = i * 1024
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    return path


def audio_packets(path):
    with av.open(str(path)) as source:
        return [bytes(p) for p in source.demux(source.streams.audio[0]) if p.size]


def test_pyav_copies_aac_bit_for_bit_with_tags_and_cover(aac_file, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    cover = tmp_path / "cover.png"
    Image.new("RGB", (32, 32), "red").save(cover)
    destination = tmp_path / "output.m4a"
    MyFfmpegHelper.save_aac_as_m4a(
        str(aac_file), str(destination),
        {"title": "あじがとレディオ#232", "artist": "aiko", "album": "あじがとレディオ", "date": "2026-10-08"},
        cover_path=str(cover), expected_duration=1.024,
    )
    assert audio_packets(aac_file) == audio_packets(destination)
    with av.open(str(destination)) as result:
        assert result.streams.audio[0].codec_context.name == "aac"
        assert result.metadata["title"] == "あじがとレディオ#232"
        assert result.metadata["artist"] == "aiko"
        assert result.metadata["album"] == "あじがとレディオ"
        assert result.metadata["date"] == "2026-10-08"
        assert result.streams.video[0].disposition & av.stream.Disposition.attached_pic
        assert len(list(result.decode(audio=0))) > 0
    assert not list(tmp_path.glob(".output.*"))


def test_pyav_downloads_fragmented_hls_with_referer_without_cli(aac_file, tmp_path, monkeypatch):
    playlist = tmp_path / "audio.m3u8"
    with av.open(str(aac_file)) as source:
        with av.open(str(playlist), "w", format="hls", options={
            "hls_time": "0.25", "hls_segment_type": "fmp4", "hls_playlist_type": "vod",
        }) as output:
            stream = output.add_stream_from_template(source.streams.audio[0])
            for packet in source.demux(source.streams.audio[0]):
                if packet.dts is not None and packet.size:
                    packet.stream = stream
                    output.mux(packet)

    received = []

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, self.headers.get("Referer")))
            super().do_GET()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    destination = tmp_path / "download.m4a"
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("CLI must not run")))
    try:
        MyFfmpegHelper.save_aac_as_m4a(
            f"http://127.0.0.1:{server.server_port}/audio.m3u8", str(destination), {},
            referer="https://sp.aiko.pcan.us/", expected_duration=1.024,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert received
    assert all(referer == "https://sp.aiko.pcan.us/" for _, referer in received)
    assert any(path.endswith(".m4s") for path, _ in received)
    assert audio_packets(playlist) == audio_packets(destination)


def test_pyav_does_not_overwrite_existing_file(aac_file, tmp_path):
    destination = tmp_path / "existing.m4a"
    destination.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        MyFfmpegHelper.save_aac_as_m4a(str(aac_file), str(destination), {})
    assert destination.read_bytes() == b"existing"
    MyFfmpegHelper.save_aac_as_m4a(str(aac_file), str(destination), {}, overwrite=True)
    assert audio_packets(aac_file) == audio_packets(destination)


def test_pyav_rejects_truncated_audio_and_cleans_temporary_file(aac_file, tmp_path):
    destination = tmp_path / "truncated.m4a"
    with pytest.raises(ValueError, match="長さ"):
        MyFfmpegHelper.save_aac_as_m4a(
            str(aac_file), str(destination), {}, expected_duration=100,
        )
    assert not destination.exists()
    assert not list(tmp_path.glob(".truncated.*"))


def test_pyav_rejects_non_aac_without_reencoding(tmp_path):
    source = tmp_path / "source.wav"
    import wave
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(bytes(48000 * 2))
    destination = tmp_path / "output.m4a"
    with pytest.raises(ValueError, match="AAC"):
        MyFfmpegHelper.save_aac_as_m4a(str(source), str(destination), {})
    assert not destination.exists()
    assert not list(tmp_path.glob(".output.*"))


def test_vimeo_workflow_uses_pyav_not_direct_download(tmp_path, monkeypatch):
    html = tmp_path / "page.html"
    html.write_text('<title>あじがとレディオ#232 | Team aiko</title>'
                    '<iframe src="https://player.vimeo.com/video/123?h=hash"></iframe>')
    resolved = Mock(url="https://cdn.example/audio.m3u8", referer="https://sp.aiko.pcan.us/", duration=42)
    resolver = Mock(return_value=resolved)
    save = Mock()
    monkeypatch.setattr(workflow, "resolve_vimeo_audio", resolver)
    monkeypatch.setattr(workflow, "resolve_team_aiko_publish_date", Mock(return_value="20261008"))
    monkeypatch.setattr(MyFfmpegHelper, "save_aac_as_m4a", save)
    direct_get = Mock(side_effect=AssertionError("direct MP3 downloader must not run"))
    monkeypatch.setattr(workflow.requests, "get", direct_get)
    assert workflow.download_audio_from_html(
        str(html), "sp.aiko.pcan.us", str(tmp_path), logger=Mock(),
    )
    save.assert_called_once()
    assert Path(save.call_args.kwargs["output_path"]).name == "あじがとレディオ_20261008_あじがとレディオ#232.m4a"
    assert save.call_args.kwargs["expected_duration"] == 42
    assert save.call_args.kwargs["metadata"] == {
        "title": "2026-10-08 あじがとレディオ#232", "artist": "aiko",
        "album": "あじがとレディオ", "date": "2026-10-08",
    }
    direct_get.assert_not_called()


def test_manual_broadcast_date_skips_listing_fetch(tmp_path, monkeypatch):
    html = '<title>あじがとレディオ#232 | Team aiko</title><iframe src="https://player.vimeo.com/video/123?h=hash"></iframe>'
    fetch_date = Mock(side_effect=AssertionError("manual date should avoid fetching listing"))
    monkeypatch.setattr(workflow, "resolve_team_aiko_publish_date", fetch_date)
    save = Mock()
    monkeypatch.setattr(workflow, "_download_vimeo_audio", save)
    assert workflow.download_audio_content(
        html, "sp.aiko.pcan.us", str(tmp_path), logger=Mock(), broadcast_date="20261008",
    )
    assert save.call_args.args[0].broadcast_date == "20261008"
    fetch_date.assert_not_called()


def test_date_lookup_failure_does_not_download_or_guess_date(tmp_path, monkeypatch):
    from AudioInfoExtractor.team_aiko import TeamAikoDateError
    html = '<title>あじがとレディオ#232 | Team aiko</title><iframe src="https://player.vimeo.com/video/123?h=hash"></iframe>'
    monkeypatch.setattr(workflow, "resolve_team_aiko_publish_date", Mock(side_effect=TeamAikoDateError("公開日がありません")))
    save = Mock()
    monkeypatch.setattr(workflow, "_download_vimeo_audio", save)
    assert not workflow.download_audio_content(html, "sp.aiko.pcan.us", str(tmp_path), logger=Mock())
    save.assert_not_called()


def test_cli_accepts_manual_broadcast_date(tmp_path, monkeypatch):
    html = tmp_path / "page.html"
    html.write_text("<html></html>")
    download = Mock(return_value=True)
    monkeypatch.setattr(workflow, "download_audio_from_html", download)
    assert workflow.main([
        "--html", str(html), "--domain", "sp.aiko.pcan.us", "--download_dir", str(tmp_path),
        "--broadcast-date", "2026-10-08",
    ]) == 0
    assert download.call_args.kwargs["broadcast_date"] == "20261008"


def test_existing_direct_mp3_workflow_is_preserved(tmp_path, monkeypatch):
    html = tmp_path / "page.html"
    html.write_text("<html></html>")
    info = AudioInfo("番組", "回", "出演者", "", "https://example.com/file.mp3", "20261019")
    monkeypatch.setattr(workflow, "get_extractor", Mock(return_value=Mock(get_audio_info=Mock(return_value=[info]))))
    response = Mock()
    response.iter_content.return_value = [b"audio"]
    monkeypatch.setattr(workflow.requests, "get", Mock(return_value=response))
    embed = Mock()
    monkeypatch.setattr(MyFfmpegHelper, "embed_metadata", embed)
    assert workflow.download_audio_from_html(str(html), "audee.jp", str(tmp_path), logger=Mock())
    assert Path(embed.call_args.kwargs["output_path"]).name == "番組_20261019_回.mp3"
    assert not (tmp_path / "temp_audio.mp3").exists()


def test_read_safari_page_returns_url_and_html(monkeypatch):
    payload = {"url": "https://sp.aiko.pcan.us/contents/example", "html": "<html>logged in</html>"}
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr=""))
    monkeypatch.setattr(workflow.subprocess, "run", run)
    assert workflow.read_safari_page() == payload
    assert run.call_args.args[0][0] == "osascript"
    assert "document.documentElement.outerHTML" in run.call_args.args[0][-1]
    assert run.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("result", [
    subprocess.CalledProcessError(1, ["osascript"]),
    subprocess.TimeoutExpired(["osascript"], 30),
    subprocess.CompletedProcess([], 0, stdout="not JSON", stderr=""),
    subprocess.CompletedProcess([], 0, stdout='{"url":"file:///tmp/private","html":"x"}', stderr=""),
])
def test_safari_access_errors_are_actionable(monkeypatch, result):
    run = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
    monkeypatch.setattr(workflow.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Apple Events"):
        workflow.read_safari_page()


def test_cli_failure_returns_nonzero(tmp_path):
    html = tmp_path / "page.html"
    html.write_text("<html>Not logged in</html>")
    assert workflow.main(["--html", str(html), "--domain", "sp.aiko.pcan.us", "--download_dir", str(tmp_path)]) == 1


def test_safari_cli_detects_domain_and_does_not_save_html(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "read_safari_page", Mock(return_value={
        "url": "https://sp.aiko.pcan.us/contents/example", "html": "<html>private</html>",
    }))
    download = Mock(return_value=True)
    monkeypatch.setattr(workflow, "download_audio_content", download)
    assert workflow.main(["--safari", "--download_dir", str(tmp_path)]) == 0
    assert download.call_args.args[:2] == ("<html>private</html>", "sp.aiko.pcan.us")
    assert download.call_args.kwargs["page_url"] == "https://sp.aiko.pcan.us/contents/example"
    assert not list(tmp_path.glob("*.html"))
