
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from abc import ABC, abstractmethod
from typing import TypedDict


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
    def get_audio_info(self, soup) -> AudioInfo | None:
        """HTML(BeautifulSoupオブジェクト)から音声情報を取得する"""
        pass


class AudeeInfoExtractor(AudioInfoExtractorBase):
    """audee.jpの音声情報抽出クラス"""

    def get_audio_info(self, soup) -> AudioInfo | None:
        self.logger.info("audee.jpのメタデータと音声URLを解析します...")
        try:
            program_name = soup.select_one("meta[property='og:site_name']")["content"]
            episode_title = soup.select_one("meta[property='og:title']")["content"]
            artist_name = program_name
            cover_image_url = soup.select_one("meta[property='og:image']")["content"]

            audio_src = None
            json_ld_scripts = soup.find_all("script", type="application/ld+json")

            def find_audio_url_in_json(data):
                if isinstance(data, dict):
                    if data.get("@type") == "AudioObject" and data.get("contentUrl"):
                        return data["contentUrl"]
                    for key, value in data.items():
                        found = find_audio_url_in_json(value)
                        if found:
                            return found
                elif isinstance(data, list):
                    for item in data:
                        found = find_audio_url_in_json(item)
                        if found:
                            return found
                return None

            for script in json_ld_scripts:
                try:
                    json_data = json.loads(script.string)
                    audio_src = find_audio_url_in_json(json_data)
                    if audio_src:
                        break
                except (json.JSONDecodeError, AttributeError):
                    continue

            if not audio_src:
                self.logger.error("HTML内のJSON-LDから音声URLが見つかりませんでした。")
                return None

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

    def get_audio_info(self, soup) -> AudioInfo | None:
        self.logger.info("bitfan.netのメタデータと音声URLを解析します...")
        try:
            program_name = soup.select_one("meta[property='og:site_name']")["content"]
            episode_title = soup.select_one("h1.p-clubArticle__name").get_text(strip=True)
            artist_name = program_name
            cover_image_url = soup.select_one("div.p-clubArticle__thumb img")["src"]

            audio_tag = soup.select_one("audio")
            audio_src = None
            if audio_tag:
                if audio_tag.has_attr("src"):
                    audio_src = audio_tag["src"]
                else:
                    source_tag = audio_tag.select_one("source")
                    if source_tag and source_tag.has_attr("src"):
                        audio_src = source_tag["src"]

            if not audio_src:
                self.logger.error("audioタグまたはsourceタグが見つかりませんでした。")
                return None

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
