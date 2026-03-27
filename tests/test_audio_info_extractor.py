import logging
import os
from unittest.mock import Mock

import pytest

from AudioInfoExtractor import (
    AudeeInfoExtractor,
    AudioInfo,
    BitfanInfoExtractor,
    JfnPodsInfoExtractor,
    OmnyInfoExtractor,
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
    audio_infos = extractor.get_audio_info(html)

    if audio_infos is None:
        pytest.fail("audio_infosが取得できませんでした。")

    for audio_info in audio_infos:
        assert isinstance(audio_info, AudioInfo)
        assert audio_info is not None
        assert audio_info.program_name is not None
        assert audio_info.episode_title is not None
        assert audio_info.artist_name is not None
        assert audio_info.cover_image_url is not None
        assert audio_info.audio_src is not None
        assert audio_info.broadcast_date == "20220709"

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
    audio_infos = extractor.get_audio_info(html)

    if audio_infos is None:
        pytest.fail("audio_infosが取得できませんでした。")

    for audio_info in audio_infos:
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

    bitfan_extractor = get_extractor("ij-matome.bitfan.id", mock_logger)
    assert isinstance(bitfan_extractor, BitfanInfoExtractor)

    omny_extractor = get_extractor("omny.fm", mock_logger)
    assert isinstance(omny_extractor, OmnyInfoExtractor)

    jfn_pods_extractor = get_extractor("jfn-pods.com", mock_logger)
    assert isinstance(jfn_pods_extractor, JfnPodsInfoExtractor)

    unknown_extractor = get_extractor("unknown.com", mock_logger)
    assert unknown_extractor is None


def test_omny_info_extractor(mock_logger):
    html_path = os.path.join(
        os.path.dirname(__file__), "private_data", "page_omny_fm.html"
    )

    html = open(html_path, "r", encoding="utf-8").read()

    extractor = OmnyInfoExtractor(mock_logger)
    audio_infos = extractor.get_audio_info(html)

    if audio_infos is None:
        pytest.fail("audio_infosが取得できませんでした。")

    assert len(audio_infos) == 1
    audio_info = audio_infos[0]
    assert isinstance(audio_info, AudioInfo)
    assert audio_info.program_name != ""
    assert audio_info.episode_title != ""
    assert audio_info.artist_name != ""
    assert audio_info.cover_image_url.startswith("http")
    assert "traffic.omny.fm" in audio_info.audio_src
    assert audio_info.broadcast_date == "20260222"


def test_jfn_pods_info_extractor(mock_logger):
    html = """
    <!doctype html>
    <html lang="ja">
      <head>
        <meta property="og:title" content="実家帰省中に！サイコロトーク！vol.212｜伊藤沙莉のsaireek channel｜JFN Pods" />
        <meta property="og:image" content="https://jfn-pods.com/image/example.avif?min=600" />
      </head>
      <body>
        <h1>実家帰省中に！サイコロトーク！vol.212</h1>
        <div class="mt-24 font-semibold">伊藤沙莉のsaireek channel</div>
        <time datetime="2026-03-14">2026.03.14</time>
        <div
          class="voice-player"
          data-audio-url="https://cf.audee.jp/episode/40889/YF7GUMWdLU/tBQdV5tpTa_001.mp3"
          data-episode-name="実家でサイコロトーク！"
        ></div>
        <audio>
          <source src="https://cf.audee.jp/episode/40889/YF7GUMWdLU/tBQdV5tpTa_001.mp3" type="audio/mpeg">
        </audio>
      </body>
    </html>
    """

    extractor = JfnPodsInfoExtractor(mock_logger)
    audio_infos = extractor.get_audio_info(html)

    if audio_infos is None:
        pytest.fail("audio_infosが取得できませんでした。")

    assert len(audio_infos) == 1
    audio_info = audio_infos[0]
    assert isinstance(audio_info, AudioInfo)
    assert audio_info.program_name == "伊藤沙莉のsaireek channel"
    assert audio_info.episode_title == "実家でサイコロトーク！"
    assert audio_info.artist_name == "伊藤沙莉のsaireek channel"
    assert audio_info.cover_image_url == "https://jfn-pods.com/image/example.avif?min=600"
    assert audio_info.audio_src == "https://cf.audee.jp/episode/40889/YF7GUMWdLU/tBQdV5tpTa_001.mp3"
    assert audio_info.broadcast_date == "20260314"
