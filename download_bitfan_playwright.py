import argparse
import os
import re
import subprocess
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from login_bitfan import login_bitfan

def sanitize_filename(filename):
    """ファイル名として使えない文字を全角アンダースコアに置換する"""
    filename = re.sub(r"^vol\.\d+\s", "", filename)
    return re.sub(r'[\\/:*?"<>|\s]', "＿", filename)

def download_audio_from_bitfan_playwright(url, download_dir="."):
    """
    bitfan.jpのページから音声ファイルをダウンロードし、メタデータを付与する (Playwright版)
    """
    with sync_playwright() as p:
        browser = None
        try:
            STORAGE_STATE_PATH = "bitfan_storage_state.json"
            if not os.path.exists(STORAGE_STATE_PATH):
                print("ログイン情報が見つかりません。ログインプロセスを開始します。")
                login_bitfan()
                if not os.path.exists(STORAGE_STATE_PATH):
                    print("ログインに失敗したか、ログイン情報が保存されませんでした。処理を中断します。")
                    return

            print("Playwrightでブラウザを起動しています...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=STORAGE_STATE_PATH)
            page = context.new_page()
            print(f"ページにアクセスしています: {url}")
            page.goto(url, wait_until="load")

            # --- メタデータ情報の取得 ---
            print("メタデータ情報を取得しています...")
            program_name = page.locator("meta[property='og:site_name']").get_attribute("content")
            episode_title = page.locator("h1.p-clubArticle__name").inner_text()
            artist_name = program_name
            cover_image_url = page.locator("div.p-clubArticle__thumb img").get_attribute("src")

            print(f"  番組名: {program_name}")
            print(f"  エピソード名: {episode_title}")
            print(f"  カバー画像URL: {cover_image_url}")

            # --- 音声ソースのURLを取得 ---
            print("音声プレーヤーのiframeを探しています...")
            sound_iframe_locator = page.locator(".sound-content")
            sound_frame = sound_iframe_locator.frame_locator(":scope")
            
            print("音声ファイルのURLを探しています...")
            audio_locator = sound_frame.locator("audio")
            audio_src = audio_locator.get_attribute("src")
            if not audio_src:
                audio_src = sound_frame.locator("audio > source").get_attribute("src")

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

            print(
                f"音声ファイルを一時ファイルとしてダウンロードしています: {temp_filepath}"
            )
            
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
                    "-y",
                    final_filepath,
                ]
                result = subprocess.run(
                    ffmpeg_command,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                )
                print(f"ffmpeg stdout: {result.stdout}")
                print(f"ffmpeg stderr: {result.stderr}")
                print(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")
                os.remove(temp_cover_path)
            else:
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
                    ffmpeg_command,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                )
                print(f"ffmpeg stdout: {result.stdout}")
                print(f"ffmpeg stderr: {result.stderr}")
                print(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")

            os.remove(temp_filepath)

            
            
        except PlaywrightTimeoutError:
            print("タイムアウトエラー: ページの読み込みまたは要素の取得に時間がかかりすぎました。")
        except Exception as e:
            print(f"予期せぬエラーが発生しました: {e}")
        finally:
            if browser:
                print("ブラウザを閉じています...")
                browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="bitfan.jpから音声ファイルをダウンロードします。(Playwright版)"
    )
    parser.add_argument("url", help="対象のbitfanページのURL")
    parser.add_argument(
        "--download_dir",
        default=".",
        help="ダウンロード先のディレクトリ (デフォルト: カレントディレクトリ)",
    )
    args = parser.parse_args()
    download_directory = os.path.abspath(args.download_dir)
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)
    
    download_audio_from_bitfan_playwright(args.url, download_directory)