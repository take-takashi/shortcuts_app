import argparse
import os
import subprocess
import requests
import json
from bs4 import BeautifulSoup

from MyPathHelper.my_path_helper import MyPathHelper
from MyLoggerHelper.my_logger_helper import MyLoggerHelper

# --- ドメインごとの処理 ---

def get_audio_info_audee(soup, logger):
    """audee.jpのHTML(BeautifulSoupオブジェクト)から音声情報を取得する"""
    logger.info("audee.jpのメタデータと音声URLを解析します...")
    try:
        # ページのメタ情報から番組名などを取得
        program_name = soup.select_one("meta[property='og:site_name']")["content"]
        episode_title = soup.select_one("meta[property='og:title']")["content"]
        artist_name = program_name
        cover_image_url = soup.select_one("meta[property='og:image']")["content"]

        # JSON-LD (埋め込み構造化データ) から音声URLを探索
        audio_src = None
        json_ld_scripts = soup.find_all("script", type="application/ld+json")

        def find_audio_url_in_json(data):
            """JSONデータ内を再帰的に探索してAudioObjectのcontentUrlを探す"""
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
            logger.error("HTML内のJSON-LDから音声URLが見つかりませんでした。")
            return None

        return {
            "program_name": program_name,
            "episode_title": episode_title,
            "artist_name": artist_name,
            "cover_image_url": cover_image_url,
            "audio_src": audio_src,
        }
    except Exception as e:
        logger.error(f"audee.jpのHTML解析に失敗しました: {e}", exc_info=True)
        return None


def get_audio_info_bitfan(soup, logger):
    """bitfan.netのHTML(BeautifulSoupオブジェクト)から音声情報を取得する"""
    logger.info("bitfan.netのメタデータと音声URLを解析します...")
    try:
        program_name = soup.select_one("meta[property='og:site_name']")["content"]
        episode_title = soup.select_one("h1.p-clubArticle__name").get_text(strip=True)
        artist_name = program_name
        cover_image_url = soup.select_one("div.p-clubArticle__thumb img")["src"]

        # 音声タグからソースを取得 (iframeは展開済みと想定)
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
            logger.error("audioタグまたはsourceタグが見つかりませんでした。")
            return None

        return {
            "program_name": program_name,
            "episode_title": episode_title,
            "artist_name": artist_name,
            "cover_image_url": cover_image_url,
            "audio_src": audio_src,
        }
    except Exception as e:
        logger.error(f"bitfan.netのHTML解析に失敗しました: {e}", exc_info=True)
        return None

# --- メイン処理 ---

def download_audio_from_html(html_path, download_dir, logger, domain):
    """HTMLファイルから音声ファイルをダウンロードし、メタデータを付与する"""
    logger.info(f"ドメイン: {domain}")
    try:
        logger.info(f"ローカルHTMLファイルを読み込んでいます: {html_path}")
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # BeautifulSoupでHTMLを解析
        soup = BeautifulSoup(html_content, "lxml")

        # ドメインに基づいて処理を分岐
        audio_info = None
        if "audee.jp" in domain:
            audio_info = get_audio_info_audee(soup, logger)
        elif "bitfan.net" in domain:
            audio_info = get_audio_info_bitfan(soup, logger)
        else:
            logger.warning(f"未対応のドメインです: {domain}")
            return

        if not audio_info:
            logger.error("音声情報の取得に失敗しました。")
            return

        # --- ダウンロードとffmpeg処理 ---
        sanitized_program = MyPathHelper.sanitize_filepath(audio_info["program_name"])
        sanitized_episode = MyPathHelper.sanitize_filepath(audio_info["episode_title"])
        temp_filename = "temp_audio.mp3"
        final_filename = f"{sanitized_program}_{sanitized_episode}.mp3"
        temp_filepath = os.path.join(download_dir, temp_filename)
        final_filepath = os.path.join(download_dir, final_filename)

        logger.info(f"音声ファイルを一時ファイルとしてダウンロードしています: {temp_filepath}")
        response = requests.get(audio_info["audio_src"], stream=True)
        response.raise_for_status()
        with open(temp_filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info("ダウンロードが完了しました。")

        # --- ffmpeg処理 ---
        if audio_info["cover_image_url"]:
            temp_cover_path = os.path.join(download_dir, "temp_cover.jpg")
            logger.info(f"カバー画像をダウンロードしています: {temp_cover_path}")
            cover_res = requests.get(audio_info["cover_image_url"])
            with open(temp_cover_path, "wb") as f:
                f.write(cover_res.content)

            logger.info("ffmpegを使用してメタデータとカバー画像を埋め込んでいます...")
            ffmpeg_command = [
                "ffmpeg",
                "-i", temp_filepath,
                "-i", temp_cover_path,
                "-map", "0",
                "-map", "1",
                "-c", "copy",
                "-metadata", f"title={audio_info['episode_title']}",
                "-metadata", f"artist={audio_info['artist_name']}",
                "-metadata", f"album={audio_info['program_name']}",
                "-y", final_filepath,
            ]
            subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True)
            os.remove(temp_cover_path)
        else:
            logger.info("ffmpegを使用してメタデータを埋め込んでいます...")
            ffmpeg_command = [
                "ffmpeg",
                "-i", temp_filepath,
                "-c", "copy",
                "-metadata", f"title={audio_info['episode_title']}",
                "-metadata", f"artist={audio_info['artist_name']}",
                "-metadata", f"album={audio_info['program_name']}",
                "-y", final_filepath,
            ]
            subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True)

        os.remove(temp_filepath)
        logger.info(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")

    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}", exc_info=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="指定されたHTMLファイルから音声ファイルをダウンロードし、メタデータを付与します。"
    )
    parser.add_argument("html_path", help="対象のHTMLファイルのパス")
    parser.add_argument(
        "--download_dir",
        default=".",
        help="ダウンロード先のディレクトリ (デフォルト: カレントディレクトリ)",
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="HTMLファイルの取得元ドメイン (例: bitfan.net)",
    )
    args = parser.parse_args()

    # 入力パスの検証
    if not os.path.isfile(args.html_path):
        print(f"エラー: 指定されたファイルが見つかりません: {args.html_path}")
        exit(1)

    download_directory = MyPathHelper.complete_safe_path(args.download_dir)
    logger = MyLoggerHelper.setup_logger(__name__, download_directory)

    if not os.path.exists(download_directory):
        os.makedirs(download_directory)

    download_audio_from_html(
        args.html_path, download_directory, logger, args.domain
    )
