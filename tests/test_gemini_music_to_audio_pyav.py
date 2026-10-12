import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import av
from av.stream import Disposition
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gemini_music_to_audio_pyav import build_parser, convert


def test_default_format_and_tags():
    args = build_parser().parse_args(["track.mp4"])
    assert args.format == "m4a"
    assert args.artist == "TAKE Takashi"
    assert args.album == "TAKE's music"
    assert args.album_artist == "TAKE Takashi"
    assert args.date == str(date.today().year)
    assert args.genre == "Lo-Fi"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is used only to create the test fixture")
def test_pyav_conversion_runs_without_ffmpeg_cli_and_embeds_cover(tmp_path: Path, monkeypatch):
    source = tmp_path / "Gemini_track.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x64:r=5:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-y",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    # The converter must not shell out to ffmpeg or ffprobe.
    monkeypatch.setenv("PATH", "")

    flac_args = build_parser().parse_args([str(source), "--format", "flac"])
    flac_path, cover_path, gain_db = convert(flac_args)

    assert gain_db is not None
    assert cover_path is not None and cover_path.is_file()
    with av.open(str(flac_path)) as result:
        assert result.streams.audio[0].codec_context.name == "flac"
        assert result.metadata["title"] == "Gemini track"
        assert result.metadata["artist"] == "TAKE Takashi"
        assert result.metadata["album"] == "TAKE's music"
        assert result.metadata["album_artist"] == "TAKE Takashi"
        assert result.metadata["date"] == str(date.today().year)
        assert result.metadata["genre"] == "Lo-Fi"
        assert any(
            stream.disposition & Disposition.attached_pic
            for stream in result.streams.video
        )

    def audio_packets(path: Path) -> list[bytes]:
        with av.open(str(path)) as container:
            stream = container.streams.audio[0]
            return [
                bytes(packet)
                for packet in container.demux(stream)
                if packet.size > 0
            ]

    m4a_path = tmp_path / "original-aac.m4a"
    m4a_args = build_parser().parse_args(
        [str(source), "--format", "m4a", "--no-normalize", "-o", str(m4a_path)]
    )
    convert(m4a_args)

    with av.open(str(m4a_path)) as result:
        assert result.streams.audio[0].codec_context.name == "aac"
        assert result.metadata["artist"] == "TAKE Takashi"
        assert result.metadata["album"] == "TAKE's music"
        assert result.metadata["album_artist"] == "TAKE Takashi"
        assert result.metadata["date"] == str(date.today().year)
        assert result.metadata["genre"] == "Lo-Fi"
        assert any(
            stream.disposition & Disposition.attached_pic
            for stream in result.streams.video
        )
    assert audio_packets(source) == audio_packets(m4a_path)

    normalized_m4a = tmp_path / "normalized.m4a"
    normalized_args = build_parser().parse_args(
        [str(source), "--format", "m4a", "--artist", "Gemini", "-o", str(normalized_m4a)]
    )
    assert convert(normalized_args)[2] is not None
    with av.open(str(normalized_m4a)) as result:
        assert result.streams.audio[0].codec_context.name == "aac"
        assert result.metadata["artist"] == "Gemini"
