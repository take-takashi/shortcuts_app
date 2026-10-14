from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

import av

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyav_split_by_5gib import parse_size, split_video


def _make_test_mp4(path: Path) -> None:
    with av.open(str(path), mode="w", format="mp4") as output:
        video = output.add_stream("mpeg4", rate=10)
        video.width = 128
        video.height = 128
        video.pix_fmt = "yuv420p"
        video.codec_context.gop_size = 10
        video.codec_context.max_b_frames = 0
        video.options = {"qscale": "2"}

        audio = output.add_stream("aac", rate=48_000)
        audio.layout = "stereo"

        for frame_index in range(50):
            frame = av.VideoFrame(128, 128, "yuv420p")
            for plane_index, plane in enumerate(frame.planes):
                plane.update(
                    bytes(
                        (offset * 31 + frame_index * 17 + plane_index * 77) % 256
                        for offset in range(plane.buffer_size)
                    )
                )
            frame.pts = frame_index
            for packet in video.encode(frame):
                output.mux(packet)
        for packet in video.encode(None):
            output.mux(packet)

        for frame_index in range(5 * 48_000 // 1024):
            frame = av.AudioFrame(format="fltp", layout="stereo", samples=1024)
            frame.sample_rate = 48_000
            frame.pts = frame_index * 1024
            frame.time_base = Fraction(1, 48_000)
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
            for packet in audio.encode(frame):
                output.mux(packet)
        for packet in audio.encode(None):
            output.mux(packet)


def _packet_payloads(path: Path, stream_type: str) -> list[bytes]:
    with av.open(str(path)) as container:
        stream = next(stream for stream in container.streams if stream.type == stream_type)
        return [bytes(packet) for packet in container.demux(stream) if packet.size]


def _decoded_frames(path: Path, stream_type: str) -> int:
    with av.open(str(path)) as container:
        stream = next(stream for stream in container.streams if stream.type == stream_type)
        return sum(1 for _ in container.decode(stream))


def test_parse_size():
    assert parse_size("5GiB") == 5 * 1024**3
    assert parse_size("500MB") == 500_000_000


def test_splits_on_keyframes_without_reencoding(tmp_path: Path):
    source = tmp_path / "input.mp4"
    output_dir = tmp_path / "parts"
    _make_test_mp4(source)

    outputs = split_video(source, output_dir, max_size=120 * 1024)

    assert len(outputs) > 1
    assert all(path.stat().st_size <= 120 * 1024 for path in outputs)
    for path in outputs:
        with av.open(str(path)) as container:
            first_video_packet = next(
                packet for packet in container.demux(video=0) if packet.size
            )
            assert first_video_packet.is_keyframe

    for stream_type in ("video", "audio"):
        source_packets = _packet_payloads(source, stream_type)
        split_packets = [
            payload
            for path in outputs
            for payload in _packet_payloads(path, stream_type)
        ]
        assert split_packets == source_packets
        assert sum(_decoded_frames(path, stream_type) for path in outputs) == _decoded_frames(
            source, stream_type
        )
