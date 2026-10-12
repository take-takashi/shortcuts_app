import json
import math
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gemini_music_to_audio import (
    ConversionError,
    build_parser,
    calculate_gain_db,
    convert,
    parse_loudness_measurement,
)


def test_default_format_and_tags():
    args = build_parser().parse_args(["track.mp4"])
    assert args.format == "m4a"
    assert args.artist == "TAKE Takashi"
    assert args.album == "TAKE's music"
    assert args.album_artist == "TAKE Takashi"
    assert args.date == str(date.today().year)
    assert args.genre == "Lo-Fi"


def test_calculate_gain_db_normalizes_but_respects_true_peak_limit():
    # LUFS requests +8 dB, but only +3 dB headroom remains before the peak ceiling.
    assert calculate_gain_db(-22.0, -4.0, -14.0, -1.0) == pytest.approx(3.0)


def test_calculate_gain_db_can_attenuate():
    assert calculate_gain_db(-10.0, -5.0, -14.0, -1.0) == pytest.approx(-4.0)


def test_calculate_gain_db_silence_is_left_unchanged():
    assert calculate_gain_db(-math.inf, -math.inf, -14.0, -1.0) == 0.0


def test_parse_loudness_measurement_reads_ffmpeg_json_from_stderr():
    stderr = '''
[Parsed_loudnorm_0 @ 0x123] {
    "input_i" : "-18.23",
    "input_tp" : "-2.50",
    "input_lra" : "4.20",
    "input_thresh" : "-28.00",
    "output_i" : "-14.00",
    "output_tp" : "-1.00",
    "output_lra" : "4.20",
    "output_thresh" : "-23.77",
    "normalization_type" : "linear",
    "target_offset" : "0.00"
}
'''
    assert parse_loudness_measurement(stderr) == pytest.approx((-18.23, -2.5))


def test_parse_loudness_measurement_rejects_missing_json():
    with pytest.raises(ConversionError):
        parse_loudness_measurement("ffmpeg produced no loudnorm output")


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required for the integration test",
)
def test_convert_mp4_to_flac_with_metadata_and_attached_cover(tmp_path: Path):
    source = tmp_path / "Gemini track.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x64:r=5:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-y",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    args = build_parser().parse_args(
        [str(source), "--format", "flac", "--title", "Glass", "--artist", "Gemini"]
    )
    audio_path, cover_path, gain_db = convert(args)

    assert audio_path.suffix == ".flac"
    assert cover_path is not None and cover_path.is_file()
    assert gain_db is not None

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    media = json.loads(result.stdout)
    assert any(stream.get("codec_name") == "flac" for stream in media["streams"])
    assert any(
        stream.get("disposition", {}).get("attached_pic") == 1
        for stream in media["streams"]
    )
    assert media["format"]["tags"]["title"] == "Glass"
    assert media["format"]["tags"]["artist"] == "Gemini"
