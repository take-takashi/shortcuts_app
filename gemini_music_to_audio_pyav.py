#!/usr/bin/env python3
"""PyAV-based version of gemini_music_to_audio.py.

This uses PyAV's bundled FFmpeg libraries directly; it does not launch the
ffmpeg or ffprobe command-line programs.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, cast

import av
from av.audio.frame import AudioFrame
from av.container.input import InputContainer
from av.container.output import OutputContainer
from av.error import BlockingIOError as AvBlockingIOError
from av.error import EOFError as AvEOFError
from av.filter.graph import Graph
from av.stream import Disposition
from av.video.stream import VideoStream
from PIL import Image

DEFAULT_TARGET_LUFS = -14.0
DEFAULT_TRUE_PEAK_DBTP = -1.0
DEFAULT_ARTIST = "TAKE Takashi"
DEFAULT_ALBUM = "TAKE's music"
DEFAULT_ALBUM_ARTIST = "TAKE Takashi"
DEFAULT_GENRE = "Lo-Fi"


class ConversionError(RuntimeError):
    """Raised when media cannot be analyzed or converted."""


def _drain_graph(graph: Graph) -> list[AudioFrame]:
    frames: list[av.AudioFrame] = []
    while True:
        try:
            frames.append(cast(AudioFrame, graph.pull()))
        except (AvBlockingIOError, AvEOFError):
            return frames


def _make_graph(audio_stream: Any, filter_name: str, options: str) -> Graph:
    graph = Graph()
    source = graph.add_abuffer(template=audio_stream)
    filter_context = graph.add(filter_name, options)
    sink = graph.add("abuffersink")
    source.link_to(filter_context)
    filter_context.link_to(sink)
    graph.configure()
    return graph


def measure_loudness(input_path: Path) -> tuple[float, float]:
    """Measure integrated LUFS and true peak using FFmpeg's ebur128 filter."""
    last_measurement: dict[str, str] | None = None
    try:
        with av.open(str(input_path)) as container:
            if not container.streams.audio:
                raise ConversionError("入力ファイルに音声トラックがありません")
            graph = _make_graph(container.streams.audio[0], "ebur128", "metadata=1:peak=true")
            for frame in container.decode(audio=0):
                graph.push(frame)
                for filtered in _drain_graph(graph):
                    if "lavfi.r128.I" in filtered.metadata:
                        last_measurement = filtered.metadata
            graph.push(None)
            for filtered in _drain_graph(graph):
                if "lavfi.r128.I" in filtered.metadata:
                    last_measurement = filtered.metadata
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"PyAVで音量を解析できませんでした: {exc}") from exc

    if not last_measurement:
        raise ConversionError("音量解析結果を取得できませんでした")
    try:
        integrated_lufs = float(last_measurement["lavfi.r128.I"])
        true_peak_linear = float(last_measurement["lavfi.r128.true_peak"])
        true_peak_dbtp = (
            20.0 * math.log10(true_peak_linear) if true_peak_linear > 0 else -math.inf
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConversionError("LUFS/True Peakの解析結果を読み取れませんでした") from exc
    return integrated_lufs, true_peak_dbtp


def calculate_gain_db(
    integrated_lufs: float,
    true_peak_dbtp: float,
    target_lufs: float,
    max_true_peak_dbtp: float,
) -> float:
    if not math.isfinite(integrated_lufs) or not math.isfinite(true_peak_dbtp):
        return 0.0
    return min(
        target_lufs - integrated_lufs,
        max_true_peak_dbtp - true_peak_dbtp,
    )


def extract_cover(input_path: Path, cover_path: Path) -> Image.Image:
    try:
        with av.open(str(input_path)) as container:
            if not container.streams.video:
                raise ConversionError("入力ファイルに動画トラックがありません")
            frame = next(container.decode(video=0), None)
            if frame is None:
                raise ConversionError("動画からカバー画像を抽出できませんでした")
            image = frame.to_image().convert("RGB")
            image.save(cover_path, format="JPEG", quality=95)
            return image
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"PyAVでカバー画像を抽出できませんでした: {exc}") from exc


