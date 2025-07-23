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
            program_name = ""
            episode_title = ""
            artist_name = ""
            cover_image_url = ""
            audio_src = ""

            soup = BeautifulSoup(html_content, "html.parser")

            # 番組名を取得
            program_elem = soup.select_one("h2.box-program-ttl.ttl-cmn-lev1 a")
            if program_elem:
                program_name = program_elem.get_text(strip=True)

            # エピソードタイトルを取得
            epsode_elem = soup.select_one("div.ttl-inner")
            if epsode_elem:
                episode_title_full = epsode_elem.get_text(strip=True)
                # 日付部分を除去してエピソードタイトルを抽出
                episode_title = episode_title_full.split(")", 1)[-1].strip()

            # パーソナリティ名を番組名から抽出
            # 例: 「伊藤沙莉のsaireek channel」から「伊藤沙莉」を抽出
            if "の" in program_name:
                artist_name = program_name.split("の", 1)[0].strip()
            else:
                artist_name = program_name  # 「の」がない場合は番組名をそのまま使用

            # フロントカバー画像URLを取得
            cover_image_elem = soup.select_one("meta[property='og:image']")
            if cover_image_elem:
                cover_image_url = str(cover_image_elem["content"])

            # 音声URLを取得
            audio_src = None
            # <script>タグ内のplaylist変数を正規表現で検索
            match = re.search(r"var playlist =\s*(\[.*?]);", html_content, re.DOTALL)
            if match:
                playlist_str = match.group(1)
                # playlistから音声URLを抽出
                # 簡単な文字列処理で対応するが、より複雑な場合はjsonライブラリなどが必要
                url_match = re.search(r"\"voice\":\s*\"(.*?)\"", playlist_str)
                if url_match:
                    audio_src = url_match.group(1)

            return AudioInfo(
                program_name=program_name,
                episode_title=episode_title,
                artist_name=artist_name,
                cover_image_url=cover_image_url or "",
                audio_src=audio_src or "",
            )
        except Exception as e:
            self.logger.error(f"audee.jpのHTML解析に失敗しました: {e}", exc_info=True)
            return None


class BitfanInfoExtractor(AudioInfoExtractorBase):
    """bitfan.netの音声情報抽出クラス"""

    def get_audio_info(self, html_content: str) -> AudioInfo | None:
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
    "ij-matome.bitfan.id": BitfanInfoExtractor,
}


def get_extractor(domain, logger):
    """ドメイン名に一致するExtractorのインスタンスを返す"""
    for key, extractor_class in EXTRACTOR_MAP.items():
        if key in domain:
            return extractor_class(logger)
    return None
