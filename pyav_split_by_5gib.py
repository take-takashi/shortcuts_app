#!/usr/bin/env python3
"""Split an MP4 into independently playable, keyframe-aligned parts without re-encoding."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from bisect import bisect_left, bisect_right
from typing import Any

import av
from av.container.output import OutputContainer
from av.stream import Disposition, Stream

GIB = 1024**3
MIB = 1024**2
DEFAULT_MAX_SIZE = 5 * GIB
SAFETY_MARGIN = 16 * MIB


class SplitError(RuntimeError):
    """Raised when the input cannot be split safely within the requested limit."""


@dataclass(frozen=True)
class Keyframe:
    video_packet_index: int
    bytes_before: int
    video_bytes_before: int
    timestamp: Fraction


@dataclass(frozen=True)
class TimedPacket:
    timestamp: Fraction | None
    size: int


@dataclass(frozen=True)
class InputInfo:
    video_packet_count: int
    payload_bytes: int
    video_stream_index: int
    first_keyframe: Keyframe
    keyframes: tuple[Keyframe, ...]


def parse_size(value: str) -> int:
    """Parse a byte count or a size such as 5GiB, 500MB, or 128MiB."""
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|KIB|MIB|GIB)?\s*", value, re.I
    )
    if not match:
        raise argparse.ArgumentTypeError("サイズ例: 5GiB, 500MB, 5368709120")
    amount = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    multiplier = {
        "B": 1,
        "KB": 1_000,
        "MB": 1_000_000,
        "GB": 1_000_000_000,
        "KIB": 1024,
        "MIB": 1024**2,
        "GIB": 1024**3,
    }[unit]
    result = int(amount * multiplier)
    if result <= 0:
        raise argparse.ArgumentTypeError("サイズは正の値にしてください")
    return result


def _usable_packet(packet: av.Packet) -> bool:
    # demux() emits a zero-sized flush packet for each stream at EOF.
    return packet.size > 0 and (packet.dts is not None or packet.pts is not None)


def _packet_time(packet: av.Packet) -> tuple[Fraction | None, Fraction]:
    time_base = packet.time_base or packet.stream.time_base
    if time_base is None:
        return None, Fraction(0)
    timestamp = packet.pts if packet.pts is not None else packet.dts
    timestamp_time = Fraction(timestamp) * time_base if timestamp is not None else None
    duration = Fraction(packet.duration) * time_base if packet.duration else Fraction(0)
    return timestamp_time, duration


def _add_stream_for_mux(output: OutputContainer, input_stream: Any) -> Any:
    """Add a stream for packet-copy muxing, including decoder-only codecs."""
    codec = input_stream.codec_context.codec
    codec_name = codec.canonical_name if codec else input_stream.codec_context.name
    decoder_name = codec.name if codec else codec_name

    if decoder_name == codec_name:
        output_stream = output.add_stream_from_template(input_stream)
    elif input_stream.type == "video":
        output_stream = output.add_mux_stream(
            codec_name,
            rate=input_stream.average_rate,
            width=input_stream.width,
            height=input_stream.height,
            time_base=input_stream.time_base,
        )
    else:
        output_stream = output.add_mux_stream(
            codec_name,
            rate=input_stream.sample_rate if input_stream.type == "audio" else None,
            time_base=input_stream.time_base,
        )

    output_stream.metadata.update(input_stream.metadata)
    output_stream.disposition = input_stream.disposition
    return output_stream


def inspect_input(input_path: Path) -> InputInfo:
    """Collect packet sizes and keyframe positions without decoding the streams."""
    with av.open(str(input_path), mode="r") as source:
        video_streams = [
            stream
            for stream in source.streams.video
            if not (stream.disposition & Disposition.attached_pic)
        ]
        if not video_streams:
            raise SplitError("入力に動画トラックがありません")
        if len(video_streams) != 1:
            raise SplitError("複数の動画トラックがあるMP4には対応していません")

        video_index = video_streams[0].index
        raw_keyframes: list[Keyframe] = []
        timed_packets: list[TimedPacket] = []
        video_packet_index = 0
        payload_bytes = 0
        video_payload_bytes = 0
        first_video_packet_seen = False

        for packet in source.demux():
            if not _usable_packet(packet):
                continue
            if packet.stream.index == video_index:
                if not first_video_packet_seen:
                    first_video_packet_seen = True
                    if not packet.is_keyframe:
                        raise SplitError("動画トラックの先頭がキーフレームではありません")
                if packet.is_keyframe:
                    timestamp, _ = _packet_time(packet)
                    if timestamp is not None:
                        raw_keyframes.append(
                            Keyframe(
                                video_packet_index=video_packet_index,
                                bytes_before=0,
                                video_bytes_before=video_payload_bytes,
                                timestamp=timestamp,
                            )
                        )
                video_packet_index += 1
                video_payload_bytes += packet.size
            else:
                timestamp, _ = _packet_time(packet)
                timed_packets.append(TimedPacket(timestamp, packet.size))
            payload_bytes += packet.size

    if not raw_keyframes:
        raise SplitError("動画のキーフレームを検出できませんでした")

    # Estimate all-stream cumulative bytes at each video keyframe. The final
    # file-size check below handles muxer overhead and variable audio timing.
    timestamped_packets = sorted(
        (packet.timestamp, packet.size)
        for packet in timed_packets
        if packet.timestamp is not None
    )
    packet_times = [timestamp for timestamp, _ in timestamped_packets]
    cumulative_other_bytes = [0]
    for _, size in timestamped_packets:
        cumulative_other_bytes.append(cumulative_other_bytes[-1] + size)
    untimed_bytes = sum(packet.size for packet in timed_packets if packet.timestamp is None)

    keyframes = tuple(
        Keyframe(
            video_packet_index=keyframe.video_packet_index,
            bytes_before=(
                keyframe.video_bytes_before
                + untimed_bytes
                + cumulative_other_bytes[bisect_left(packet_times, keyframe.timestamp)]
            ),
            video_bytes_before=keyframe.video_bytes_before,
            timestamp=keyframe.timestamp,
        )
        for keyframe in raw_keyframes
    )
    return InputInfo(
        video_packet_count=video_packet_index,
        payload_bytes=payload_bytes,
        video_stream_index=video_index,
        first_keyframe=keyframes[0],
        keyframes=keyframes,
    )


def _plan_cuts(info: InputInfo, max_size: int) -> list[Keyframe]:
    """Choose keyframe boundaries using packet payload size as an estimate."""
    # Leave room for the MP4 index/metadata. Finalized files are still checked
    # against the exact limit below, and an earlier keyframe is added if needed.
    margin = min(SAFETY_MARGIN, max(1, max_size // 100))
    target = max(1, max_size - margin)
    cuts: list[Keyframe] = []
    start_video_index = 0
    start_bytes = 0

    while info.payload_bytes - start_bytes > target:
        remaining_bytes = info.payload_bytes - start_bytes
        later = [
            keyframe
            for keyframe in info.keyframes
            if keyframe.video_packet_index > start_video_index
        ]
        if not later:
            if remaining_bytes <= max_size:
                break
            raise SplitError(
                "残り部分に分割可能なキーフレームがありません。"
                "キーフレーム間のデータだけで上限を超えている可能性があります。"
            )

        eligible = [keyframe for keyframe in later if keyframe.bytes_before - start_bytes <= target]
        cut = eligible[-1] if eligible else later[0]
        estimated_size = cut.bytes_before - start_bytes
        if estimated_size > max_size:
            raise SplitError(
                "次のキーフレームまでのデータだけでサイズ上限を超えます。"
                "再エンコードせずに独立再生可能な分割はできません。"
            )
        cuts.append(cut)
        start_video_index = cut.video_packet_index
        start_bytes = cut.bytes_before

    return cuts


def _part_ranges(
    info: InputInfo, cuts: list[Keyframe]
) -> list[tuple[int, int, Fraction]]:
    starts = [0, *(cut.video_packet_index for cut in cuts)]
    ends = [*(cut.video_packet_index for cut in cuts), info.video_packet_count]
    origins = [info.first_keyframe.timestamp, *(cut.timestamp for cut in cuts)]
    return list(zip(starts, ends, origins, strict=True))


def _packet_destination(timestamp: Fraction | None, cut_times: list[Fraction]) -> int:
    """Assign each non-primary-video packet to exactly one part by its timestamp."""
    if timestamp is None:
        return 0
    return bisect_right(cut_times, timestamp)


def _mux_packet(
    packet: av.Packet,
    output: OutputContainer,
    output_stream: Stream,
    origin: Fraction,
) -> None:
    time_base = packet.time_base or packet.stream.time_base
    if time_base is None:
        raise SplitError("パケットのtime_baseを取得できませんでした")
    packet_copy = av.Packet(bytes(packet))
    packet_copy.pts = packet.pts
    packet_copy.dts = packet.dts
    packet_copy.duration = packet.duration
    packet_copy.is_keyframe = packet.is_keyframe
    packet_copy.is_corrupt = packet.is_corrupt
    for side_data in packet.iter_sidedata():
        packet_copy.set_sidedata(side_data)

    offset = round(origin / time_base)
    if packet_copy.pts is not None:
        packet_copy.pts -= offset
    if packet_copy.dts is not None:
        packet_copy.dts -= offset
    packet_copy.time_base = time_base
    packet_copy.stream = output_stream
    packet_copy.time_base = time_base
    output.mux(packet_copy)


def _write_parts(
    input_path: Path,
    temp_paths: list[Path],
    info: InputInfo,
    cuts: list[Keyframe],
) -> None:
    ranges = _part_ranges(info, cuts)
    cut_video_indices = [cut.video_packet_index for cut in cuts]
    cut_times = [cut.timestamp for cut in cuts]

    with ExitStack() as stack:
        source = stack.enter_context(av.open(str(input_path), mode="r"))
        outputs = []
        stream_maps: list[dict[int, Stream]] = []
        for temp_path in temp_paths:
            output = stack.enter_context(av.open(str(temp_path), mode="w", format="mp4"))
            output.metadata.update(source.metadata)
            stream_map: dict[int, Stream] = {}
            for input_stream in source.streams:
                stream_map[input_stream.index] = _add_stream_for_mux(
                    output, input_stream
                )
            outputs.append(output)
            stream_maps.append(stream_map)

        attached_picture_indices = {
            stream.index
            for stream in source.streams.video
            if stream.disposition & Disposition.attached_pic
        }
        video_packet_index = 0
        for packet in source.demux():
            if packet.size <= 0:
                continue
            if (
                packet.stream.index not in attached_picture_indices
                and packet.dts is None
                and packet.pts is None
            ):
                continue
            if packet.stream.index == info.video_stream_index:
                part_index = bisect_right(cut_video_indices, video_packet_index)
                _mux_packet(
                    packet,
                    outputs[part_index],
                    stream_maps[part_index][packet.stream.index],
                    ranges[part_index][2],
                )
                video_packet_index += 1
            elif packet.stream.index in attached_picture_indices:
                # Attachments belong in every standalone part and always start at 0.
                for output, stream_map in zip(outputs, stream_maps, strict=True):
                    _mux_packet(
                        packet,
                        output,
                        stream_map[packet.stream.index],
                        Fraction(0),
                    )
            elif packet.stream.type == "video":
                # Other non-primary video streams belong in every standalone part.
                for part_index, (output, stream_map, part_range) in enumerate(
                    zip(outputs, stream_maps, ranges, strict=True)
                ):
                    _mux_packet(
                        packet,
                        output,
                        stream_map[packet.stream.index],
                        part_range[2],
                    )
            else:
                timestamp, duration = _packet_time(packet)
                part_index = _packet_destination(timestamp, cut_times)
                _mux_packet(
                    packet,
                    outputs[part_index],
                    stream_maps[part_index][packet.stream.index],
                    ranges[part_index][2],
                )

        if video_packet_index != info.video_packet_count:
            raise SplitError("入力の再読み込み中に動画パケット数が変わりました")


def split_video(
    input_path: Path,
    output_dir: Path | None = None,
    max_size: int = DEFAULT_MAX_SIZE,
    overwrite: bool = False,
) -> list[Path]:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"入力ファイルがありません: {input_path}")
    if max_size <= 0:
        raise ValueError("max_sizeは正の値にしてください")

    output_dir = (output_dir or input_path.parent).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem
    output_pattern = re.compile(rf"^{re.escape(stem)}_part\d+\.mp4$")
    existing = [path for path in output_dir.iterdir() if output_pattern.fullmatch(path.name)]
    if existing and not overwrite:
        raise FileExistsError(
            "出力ファイルが既にあります。上書きする場合は --force を指定してください: "
            + ", ".join(str(path) for path in existing)
        )

    info = inspect_input(input_path)
    cuts = _plan_cuts(info, max_size)

    with tempfile.TemporaryDirectory(prefix=f".{stem}_split_", dir=output_dir) as temp_name:
        temp_dir = Path(temp_name)
        attempt = 0
        while True:
            attempt += 1
            ranges = _part_ranges(info, cuts)
            temp_paths = [
                temp_dir / f"part_{number:03d}.mp4"
                for number in range(1, len(ranges) + 1)
            ]
            _write_parts(input_path, temp_paths, info, cuts)
            sizes = [path.stat().st_size for path in temp_paths]

            oversized_index = next(
                (index for index, size in enumerate(sizes) if size > max_size), None
            )
            if oversized_index is None:
                break

            start, end, _ = ranges[oversized_index]
            start_bytes = 0 if start == 0 else next(
                keyframe.bytes_before
                for keyframe in info.keyframes
                if keyframe.video_packet_index == start
            )
            internal_keyframes = [
                keyframe
                for keyframe in info.keyframes
                if start < keyframe.video_packet_index < end
            ]
            if not internal_keyframes:
                raise SplitError(
                    f"{sizes[oversized_index]} bytesのパートを上限 {max_size} bytes 以下にできません。"
                    "この区間には追加で切れるキーフレームがありません。"
                )

            margin = min(SAFETY_MARGIN, max(1, max_size // 100))
            target = max(1, max_size - margin)
            eligible = [
                keyframe
                for keyframe in internal_keyframes
                if keyframe.bytes_before - start_bytes <= target
            ]
            new_cut = eligible[-1] if eligible else internal_keyframes[0]
            cuts.insert(oversized_index, new_cut)
            print(
                f"part {oversized_index + 1} が上限超過のため、"
                f"前のキーフレームで再分割します (試行 {attempt})",
                file=sys.stderr,
            )

        final_paths = [
            output_dir / f"{stem}_part{number:03d}.mp4"
            for number in range(1, len(temp_paths) + 1)
        ]
        for temp_path, final_path in zip(temp_paths, final_paths, strict=True):
            os.replace(temp_path, final_path)
        if overwrite:
            final_set = set(final_paths)
            for old_path in existing:
                if old_path not in final_set and old_path.exists():
                    old_path.unlink()

    return final_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MP4を再エンコードせず、キーフレーム位置で5GiB以下のパートに分割します。"
    )
    parser.add_argument("input", type=Path, help="分割するMP4ファイル")
    parser.add_argument("--output-dir", type=Path, help="出力先 (既定: 入力ファイルと同じフォルダ)")
    parser.add_argument(
        "--max-size",
        type=parse_size,
        default=DEFAULT_MAX_SIZE,
        help="パートの最大サイズ。例: 5GiB, 500MB (既定: 5GiB)",
    )
    parser.add_argument("--force", action="store_true", help="既存の出力を上書き")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = split_video(args.input, args.output_dir, args.max_size, args.force)
    except Exception as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    print(f"{len(paths)}個のパートを出力しました:")
    for path in paths:
        print(f"  {path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