def parse_bitrate(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmM]?)\s*", value)
    if not match:
        raise argparse.ArgumentTypeError("例: 256k または 320k")
    amount = float(match.group(1))
    suffix = match.group(2).lower()
    multiplier = 1_000 if suffix == "k" else 1_000_000 if suffix == "m" else 1
    return int(amount * multiplier)


def _add_cover_stream(output: OutputContainer, image: Image.Image) -> VideoStream:
    stream = output.add_stream("mjpeg")
    stream.width = image.width
    stream.height = image.height
    stream.pix_fmt = "yuvj420p"
    stream.disposition = Disposition.attached_pic
    return stream


def _write_cover(
    output: OutputContainer,
    stream: VideoStream,
    image: Image.Image,
) -> None:
    frame = av.VideoFrame.from_image(image).reformat(format="yuvj420p")
    frame.pts = 0
    for packet in stream.encode(frame):
        output.mux(packet)
    for packet in stream.encode(None):
        output.mux(packet)


def _write_audio(
    input_container: InputContainer,
    input_stream: Any,
    output: OutputContainer,
    output_stream: Any,
    codec_name: str,
    gain_db: float | None,
) -> None:
    try:
        if codec_name == "copy":
            for packet in input_container.demux(input_stream):
                if packet.dts is None or packet.size == 0:
                    continue
                packet.stream = output_stream
                output.mux(packet)
            return

        output_format = "s32" if codec_name == "flac" else "fltp"
        layout = input_stream.codec_context.layout.name
        sample_rate = input_stream.codec_context.sample_rate or input_stream.rate
        # Apply gain to decoded samples, then convert to the encoder's format.
        format_graph = Graph()
        source = format_graph.add_abuffer(template=input_stream)
        volume = format_graph.add("volume", f"{gain_db:.6f}dB" if gain_db is not None else "1")
        audio_format = format_graph.add(
            "aformat",
            f"sample_fmts={output_format}:sample_rates={sample_rate}:channel_layouts={layout}",
        )
        sink = format_graph.add("abuffersink")
        source.link_to(volume)
        volume.link_to(audio_format)
        audio_format.link_to(sink)
        format_graph.configure()

        for frame in input_container.decode(audio=0):
            format_graph.push(frame)
            for filtered in _drain_graph(format_graph):
                for packet in output_stream.encode(filtered):
                    output.mux(packet)
        format_graph.push(None)
        for filtered in _drain_graph(format_graph):
            for packet in output_stream.encode(filtered):
                output.mux(packet)
        for packet in output_stream.encode(None):
            output.mux(packet)
    except Exception as exc:
        raise ConversionError(f"PyAVで音声を書き出せませんでした: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PyAVを使ってGeminiのMP4から音楽ファイルを作成します (ffmpeg CLI不要)。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", type=Path, help="入力MP4")
    parser.add_argument("--format", choices=("flac", "m4a"), default="m4a")
    parser.add_argument("-o", "--output", type=Path, help="出力音声ファイル")
    parser.add_argument("--cover-output", type=Path, help="JPEGカバー画像の保存先")
    parser.add_argument("--title", help="タイトル (既定値: 入力ファイル名の_を空白に置換)")
    parser.add_argument("--artist", default=DEFAULT_ARTIST, help="アーティスト")
    parser.add_argument("--album", default=DEFAULT_ALBUM, help="アルバム")
    parser.add_argument("--album-artist", default=DEFAULT_ALBUM_ARTIST, help="アルバムアーティスト")
    parser.add_argument("--date", default=str(date.today().year), help="年または日付")
    parser.add_argument("--genre", default=DEFAULT_GENRE, help="ジャンル")
    parser.add_argument("--target-lufs", type=float, default=DEFAULT_TARGET_LUFS)
    parser.add_argument("--true-peak", type=float, default=DEFAULT_TRUE_PEAK_DBTP)
    parser.add_argument("--bitrate", type=parse_bitrate, default=256_000, help="M4A/AAC bitrate")
    parser.add_argument("--no-normalize", action="store_true", help="gainを適用しない")
    parser.add_argument("--no-cover", action="store_true", help="カバー画像を抽出・埋め込みしない")
    parser.add_argument("--force", action="store_true", help="既存ファイルを上書き")
    return parser


