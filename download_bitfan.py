import argparse
import os
import re
import subprocess
import time

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchWindowException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

def sanitize_filename(filename):
    """ファイル名として使えない文字を全角アンダースコアに置換する"""
    filename = re.sub(r"^vol\.\d+\s", "", filename)
    return re.sub(r'[\\/:*?"<>|\s]', "＿", filename)


def download_audio_from_bitfan(url, download_dir="."):
    """
    bitfan.jpのページから音声ファイルをダウンロードし、メタデータを付与する
    """
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    driver = None
    original_window = None
    try:
        print("既存のChromeセッションに接続しています...")
        driver = webdriver.Chrome(options=options)
        print("接続に成功しました。")

        original_window = driver.current_window_handle
        print("新しいタブでページを開いています...")
        driver.switch_to.new_window('tab')
        driver.get(url)

        # --- メタデータ情報の取得 ---
        print("メタデータ情報を取得しています...")
        wait = WebDriverWait(driver, 15)
        try:
            program_name = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "meta[property='og:site_name']"))).get_attribute("content")
            episode_title = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.p-clubArticle__name"))).text
            artist_name = program_name
            cover_image_url = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.p-clubArticle__thumb img"))).get_attribute("src")
            print(f"  番組名: {program_name}")
            print(f"  エピソード名: {episode_title}")
            print(f"  カバー画像URL: {cover_image_url}")
        except Exception as e:
            print(f"エラー: メタデータ情報の取得に失敗しました - {e}")
            program_name, episode_title, artist_name, cover_image_url = "Unknown Program", "Unknown Episode", "Unknown Artist", None

        # --- 音声ソースのURLを取得 ---
        print("音声プレーヤーのiframeに切り替えます...")
        sound_iframe = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "sound-content")))
        driver.switch_to.frame(sound_iframe)

        print("音声ファイルのURLを探しています...")
        audio_src = None
        try:
            audio_element = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "audio")))
            audio_src = audio_element.get_attribute("src")
            if not audio_src:
                source_element = audio_element.find_element(By.TAG_NAME, "source")
                audio_src = source_element.get_attribute("src")
        except TimeoutException:
            print("エラー: 音声プレーヤーの読み込みがタイムアウトしました。")

        driver.switch_to.default_content()

        if not audio_src:
            print("エラー: 音声ファイルのURLが見つかりませんでした。")
            return

        print(f"音声ファイルのURLを取得しました: {audio_src}")

        # --- ファイル名の生成とダウンロード ---
        sanitized_program = sanitize_filename(program_name)
        sanitized_episode = sanitize_filename(episode_title)
        temp_filename = "temp_audio.mp3"
        final_filename = f"{sanitized_program}_{sanitized_episode}.mp3"
        temp_filepath = os.path.join(download_dir, temp_filename)
        final_filepath = os.path.join(download_dir, final_filename)

        print(f"音声ファイルを一時ファイルとしてダウンロードしています: {temp_filepath}")
        response = requests.get(audio_src, stream=True)
        response.raise_for_status()

        with open(temp_filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print("ダウンロードが完了しました。")

        # --- ffmpeg処理 ---
        if cover_image_url:
            temp_cover_path = os.path.join(download_dir, "temp_cover.jpg")
            print(f"カバー画像をダウンロードしています: {temp_cover_path}")
            cover_res = requests.get(cover_image_url)
            with open(temp_cover_path, "wb") as f:
                f.write(cover_res.content)

            print("ffmpegを使用してメタデータとカバー画像を埋め込んでいます...")
            ffmpeg_command = [
                "ffmpeg", "-i", temp_filepath, "-i", temp_cover_path,
                "-map", "0", "-map", "1", "-c", "copy",
                "-metadata", f"title={episode_title}",
                "-metadata", f"artist={artist_name}",
                "-metadata", f"album={program_name}",
                "-y", final_filepath,
            ]
            result = subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            print(f"ffmpeg stdout: {result.stdout}")
            print(f"ffmpeg stderr: {result.stderr}")
            print(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")
            os.remove(temp_cover_path)
        else:
            print("ffmpegを使用してメタデータを埋め込んでいます...")
            ffmpeg_command = [
                "ffmpeg", "-i", temp_filepath, "-c", "copy",
                "-metadata", f"title={episode_title}",
                "-metadata", f"artist={artist_name}",
                "-metadata", f"album={program_name}",
                "-y", final_filepath,
            ]
            result = subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            print(f"ffmpeg stdout: {result.stdout}")
            print(f"ffmpeg stderr: {result.stderr}")
            print(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")

        os.remove(temp_filepath)

    except NoSuchWindowException:
        print("エラー: ブラウザのタブが閉じられたため、処理を続行できませんでした。")
    except TimeoutException as e:
        print(f"タイムアウトエラー: 処理中に問題が発生しました。 - {e}")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
    finally:
        if driver:
            if len(driver.window_handles) > 1 and original_window:
                 print("現在のタブを閉じています...")
                 driver.close()
                 driver.switch_to.window(original_window)
            print("WebDriverのセッションを終了します。ブラウザは開いたままです。")
            driver.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="bitfan.jpから音声ファイルをダウンロードします。")
    parser.add_argument("url", help="対象のbitfanページのURL")
    parser.add_argument("--download_dir", default=".", help="ダウンロード先のディレクトリ (デフォルト: カレントディレクトリ)")
    args = parser.parse_args()
    download_directory = os.path.abspath(args.download_dir)
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)
    download_audio_from_bitfan(args.url, download_directory)
