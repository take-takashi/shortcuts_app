import os
import subprocess
import tempfile

import pytest

from MyFfmpegHelper.my_ffmpeg_helper import MyFfmpegHelper

# テスト用のダミー動画ファイルのパスを設定してください
# 実際のCBR動画とVBR動画のパスに置き換えてください
# 例: cbr_video_path = "/path/to/your/cbr_video.mp4"
# 例: vbr_video_path = "/path/to/your/vbr_video.mp4"
cbr_video_path = "./tests/cbr_test.mp4"  # ここを実際のCBR動画のパスに置き換える
vbr_video_path = "./tests/vbr_test.mp4"  # ここを実際のVBR動画のパスに置き換える


@pytest.mark.skipif(
    not os.path.exists(cbr_video_path), reason="CBRテスト動画が存在しません"
)
def test_is_vbr_cbr_video():
    """CBR動画に対してis_vbrがFalseを返すことをテスト"""
    # assert not MyFfmpegHelper.is_vbr(cbr_video_path)
    pass


@pytest.mark.skipif(
    not os.path.exists(vbr_video_path), reason="VBRテスト動画が存在しません"
)
def test_is_vbr_vbr_video():
    """VBR動画に対してis_vbrがTrueを返すことをテスト"""
    assert MyFfmpegHelper.is_vbr(vbr_video_path)


def test_is_vbr_non_existent_file():
    """存在しないファイルに対してis_vbrが例外を発生させることをテスト"""
    with pytest.raises(Exception, match="エラーが発生しました"):
        MyFfmpegHelper.is_vbr("non_existent_video.mp4")


def test_is_vbr_empty_file():
    """空のファイルに対してis_vbrが例外を発生させることをテスト"""
    # 空のダミーファイルを作成
    empty_file_path = "empty_file.mp4"
    open(empty_file_path, "a").close()
    try:
        with pytest.raises(Exception):  # ffprobeがエラーを返すことを期待
            MyFfmpegHelper.is_vbr(empty_file_path)
    finally:
        os.remove(empty_file_path)

def test_get_audio_metadata():
    """音声ファイルからメタデータを正しく取得できるかテスト"""
    audio_file_path = "./tests/sample.mp3"
    
    # 期待されるメタデータ
    expected_metadata = {
        "title": "タイトル表示",
        "album": "効果音ラボ",
        "artist": "サンプルミュージシャン",
        "track": "1/1",
        "date": "2025",
        "genre": "Soundtrack"
    }

    # メタデータを取得
    actual_metadata = MyFfmpegHelper.get_audio_metadata(audio_file_path)

    # 取得したメタデータが期待通りか検証
    assert actual_metadata is not None
    assert actual_metadata.get("title") == expected_metadata["title"]
    assert actual_metadata.get("album") == expected_metadata["album"]
    assert actual_metadata.get("artist") == expected_metadata["artist"]
    assert actual_metadata.get("track") == expected_metadata["track"]
    assert actual_metadata.get("date") == expected_metadata["date"]
    assert actual_metadata.get("genre") == expected_metadata["genre"]


def test_embed_metadata_with_avif_cover():
    """AVIFカバー画像付きでもMP3へ正常に埋め込めることをテスト"""
    audio_file_path = "./tests/sample.mp3"

    with tempfile.TemporaryDirectory() as temp_dir:
        cover_path = os.path.join(temp_dir, "cover.avif")
        output_path = os.path.join(temp_dir, "output.mp3")

        # AVIFのカバー画像を動的生成する
        subprocess.run(
            [
                "ffmpeg",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=32x32:d=1",
                "-frames:v",
                "1",
                "-c:v",
                "libsvtav1",
                "-f",
                "avif",
                "-y",
                cover_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        MyFfmpegHelper.embed_metadata(
            input_path=audio_file_path,
            output_path=output_path,
            metadata={
                "title": "AVIF付きタイトル",
                "artist": "AVIF付きアーティスト",
                "album": "AVIF付きアルバム",
            },
            cover_path=cover_path,
        )

        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 10 * 1024

        metadata = MyFfmpegHelper.get_audio_metadata(output_path)
        assert metadata is not None
        assert metadata.get("title") == "AVIF付きタイトル"
        assert metadata.get("artist") == "AVIF付きアーティスト"
        assert metadata.get("album") == "AVIF付きアルバム"

        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type:stream_disposition=attached_pic",
                "-of",
                "default=noprint_wrappers=1",
                output_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "codec_type=audio" in probe.stdout
        assert "codec_type=video" in probe.stdout
        assert "attached_pic=1" in probe.stdout
