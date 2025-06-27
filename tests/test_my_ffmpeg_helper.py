import pytest
import os
from MyFfmpegHelper.my_ffmpeg_helper import MyFfmpegHelper

# テスト用のダミー動画ファイルのパスを設定してください
# 実際のCBR動画とVBR動画のパスに置き換えてください
# 例: cbr_video_path = "/path/to/your/cbr_video.mp4"
# 例: vbr_video_path = "/path/to/your/vbr_video.mp4"
cbr_video_path = "./tests/cbr_test.mp4"  # ここを実際のCBR動画のパスに置き換える
vbr_video_path = "./tests/vbr_test.mp4"  # ここを実際のVBR動画のパスに置き換える

@pytest.mark.skipif(not os.path.exists(cbr_video_path), reason="CBRテスト動画が存在しません")
def test_is_vbr_cbr_video():
    """CBR動画に対してis_vbrがFalseを返すことをテスト"""
    assert not MyFfmpegHelper.is_vbr(cbr_video_path)

@pytest.mark.skipif(not os.path.exists(vbr_video_path), reason="VBRテスト動画が存在しません")
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
    open(empty_file_path, 'a').close()
    try:
        with pytest.raises(Exception): # ffprobeがエラーを返すことを期待
            MyFfmpegHelper.is_vbr(empty_file_path)
    finally:
        os.remove(empty_file_path)