def convert(args: argparse.Namespace) -> tuple[Path, Path | None, float | None]:
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise ConversionError(f"入力ファイルがありません: {input_path}")

    output_path = (args.output or input_path.with_suffix(f".{args.format}")).expanduser().resolve()
    if output_path.suffix.lower() != f".{args.format}":
        raise ConversionError(f"出力拡張子は .{args.format} にしてください")
    if output_path == input_path:
        raise ConversionError("出力先に入力ファイル自身は指定できません")

    cover_output: Path | None = None
    if not args.no_cover:
        requested_cover = args.cover_output or output_path.with_suffix(".jpg")
        cover_output = Path(requested_cover).expanduser().resolve()
        if cover_output.suffix.lower() not in (".jpg", ".jpeg"):
            raise ConversionError("カバー画像の拡張子は .jpg または .jpeg にしてください")
        if cover_output in (input_path, output_path):
            raise ConversionError("カバー画像の保存先が入力/音声出力と重複しています")

    destinations = [output_path] + ([cover_output] if cover_output else [])
    existing = [str(path) for path in destinations if path.exists()]
    if existing and not args.force:
        raise ConversionError(
            "出力ファイルが既にあります (上書きには --force):\n  " + "\n  ".join(existing)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if cover_output:
        cover_output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with av.open(str(input_path)) as source:
            if not source.streams.audio:
                raise ConversionError("入力ファイルに音声トラックがありません")
            has_video = bool(source.streams.video)
            source_metadata = dict(source.metadata)
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"PyAVで入力を開けませんでした: {exc}") from exc

    gain_db: float | None = None
    if not args.no_normalize:
        input_lufs, input_true_peak = measure_loudness(input_path)
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
    else:
        print("音量ノーマライズ: 無効")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_audio_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}.",
        suffix=f".tmp.{args.format}",
        dir=output_path.parent,
    )
    os.close(fd)
    temp_audio = Path(temp_audio_name)
    temp_dir = tempfile.TemporaryDirectory(prefix="gemini-music-pyav-")
    temp_cover = Path(temp_dir.name) / "cover.jpg"

    try:
        cover_image: Image.Image | None = None
        if cover_output:
            if not has_video:
                raise ConversionError("動画トラックがありません。--no-coverで抽出を省略できます")
            cover_image = extract_cover(input_path, temp_cover)

        tags = source_metadata
        tags.update(
            {
                "title": args.title or input_path.stem.replace("_", " "),
                "artist": args.artist,
                "album": args.album,
                "album_artist": args.album_artist,
                "date": args.date,
                "genre": args.genre,
            }
        )
        tags = {key: value for key, value in tags.items() if value}

        output_format = "flac" if args.format == "flac" else "mp4"
        with av.open(str(input_path)) as audio_input:
            live_audio_stream = audio_input.streams.audio[0]
            with av.open(str(temp_audio), mode="w", format=output_format) as output:
                output.metadata.update(tags)
                copy_aac = (
                    args.no_normalize
                    and args.format == "m4a"
                    and live_audio_stream.codec_context.name == "aac"
                )
                if copy_aac:
                    audio_output = output.add_stream_from_template(live_audio_stream)
                    codec_name = "copy"
                else:
                    codec_name = "flac" if args.format == "flac" else "aac"
                    sample_rate = (
                        live_audio_stream.codec_context.sample_rate
                        or live_audio_stream.rate
                    )
                    audio_output = output.add_stream(codec_name, rate=sample_rate)
                    audio_output.layout = live_audio_stream.codec_context.layout.name
                    if codec_name == "flac":
                        audio_output.codec_context.format = "s32"
                    else:
                        audio_output.codec_context.format = "fltp"
                        audio_output.codec_context.bit_rate = args.bitrate

                cover_stream = None
                if cover_image is not None:
                    cover_stream = _add_cover_stream(output, cover_image)

                if cover_stream is not None and cover_image is not None:
                    _write_cover(output, cover_stream, cover_image)

                _write_audio(
                    audio_input,
                    live_audio_stream,
                    output,
                    audio_output,
                    codec_name,
                    gain_db,
                )

        if not temp_audio.exists() or temp_audio.stat().st_size == 0:
            raise ConversionError("出力ファイルを作成できませんでした")
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
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"PyAVの変換に失敗しました: {exc}") from exc
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
