#!/usr/bin/env python3
"""Convert Gemini-generated MP4 music into tagged audio with embedded cover art.

Requires only the FFmpeg command-line tools (ffmpeg and ffprobe); Python uses its
standard library. By default this writes M4A/AAC, applies a fixed gain based on
integrated loudness, and saves the first video frame as a JPEG cover.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_TARGET_LUFS = -14.0
DEFAULT_TRUE_PEAK_DBTP = -1.0
DEFAULT_ARTIST = "TAKE Takashi"
DEFAULT_ALBUM = "TAKE's music"
DEFAULT_ALBUM_ARTIST = "TAKE Takashi"
DEFAULT_GENRE = "Lo-Fi"


class ConversionError(RuntimeError):
    """Raised when probing, analysis, or conversion fails."""


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ConversionError(
            f"コマンドが見つかりません: {command[0]} (FFmpegをインストールし、PATHを確認してください)"
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise ConversionError(f"コマンドに失敗しました: {command[0]}\n{details}") from exc


def probe_media(input_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(input_path),
        ]
    )
    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConversionError("ffprobeの出力を読み取れませんでした") from exc

    streams = probe.get("streams", [])
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise ConversionError("入力ファイルに音声トラックがありません")

    # Prefer a real video track over an existing attached cover image.
    videos = [s for s in streams if s.get("codec_type") == "video"]
    video = next(
        (s for s in videos if not s.get("disposition", {}).get("attached_pic")),
        videos[0] if videos else None,
    )
    return probe, audio, video


def extract_cover(input_path: Path, video_index: int, cover_path: Path) -> None:
    run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-map",
            f"0:{video_index}",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(cover_path),
        ]
    )
    if not cover_path.exists() or cover_path.stat().st_size == 0:
        raise ConversionError("動画からカバー画像を抽出できませんでした")


def parse_loudness_measurement(stderr: str) -> tuple[float, float]:
    # loudnorm writes a JSON object to stderr among its normal log messages.
    objects = re.findall(r'\{\s*"input_i".*?\}', stderr, flags=re.DOTALL)
    if not objects:
        raise ConversionError("音量解析結果を読み取れませんでした (loudnorm JSONがありません)")
    try:
        data = json.loads(objects[-1])
        integrated_lufs = float(data["input_i"])
        true_peak_dbtp = float(data["input_tp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConversionError("音量解析結果に有効なLUFS/True Peak値がありません") from exc
    return integrated_lufs, true_peak_dbtp


def measure_loudness(
    input_path: Path,
    target_lufs: float,
    max_true_peak_dbtp: float,
) -> tuple[float, float]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-af",
        f"loudnorm=I={target_lufs}:TP={max_true_peak_dbtp}:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ConversionError(
            "ffmpegが見つかりません (FFmpegをインストールし、PATHを確認してください)"
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or str(exc)
        raise ConversionError(f"音量解析に失敗しました\n{details}") from exc
    return parse_loudness_measurement(result.stderr)


def calculate_gain_db(
    integrated_lufs: float,
    true_peak_dbtp: float,
    target_lufs: float,
    max_true_peak_dbtp: float,
) -> float:
    """Calculate a fixed gain, limited so the measured true peak stays below target."""
    if not math.isfinite(integrated_lufs) or not math.isfinite(true_peak_dbtp):
        # Silence (or invalid measurements) has no useful loudness to normalize.
        return 0.0
    gain_for_loudness = target_lufs - integrated_lufs
    gain_allowed_by_peak = max_true_peak_dbtp - true_peak_dbtp
    return min(gain_for_loudness, gain_allowed_by_peak)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "GeminiのMP4から音声を取り出し、実音量をノーマライズして、"
            "タグとカバー画像付きの音楽ファイルを作成します。"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", type=Path, help="入力MP4 (例: ~/Downloads/Patterns_On_The_Glass.mp4)")
    parser.add_argument(
        "--format",
        choices=("flac", "m4a"),
        default="m4a",
        help="出力形式。既定値はM4A/AAC。FLACを選ぶこともできます",
    )
    parser.add_argument("-o", "--output", type=Path, help="出力音声ファイルのパス")
    parser.add_argument("--cover-output", type=Path, help="抽出したJPEGカバー画像の保存先")
    parser.add_argument("--title", help="タイトル (既定値: 入力ファイル名の_を空白に置換)")
    parser.add_argument("--artist", default=DEFAULT_ARTIST, help="アーティスト")
    parser.add_argument("--album", default=DEFAULT_ALBUM, help="アルバム")
    parser.add_argument("--album-artist", default=DEFAULT_ALBUM_ARTIST, help="アルバムアーティスト")
    parser.add_argument("--date", default=str(date.today().year), help="年または日付")
    parser.add_argument("--genre", default=DEFAULT_GENRE, help="ジャンル")
    parser.add_argument(
        "--target-lufs",
        type=float,
        default=DEFAULT_TARGET_LUFS,
        help="目標Integrated Loudness (LUFS)。実音声に固定gainを適用",
    )
    parser.add_argument(
        "--true-peak",
        type=float,
        default=DEFAULT_TRUE_PEAK_DBTP,
        help="True Peakの上限 (dBTP)。超えない範囲でgainを適用",
    )
    parser.add_argument(
        "--bitrate",
        default="256k",
        help="M4A/AAC出力時のビットレート (例: 256k)",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="音量を変更しない。M4A出力で元音声がAACならそのままコピー",
    )
    parser.add_argument(
        "--no-cover",
        action="store_true",
        help="カバー画像を抽出・埋め込みしない",
    )
    parser.add_argument("--force", action="store_true", help="既存の出力ファイルを上書き")
    return parser


def convert(args: argparse.Namespace) -> tuple[Path, Path | None, float | None]:
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise ConversionError(f"入力ファイルがありません: {input_path}")

    output_path = (args.output or input_path.with_suffix(f".{args.format}")).expanduser().resolve()
    if output_path.suffix.lower() != f".{args.format}":
        raise ConversionError(
            f"--outputの拡張子は--format={args.format}に合わせてください: {output_path}"
        )
    if output_path == input_path:
        raise ConversionError("出力先に入力ファイル自身は指定できません")

    cover_output: Path | None = None
    if not args.no_cover:
        requested_cover_path = args.cover_output or output_path.with_suffix(".jpg")
        cover_output = Path(requested_cover_path).expanduser().resolve()
        if cover_output.suffix.lower() not in (".jpg", ".jpeg"):
            raise ConversionError("カバー画像の出力拡張子は .jpg または .jpeg にしてください")
        if cover_output in (input_path, output_path):
            raise ConversionError("カバー画像の保存先が入力/音声出力と重複しています")

    destinations = [output_path] + ([cover_output] if cover_output else [])
    existing = [str(path) for path in destinations if path.exists()]
    if existing and not args.force:
        raise ConversionError(
            "出力ファイルが既にあります (上書きする場合は --force):\n  "
            + "\n  ".join(existing)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if cover_output:
        cover_output.parent.mkdir(parents=True, exist_ok=True)

    _, audio_stream, video_stream = probe_media(input_path)
    gain_db: float | None = None
    if args.no_normalize:
        print("音量ノーマライズ: 無効")
    else:
        input_lufs, input_true_peak = measure_loudness(
            input_path,
            args.target_lufs,
            args.true_peak,
        )
        gain_db = calculate_gain_db(
            input_lufs,
            input_true_peak,
            args.target_lufs,
            args.true_peak,
        )
        print(
            f"音量解析: {input_lufs:.2f} LUFS, {input_true_peak:.2f} dBTP "
            f"→ 固定gain {gain_db:+.2f} dB"
        )

    temp_dir = tempfile.TemporaryDirectory(prefix="gemini-music-")
    temp_root = Path(temp_dir.name)
    temp_audio = output_path.with_name(
        f".{output_path.stem}.{os.getpid()}.tmp{output_path.suffix}"
    )
    try:
        temp_cover = temp_root / "cover.jpg"

        if cover_output:
            if video_stream is None:
                raise ConversionError("動画トラックがありません。--no-coverで画像抽出を省略できます")
            extract_cover(input_path, int(video_stream["index"]), temp_cover)

        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
        ]
        if cover_output:
            command.extend(["-i", str(temp_cover)])
        command.extend(["-map", "0:a:0", "-map_metadata", "0", "-map_chapters", "-1"])
        if cover_output:
            command.extend(["-map", "1:v:0"])

        if args.format == "flac":
            command.extend(["-c:a", "flac"])
        elif args.no_normalize and audio_stream.get("codec_name") == "aac":
            # Preserve the original AAC bitstream exactly when no gain is requested.
            command.extend(["-c:a", "copy"])
        else:
            command.extend(["-c:a", "aac", "-b:a", args.bitrate])

        if gain_db is not None:
            command.extend(["-af", f"volume={gain_db:.6f}dB"])
        if cover_output:
            command.extend(
                [
                    "-c:v",
                    "copy",
                    "-disposition:v:0",
                    "attached_pic",
                    "-metadata:s:v:0",
                    "title=Cover",
                    "-metadata:s:v:0",
                    "comment=Cover (front)",
                ]
            )

        metadata = {
            "title": args.title or input_path.stem.replace("_", " "),
            "artist": args.artist,
            "album": args.album,
            "album_artist": args.album_artist,
            "date": args.date,
            "genre": args.genre,
        }
        for key, value in metadata.items():
            if value:
                command.extend(["-metadata", f"{key}={value}"])
        if args.format == "m4a":
            command.extend(["-movflags", "+faststart"])
        command.extend(["-y", str(temp_audio)])

        run_command(command)
        if not temp_audio.exists() or temp_audio.stat().st_size == 0:
            raise ConversionError("FFmpegは成功しましたが、出力ファイルが作成されませんでした")
        os.replace(temp_audio, output_path)

        if cover_output:
            temp_cover_output = cover_output.with_name(
                f".{cover_output.stem}.{os.getpid()}.tmp{cover_output.suffix}"
            )
            try:
                shutil.copyfile(temp_cover, temp_cover_output)
                os.replace(temp_cover_output, cover_output)
            finally:
                if temp_cover_output.exists():
                    temp_cover_output.unlink()
    finally:
        if temp_audio.exists():
            temp_audio.unlink()
        temp_dir.cleanup()

    return output_path, cover_output, gain_db


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output_path, cover_path, gain_db = convert(args)
    except (ConversionError, OSError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    print(f"音声: {output_path}")
    if cover_path:
        print(f"カバー: {cover_path}")
    if gain_db is not None:
        print("※ ReplayGainタグではなく、音声データ自体に固定gainを適用しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
