import argparse
import os
import re
import subprocess

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def sanitize_filename(filename):
    """ファイル名として使えない文字を全角アンダースコアに置換する"""
    # 先頭の "vol.XX " のような部分を削除
    filename = re.sub(r"^vol\.\d+\s", "", filename)
    return re.sub(r'[\\/:*?"<>|\s]', "＿", filename)


def download_audio_from_audee(url, download_dir="."):
    """
    audee.jpのページから音声ファイルをダウンロードし、メタデータを付与する
    """
    # ブラウザのオプションを設定
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # WebDriverを初期化 (SeleniumManagerが適切なドライバを自動管理)
    print("WebDriverを初期化しています...")
    driver = webdriver.Chrome(options=options)
    print("WebDriverの初期化が完了しました。")

    try:
        # ページを開く
        print(f"ページを開いています: {url}")
        driver.get(url)

        # プレイヤーの再生ボタンが表示されるまで最大30秒待機
        print("プレイヤーの読み込みを待機しています...")
        wait = WebDriverWait(driver, 30)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "btn-play")))
        print("プレイヤーの読み込みが完了しました。")

        # --- メタデータ情報の取得 ---
        print("メタデータ情報を取得しています...")
        try:
            program_name = driver.find_element(
                By.CSS_SELECTOR, "h2.box-program-ttl"
            ).text
            episode_title = driver.find_element(
                By.CSS_SELECTOR, "h3.ttl-cmn-detail .ttl-inner"
            ).text
            # パーソナリティ名は番組名で代用
            artist_name = program_name
            cover_image_url = driver.find_element(
                By.CSS_SELECTOR, "div.box-visual img"
            ).get_attribute("src")
            print(f"  番組名: {program_name}")
            print(f"  エピソード名: {episode_title}")
            print(f"  カバー画像URL: {cover_image_url}")
        except Exception as e:
            print(f"エラー: メタデータ情報の取得に失敗しました - {e}")
            # 失敗した場合はデフォルト値を使う
            program_name = "Unknown Program"
            episode_title = "Unknown Episode"
            artist_name = "Unknown Artist"
            cover_image_url = None

        # JavaScriptを実行してplaylist変数を取得
        print("JavaScriptからプレイリスト情報を取得します...")
        playlist_data = driver.execute_script("return window.playlist;")

        if (
            not playlist_data
            or not isinstance(playlist_data, list)
            or len(playlist_data) == 0
        ):
            print("エラー: プレイリスト情報が見つかりませんでした。")
            return

        # 音声ファイルのURLを取得
        audio_src = playlist_data[0].get("voice")
        if not audio_src:
            print("エラー: 音声ファイルのURLが見つかりませんでした。")
            return

        print(f"音声ファイルのURLを取得しました: {audio_src}")

        # --- ファイル名の生成 ---
        sanitized_program = sanitize_filename(program_name)
        sanitized_episode = sanitize_filename(episode_title)
        temp_filename = "temp_audio.mp3"
        final_filename = f"{sanitized_program}_{sanitized_episode}.mp3"
        temp_filepath = os.path.join(download_dir, temp_filename)
        final_filepath = os.path.join(download_dir, final_filename)

        # ファイルをダウンロード
        print(
            f"音声ファイルを一時ファイルとしてダウンロードしています: {temp_filepath}"
        )
        response = requests.get(audio_src, stream=True)
        response.raise_for_status()  # エラーがあれば例外を発生させる

        with open(temp_filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print("ダウンロードが完了しました。")

        # --- ffmpeg処理 ---
        if cover_image_url:
            # カバー画像をダウンロード
            temp_cover_path = os.path.join(download_dir, "temp_cover.jpg")
            print(f"カバー画像をダウンロードしています: {temp_cover_path}")
            cover_res = requests.get(cover_image_url)
            with open(temp_cover_path, "wb") as f:
                f.write(cover_res.content)

            # ffmpegコマンドを組み立て
            print("ffmpegを使用してメタデータとカバー画像を埋め込んでいます...")
            ffmpeg_command = [
                "ffmpeg",
                "-i",
                temp_filepath,
                "-i",
                temp_cover_path,
                "-map",
                "0",
                "-map",
                "1",
                "-c",
                "copy",
                "-metadata",
                f"title={episode_title}",
                "-metadata",
                f"artist={artist_name}",
                "-metadata",
                f"album={program_name}",
                "-y",  # 既存ファイルを上書き
                final_filepath,
            ]
            result = subprocess.run(
                ffmpeg_command, check=True, capture_output=True, text=True
            )
            print(f"ffmpeg stdout: {result.stdout}")
            print(f"ffmpeg stderr: {result.stderr}")
            print(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")

            # 一時ファイルを削除
            os.remove(temp_cover_path)
        else:
            # カバーがない場合はメタデータのみ付与
            print("ffmpegを使用してメタデータを埋め込んでいます...")
            ffmpeg_command = [
                "ffmpeg",
                "-i",
                temp_filepath,
                "-c",
                "copy",
                "-metadata",
                f"title={episode_title}",
                "-metadata",
                f"artist={artist_name}",
                "-metadata",
                f"album={program_name}",
                "-y",
                final_filepath,
            ]
            result = subprocess.run(
                ffmpeg_command, check=True, capture_output=True, text=True
            )
            print(f"ffmpeg stdout: {result.stdout}")
            print(f"ffmpeg stderr: {result.stderr}")
            print(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")

        # 一時音声ファイルを削除
        os.remove(temp_filepath)

    except TimeoutException:
        print(
            "タイムアウトエラー: 指定された音声コンテンツが時間内に見つかりませんでした。"
        )
        # デバッグ用にHTMLを保存
        html_path = os.path.join(download_dir, "error_page.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"現在のページのHTMLを {html_path} に保存しました。")
    except requests.exceptions.RequestException as e:
        print(f"ダウンロードエラー: {e}")
    except subprocess.CalledProcessError as e:
        print("ffmpegの実行に失敗しました。")
        print(f"ffmpeg stderr: {e.stderr}")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
    finally:
        # ブラウザを閉じる
        print("ブラウザを閉じています...")
        driver.quit()


if __name__ == "__main__":
    # コマンドライン引数の設定
    parser = argparse.ArgumentParser(
        description="audee.jpから音声ファイルをダウンロードします。"
    )
    parser.add_argument("url", help="対象のAuDeeページのURL")
    parser.add_argument(
        "--download_dir",
        default=".",
        help="ダウンロード先のディレクトリ (デフォルト: カレントディレクトリ)",
    )
    args = parser.parse_args()

    # 絶対パスに変換
    download_directory = os.path.abspath(args.download_dir)

    # ディレクトリが存在しない場合は作成
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)

    download_audio_from_audee(args.url, download_directory)
