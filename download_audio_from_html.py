import argparse
import os

import requests

from AudioInfoExtractor import get_extractor
from MyFfmpegHelper.my_ffmpeg_helper import FfmpegMetadata, MyFfmpegHelper
from MyLoggerHelper.my_logger_helper import MyLoggerHelper
from MyPathHelper.my_path_helper import MyPathHelper

# --- メイン処理 ---


def download_audio_from_html(html_path, domain, download_dir, *, logger):
    """HTMLファイルから音声ファイルをダウンロードし、メタデータを付与する"""
    logger.info(f"HTMLファイルのパス: {html_path}")
    logger.info(f"ドメイン: {domain}")
    logger.info(f"ダウンロード先ディレクトリ: {download_dir}")

    try:
        logger.info(f"ローカルHTMLファイルを読み込んでいます: {html_path}")
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # ドメインに基づいて適切なExtractorを取得
        extractor = get_extractor(domain, logger=logger)
        if not extractor:
            logger.warning(f"未対応のドメインです: {domain}")
            return

        # 音声情報を取得
        audio_info_list = extractor.get_audio_info(html_content)

        if not audio_info_list:
            logger.error("音声情報の取得に失敗しました。")
            return

        for audio_info in audio_info_list:
            # --- ダウンロードとffmpeg処理 ---
            sanitized_program = MyPathHelper.sanitize_filepath(audio_info.program_name)
            sanitized_episode = MyPathHelper.sanitize_filepath(audio_info.episode_title)
            temp_filename = "temp_audio.mp3"
            final_filename = f"{sanitized_program}_{sanitized_episode}.mp3"
            temp_filepath = os.path.join(download_dir, temp_filename)
            final_filepath = os.path.join(download_dir, final_filename)

            logger.info(
                f"音声ファイルを一時ファイルとしてダウンロードしています: {temp_filepath}"
            )
            response = requests.get(audio_info.audio_src, stream=True)
            response.raise_for_status()
            with open(temp_filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("ダウンロードが完了しました。")

            # --- ffmpeg処理 ---
            metadata: FfmpegMetadata = {
                "title": audio_info.episode_title,
                "artist": audio_info.artist_name,
                "album": audio_info.program_name,
            }

            temp_cover_path = None
            if audio_info.cover_image_url:
                temp_cover_path = os.path.join(download_dir, "temp_cover.jpg")
                logger.info(f"カバー画像をダウンロードしています: {temp_cover_path}")
                cover_res = requests.get(audio_info.cover_image_url)
                with open(temp_cover_path, "wb") as f:
                    f.write(cover_res.content)

            MyFfmpegHelper.embed_metadata(
                input_path=temp_filepath,
                output_path=final_filepath,
                metadata=metadata,
                cover_path=temp_cover_path,
                logger=logger,
            )

            # 一時ファイルを削除
            if temp_cover_path and os.path.exists(temp_cover_path):
                os.remove(temp_cover_path)
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)

            logger.info(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")

    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}", exc_info=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="指定されたHTMLファイルから音声ファイルをダウンロードし、メタデータを付与します。"
    )
    parser.add_argument("--html", required=True, help="対象のHTMLファイルのパス")
    parser.add_argument(
        "--domain",
        required=True,
        help="HTMLファイルの取得元ドメイン (例: audee.jp)",
    )
    parser.add_argument(
        "--download_dir",
        default=".",
        help="ダウンロード先のディレクトリ (デフォルト: カレントディレクトリ)",
    )
    args = parser.parse_args()

    # 入力パスの検証
    if not os.path.isfile(args.html):
        print(f"エラー: 指定されたファイルが見つかりません: {args.html}")
        exit(1)

    # ダウンロードするディレクトリを安全に展開する
    download_directory = MyPathHelper.complete_safe_path(args.download_dir)
    # ディレクトリがなければ作成する
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)

    # loggerを作成
    logger = MyLoggerHelper.setup_logger(__name__, download_directory)

    download_audio_from_html(args.html, args.domain, download_directory, logger=logger)

    exit(0)
