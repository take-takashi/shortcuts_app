import logging
import os
from unittest.mock import Mock

import pytest

from AudioInfoExtractor import (
    AudeeInfoExtractor,
    AudioInfo,
    BitfanInfoExtractor,
    get_extractor,
)

# print用logger
logger = logging.getLogger(__name__)


# テスト用のダミーロガー
@pytest.fixture
def mock_logger():
    return Mock()


# AudeeInfoExtractorのテスト
def test_audee_info_extractor(mock_logger):
    # htmlファイルは自分でダウンロードして配置すること
    html_path = os.path.join(
        os.path.dirname(__file__), "private_data", "test_audee_page.html"
    )

    # htmlを読み込む
    html = open(html_path, "r", encoding="utf-8").read()

    extractor = AudeeInfoExtractor(mock_logger)
    audio_info = extractor.get_audio_info(html)

    assert isinstance(audio_info, AudioInfo)
    assert audio_info is not None
    assert audio_info.program_name is not None
    assert audio_info.episode_title is not None
    assert audio_info.artist_name is not None
    assert audio_info.cover_image_url is not None
    assert audio_info.audio_src is not None

    # 取得したHTMLによって取得できるタイトルなどが異なるため、print目視とする
    logger.info(f"program_name: {audio_info.program_name}")
    logger.info(f"episode_title: {audio_info.episode_title}")
    logger.info(f"artist_name: {audio_info.artist_name}")
    logger.info(f"cover_image_url: {audio_info.cover_image_url}")
    logger.info(f"audio_src: {audio_info.audio_src}")


# BitfanInfoExtractorのテスト
def test_bitfan_info_extractor(mock_logger):
    # htmlファイルは自分でダウンロードして配置すること
    html_path = os.path.join(
        os.path.dirname(__file__), "private_data", "test_bitfan_page.html"
    )

    # htmlを読み込む
    html = open(html_path, "r", encoding="utf-8").read()

    extractor = BitfanInfoExtractor(mock_logger)
    audio_info = extractor.get_audio_info(html)

    assert isinstance(audio_info, AudioInfo)
    assert audio_info is not None
    assert audio_info.program_name is not None
    assert audio_info.episode_title is not None
    assert audio_info.artist_name is not None
    assert audio_info.cover_image_url is not None
    assert audio_info.audio_src is not None
    # 取得したHTMLによって取得できるタイトルなどが異なるため、print目視とする
    logger.info(f"program_name: {audio_info.program_name}")
    logger.info(f"episode_title: {audio_info.episode_title}")
    logger.info(f"artist_name: {audio_info.artist_name}")
    logger.info(f"cover_image_url: {audio_info.cover_image_url}")
    logger.info(f"audio_src: {audio_info.audio_src}")


# get_extractor関数のテスト
def test_get_extractor(mock_logger):
    audee_extractor = get_extractor("audee.jp", mock_logger)
    assert isinstance(audee_extractor, AudeeInfoExtractor)

    bitfan_extractor = get_extractor("bitfan.net", mock_logger)
    assert isinstance(bitfan_extractor, BitfanInfoExtractor)

    unknown_extractor = get_extractor("unknown.com", mock_logger)
    assert unknown_extractor is None
