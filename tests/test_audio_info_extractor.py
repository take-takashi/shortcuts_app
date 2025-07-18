import pytest
from unittest.mock import Mock
from bs4 import BeautifulSoup
import os

from AudioInfoExtractor import AudeeInfoExtractor, BitfanInfoExtractor, AudioInfo, get_extractor

# テスト用のダミーロガー
@pytest.fixture
def mock_logger():
    return Mock()

# AudeeInfoExtractorのテスト
def test_audee_info_extractor(mock_logger):
    html_path = os.path.join(os.path.dirname(__file__), "private_data", "audee_sample.html")
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    extractor = AudeeInfoExtractor(mock_logger)
    audio_info = extractor.get_audio_info(soup)

    assert isinstance(audio_info, AudioInfo)
    assert audio_info.program_name == "テスト番組名 - audee.jp"
    assert audio_info.episode_title == "テストエピソードタイトル - audee.jp"
    assert audio_info.artist_name == "テスト番組名 - audee.jp"
    assert audio_info.cover_image_url == "https://example.com/audee_cover.jpg"
    assert audio_info.audio_src == "https://example.com/audee_audio.mp3"

# BitfanInfoExtractorのテスト
def test_bitfan_info_extractor(mock_logger):
    html_path = os.path.join(os.path.dirname(__file__), "private_data", "bitfan_sample.html")
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    extractor = BitfanInfoExtractor(mock_logger)
    audio_info = extractor.get_audio_info(soup)

    assert isinstance(audio_info, AudioInfo)
    assert audio_info.program_name == "テスト番組名 - bitfan.net"
    assert audio_info.episode_title == "テストエピソードタイトル - bitfan.net"
    assert audio_info.artist_name == "テスト番組名 - bitfan.net"
    assert audio_info.cover_image_url == "https://example.com/bitfan_cover.jpg"
    assert audio_info.audio_src == "https://example.com/bitfan_audio.mp3"

# get_extractor関数のテスト
def test_get_extractor(mock_logger):
    audee_extractor = get_extractor("audee.jp", mock_logger)
    assert isinstance(audee_extractor, AudeeInfoExtractor)

    bitfan_extractor = get_extractor("bitfan.net", mock_logger)
    assert isinstance(bitfan_extractor, BitfanInfoExtractor)

    unknown_extractor = get_extractor("unknown.com", mock_logger)
    assert unknown_extractor is None
