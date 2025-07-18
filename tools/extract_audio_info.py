import argparse
import os
from unittest.mock import Mock  # ロガーのモック用

from bs4 import BeautifulSoup

from AudioInfoExtractor import get_extractor


def main():
    parser = argparse.ArgumentParser(
        description="指定されたHTMLファイルから音声情報を抽出し、表示します。"
    )
    parser.add_argument("html_path", help="対象のHTMLファイルのパス")
    parser.add_argument(
        "--domain",
        required=True,
        help="HTMLファイルの取得元ドメイン (例: audee.jp, bitfan.net)",
    )
    args = parser.parse_args()

    html_path = args.html_path
    domain = args.domain

    # ダミーロガーを作成
    logger = Mock()

    print(f"HTMLファイル: {html_path}")
    print(f"対象ドメイン: {domain}")

    try:
        if not os.path.exists(html_path):
            print(f"エラー: 指定されたファイルが見つかりません: {html_path}")
            return

        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, "lxml")

        extractor = get_extractor(domain, logger)

        if extractor:
            audio_info = extractor.get_audio_info(soup)
            if audio_info:
                print("\n--- 抽出された情報 ---")
                print(f"番組名: {audio_info.program_name}")
                print(f"エピソードタイトル: {audio_info.episode_title}")
                print(f"パーソナリティ名: {audio_info.artist_name}")
                print(f"カバー画像URL: {audio_info.cover_image_url}")
                print(f"音声URL: {audio_info.audio_src}")
            else:
                print("\n音声情報の抽出に失敗しました。")
        else:
            print(f"\n未対応のドメインです: {domain}")

    except Exception as e:
        print(f"エラーが発生しました: {e}")


if __name__ == "__main__":
    main()
