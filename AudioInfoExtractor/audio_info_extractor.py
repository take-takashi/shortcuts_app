import html
import json
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
    def get_audio_info(self, html_content: str) -> list[AudioInfo] | None:
        """HTML文字列から音声情報を取得する"""
        pass


class AudeeInfoExtractor(AudioInfoExtractorBase):
    """audee.jpの音声情報抽出クラス"""

    def get_audio_info(self, html_content: str) -> list[AudioInfo] | None:
        self.logger.info("audee.jpのメタデータと音声URLを解析します...")
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # --- 基本情報を取得 ---
            program_name_elem = soup.select_one("h2.box-program-ttl.ttl-cmn-lev1 a")
            program_name = (
                program_name_elem.get_text(strip=True) if program_name_elem else ""
            )

            artist_name = ""
            if "の" in program_name:
                artist_name = program_name.split("の", 1)[0].strip()
            else:
                artist_name = program_name

            cover_image_elem = soup.select_one("meta[property='og:image']")
            cover_image_url = (
                str(cover_image_elem["content"]) if cover_image_elem else ""
            )

            # --- ld+jsonから音声情報を取得 ---
            ld_json_elements = soup.find_all("script", type="application/ld+json")
            if not ld_json_elements:
                self.logger.error("ld+jsonが見つかりませんでした。")
                return None

            # パートに分かれて音声が存在する場合に備えてリストを用意
            audio_data_list = []
            for ld_json_elem in ld_json_elements:
                try:
                    ld_json_text = ld_json_elem.get_text()
                    if not ld_json_text:
                        continue

                    data = json.loads(ld_json_text.strip())

                    # dataがリストか辞書かで分岐
                    if isinstance(data, list):
                        # リストの最初の要素にaudioキーがあるかチェック
                        if data and "audio" in data[0]:
                            audio_data_list.extend(data[0]["audio"])
                    elif isinstance(data, dict):
                        if "audio" in data:
                            audios = data["audio"]
                            if isinstance(audios, list):
                                audio_data_list.extend(audios)
                            else:
                                audio_data_list.append(audios)

                except json.JSONDecodeError:
                    # パースに失敗した場合は無視して次の要素へ
                    continue

            if not audio_data_list:
                self.logger.warning("ld+json内に音声情報が見つかりませんでした。")
                return None

            # audio_dataが辞書の場合はリストに変換
            if isinstance(audio_data_list, dict):
                audio_data_list = [audio_data_list]

            audio_info_list = []
            for audio_data in audio_data_list:
                episode_title = audio_data.get("name", "")
                audio_src = audio_data.get("contentUrl", "")

                if not audio_src:
                    self.logger.warning(
                        f"音声URLが見つかりませんでした: {episode_title}"
                    )
                    continue

                audio_info_list.append(
                    AudioInfo(
                        program_name=program_name,
                        episode_title=episode_title,
                        artist_name=artist_name,
                        cover_image_url=cover_image_url,
                        audio_src=audio_src,
                    )
                )

            return audio_info_list if audio_info_list else None

        except Exception as e:
            self.logger.error(f"audee.jpのHTML解析に失敗しました: {e}", exc_info=True)
            return None


class BitfanInfoExtractor(AudioInfoExtractorBase):
    """bitfan.netの音声情報抽出クラス"""

    def get_audio_info(self, html_content: str) -> list[AudioInfo] | None:
        self.logger.info("bitfan.netのメタデータと音声URLを解析します...")
        try:
            program_name = ""
            episode_title = ""
            artist_name = ""
            cover_image_url = ""
            audio_src = ""

            soup = BeautifulSoup(html_content, "html.parser")

            # 音声URLを取得 (bs4では無理だったので正規表現で取得)
            match = re.search(
                r'<audio.*?<source src="([^"]+)"', html_content, re.DOTALL
            )
            if match:
                audio_src = html.unescape(match.group(1))

            # 番組名を取得
            program_elem = soup.select_one("meta[property='og:site_name']")
            if program_elem and program_elem.has_attr("content"):
                program_name = str(program_elem["content"])

            # エピソードタイトルを取得
            episode_elem = soup.select_one("h1.p-clubArticle__name")
            if episode_elem:
                episode_title = episode_elem.get_text(strip=True)

            # パーソナリティ名を取得
            # デフォルト値として番組名を設定 (番組名が取得できている場合)
            if program_name:
                artist_name = program_name

            artist_name_elements = soup.select(
                "div.p-clubArticle__content div.c-clubWysiwyg p"
            )
            for element in artist_name_elements:
                artist_text = element.get_text(strip=True)
                if "パーソナリティ：" in artist_text:
                    # 「パーソナリティ：」以降のテキストを取得
                    artist_name_raw = artist_text.split("パーソナリティ：", 1)[
                        1
                    ].strip()
                    # 「（」以降に補足情報が含まれる場合があるため、分割して前半部分のみ使用
                    artist_name_raw = artist_name_raw.split("（", 1)[0].strip()
                    # 全角スペースや読点などで分割し、各要素を整形
                    artists = [
                        name.strip()
                        for name in re.split(
                            r"[\s、,/・]|パートナー：", artist_name_raw
                        )
                        if name.strip()
                    ]
                    if artists:
                        artist_name = ", ".join(artists)
                    break  # マッチしたらループを抜ける

            # カバー画像URLを取得
            cover_image_elem = soup.select_one("div.p-clubArticle__thumb img")
            if cover_image_elem and cover_image_elem.has_attr("src"):
                cover_image_url = str(cover_image_elem["src"])

            if not audio_src:
                self.logger.warning("音声URLが見つかりませんでした。")
                return None

            return [
                AudioInfo(
                    program_name=program_name,
                    episode_title=episode_title,
                    artist_name=artist_name,
                    cover_image_url=cover_image_url,
                    audio_src=audio_src,
                )
            ]
        except Exception as e:
            self.logger.error(f"bitfan.netのHTML解析に失敗しました: {e}", exc_info=True)
            return None


# --- ドメインとExtractorのマッピング ---
EXTRACTOR_MAP = {
    "audee.jp": AudeeInfoExtractor,
    "ij-matome.bitfan.id": BitfanInfoExtractor,
}


def get_extractor(domain, logger):
    """ドメイン名に一致するExtractorのインスタンスを返す"""
    for key, extractor_class in EXTRACTOR_MAP.items():
        if key in domain:
            return extractor_class(logger)
    return None
