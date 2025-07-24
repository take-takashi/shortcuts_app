import argparse
import json
import logging
import logging.config
import os

from AudioInfoExtractor import get_extractor

# 実行方法
# PYTHONPATH=$(pwd) python tools/extract_audio_info.py ./tests/private_data/test_audee_page_2audio.html --domain audee.jp


def main():
    parser = argparse.ArgumentParser(
        description="指定されたHTMLファイルから音声情報を抽出します。"
    )
    parser.add_argument("html_path", help="対象のHTMLファイルのパス")
    parser.add_argument(
        "--domain",
        required=True,
        help="HTMLファイルの取得元ドメイン (例: audee.jp, bitfan.net)",
    )
    args = parser.parse_args()

    # ロギング設定ファイルを読み込む
    with open(
        os.path.join(os.path.dirname(__file__), "..", "logging_config.json"), "r"
    ) as f:
        config = json.load(f)
    logging.config.dictConfig(config)
    logger = logging.getLogger(__name__)

    html_path = args.html_path
    domain = args.domain

    print(f"HTMLファイル: {html_path}")
    print(f"対象ドメイン: {domain}")

    try:
        if not os.path.exists(html_path):
            print(f"エラー: 指定されたファイルが見つかりません: {html_path}")
            return

        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        extractor = get_extractor(domain, logger)

        if extractor:
            audio_info_list = extractor.get_audio_info(html_content)
            if audio_info_list:
                print("\n--- 抽出された情報 ---")
                for i, audio_info in enumerate(audio_info_list):
                    print(f"\n--- 音声 {i + 1} ---")
                    print(f"  番組名: {audio_info.program_name}")
                    print(f"  エピソードタイトル: {audio_info.episode_title}")
                    print(f"  パーソナリティ名: {audio_info.artist_name}")
                    print(f"  カバー画像URL: {audio_info.cover_image_url}")
                    print(f"  音声URL: {audio_info.audio_src}")
            else:
                print("\n音声情報の抽出に失敗しました。")
        else:
            print(f"\n未対応のドメインです: {domain}")

    except Exception as e:
        print(f"エラーが発生しました: {e}")


if __name__ == "__main__":
    main()
