import html
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from bs4 import BeautifulSoup


# --- 型定義 ---
@dataclass
class AudioInfo:
    """音声情報のデータ構造を定義する型"""

    program_name: str
    episode_title: str
    artist_name: str
    cover_image_url: str
    audio_src: str


class AudioInfoExtractorBase(ABC):
    """音声情報抽出の基底クラス"""

    def __init__(self, logger):
        self.logger = logger

    @abstractmethod
    def get_audio_info(self, html_content: str) -> AudioInfo | None:
        """HTML文字列から音声情報を取得する"""
        pass


class AudeeInfoExtractor(AudioInfoExtractorBase):
    """audee.jpの音声情報抽出クラス"""

    def get_audio_info(self, html_content: str) -> AudioInfo | None:
        self.logger.info("audee.jpのメタデータと音声URLを解析します...")
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            program_name = soup.select_one(
                "h2.box-program-ttl.ttl-cmn-lev1 a"
            ).get_text(strip=True)
            episode_title_full = soup.select_one("div.ttl-inner").get_text(strip=True)
            # 日付部分を除去してエピソードタイトルを抽出
            episode_title = episode_title_full.split(")", 1)[-1].strip()

            # パーソナリティ名を番組名から抽出
            # 例: 「伊藤沙莉のsaireek channel」から「伊藤沙莉」を抽出
            if "の" in program_name:
                artist_name = program_name.split("の", 1)[0].strip()
            else:
                artist_name = program_name  # 「の」がない場合は番組名をそのまま使用

            cover_image_url = soup.select_one("meta[property='og:image']")["content"]

            audio_src = None
            match = re.search(
                r'<audio.*?<source src="([^"]+)"', html_content, re.DOTALL
            )
            if match:
                audio_src = html.unescape(match.group(1))

            return AudioInfo(
                program_name=program_name,
                episode_title=episode_title,
                artist_name=artist_name,
                cover_image_url=cover_image_url,
                audio_src=audio_src,
            )
        except Exception as e:
            self.logger.error(f"audee.jpのHTML解析に失敗しました: {e}", exc_info=True)
            return None


class BitfanInfoExtractor(AudioInfoExtractorBase):
    """bitfan.netの音声情報抽出クラス"""

    def get_audio_info(self, html_content: str) -> AudioInfo | None:
        self.logger.info("bitfan.netのメタデータと音声URLを解析します...")
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # bs4ではiframe内の解析ができないので普通の正規表現を使用
            audio_src = None
            match = re.search(
                r'<audio.*?<source src="([^"]+)"', html_content, re.DOTALL
            )
            if match:
                audio_src = html.unescape(match.group(1))

            if not audio_src:
                self.logger.error("正規表現で音声URLが見つかりませんでした。")
                return None

            program_name = soup.select_one("meta[property='og:site_name']")["content"]
            episode_title = soup.select_one("h1.p-clubArticle__name").get_text(
                strip=True
            )
            artist_name_element = soup.select_one(
                "div.p-clubArticle__content div.c-clubWysiwyg p"
            )
            artist_name = program_name  # デフォルト値
            if artist_name_element:
                artist_text = artist_name_element.get_text(strip=True)
                if "パーソナリティ：" in artist_text:
                    # 「パーソナリティ：」以降のテキストを取得し、最初の「　」または「（」までを抽出
                    artist_name_raw = (
                        artist_text.split("パーソナリティ：", 1)[1]
                        .split(" ", 1)[0]
                        .split("（", 1)[0]
                        .strip()
                    )
                    artist_name = artist_name_raw
            cover_image_url = soup.select_one("div.p-clubArticle__thumb img")["src"]

            return AudioInfo(
                program_name=program_name,
                episode_title=episode_title,
                artist_name=artist_name,
                cover_image_url=cover_image_url,
                audio_src=audio_src,
            )
        except Exception as e:
            self.logger.error(f"bitfan.netのHTML解析に失敗しました: {e}", exc_info=True)
            return None


# --- ドメインとExtractorのマッピング ---
EXTRACTOR_MAP = {
    "audee.jp": AudeeInfoExtractor,
    "bitfan.net": BitfanInfoExtractor,
}


def get_extractor(domain, logger):
    """ドメイン名に一致するExtractorのインスタンスを返す"""
    for key, extractor_class in EXTRACTOR_MAP.items():
        if key in domain:
            return extractor_class(logger)
    return None
