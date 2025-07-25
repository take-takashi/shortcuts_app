import argparse
import os
import re
import subprocess

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def sanitize_filename(filename):
    """ファイル名として使えない文字を全角アンダースコアに置換する"""
    # 先頭の "vol.XX " のような部分を削除
    filename = re.sub(r"^vol\.\d+\s", "", filename)
    return re.sub(r'[\\/:*?"<>|\s]', "＿", filename)


def download_audio_from_audee_playwright(url, download_dir="."):
    """
    audee.jpのページから音声ファイルをダウンロードし、メタデータを付与する (Playwright版)
    """
    with sync_playwright() as p:
        browser = None
        try:
            print("Playwrightでブラウザを起動しています...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            print(f"ページにアクセスしています: {url}")
            page.goto(url, wait_until="load")

            # --- メタデータ情報の取得 ---
            print("メタデータ情報を取得しています...")
            try:
                program_name = page.locator("h2.box-program-ttl").first.inner_text()
                episode_title_base = page.locator("h3.ttl-cmn-detail .ttl-inner").first.inner_text()
                artist_name = program_name
                cover_image_url = page.locator("div.box-visual img").first.get_attribute("src")
                print(f"  番組名: {program_name}")
                print(f"  エピソード名（ベース）: {episode_title_base}")
                print(f"  カバー画像URL: {cover_image_url}")
            except Exception as e:
                print(f"エラー: メタデータ情報の取得に失敗しました - {e}")
                program_name = "Unknown Program"
                episode_title_base = "Unknown Episode"
                artist_name = "Unknown Artist"
                cover_image_url = None

            # JavaScriptを実行してplaylist変数を取得
            print("JavaScriptからプレイリスト情報を取得します...")
            playlist_data = page.evaluate("window.playlist")

            if not playlist_data or not isinstance(playlist_data, list) or len(playlist_data) == 0:
                print("エラー: プレイリスト情報が見つかりませんでした。")
                return

            # --- 各音声ファイルをダウンロード ---
            for i, audio_data in enumerate(playlist_data):
                audio_src = audio_data.get("voice")
                if not audio_src:
                    print(f"警告: {i+1}番目の音声ファイルのURLが見つかりませんでした。スキップします。")
                    continue

                print(f"{i+1}番目の音声ファイルを処理します: {audio_src}")

                # --- ファイル名の生成 ---
                # 複数ファイルがある場合は、エピソード名に連番を付与
                episode_title = f"{episode_title_base}_{i+1}" if len(playlist_data) > 1 else episode_title_base
                sanitized_program = sanitize_filename(program_name)
                sanitized_episode = sanitize_filename(episode_title)
                temp_filename = f"temp_audio_{i}.mp3"
                final_filename = f"{sanitized_program}_{sanitized_episode}.mp3"
                temp_filepath = os.path.join(download_dir, temp_filename)
                final_filepath = os.path.join(download_dir, final_filename)

                # ファイルをダウンロード
                print(f"音声ファイルを一時ファイルとしてダウンロードしています: {temp_filepath}")
                response = requests.get(audio_src, stream=True)
                response.raise_for_status()

                with open(temp_filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print("ダウンロードが完了しました。")

                # --- ffmpeg処理 ---
                if cover_image_url:
                    temp_cover_path = os.path.join(download_dir, f"temp_cover_{i}.jpg")
                    print(f"カバー画像をダウンロードしています: {temp_cover_path}")
                    cover_res = requests.get(cover_image_url)
                    with open(temp_cover_path, "wb") as f:
                        f.write(cover_res.content)

                    print("ffmpegを使用してメタデータとカバー画像を埋め込んでいます...")
                    ffmpeg_command = [
                        "ffmpeg",
                        "-i", temp_filepath,
                        "-i", temp_cover_path,
                        "-map", "0",
                        "-map", "1",
                        "-c", "copy",
                        "-metadata", f"title={episode_title}",
                        "-metadata", f"artist={artist_name}",
                        "-metadata", f"album={program_name}",
                        "-y",
                        final_filepath,
                    ]
                    result = subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    print(f"ffmpeg stdout: {result.stdout}")
                    print(f"ffmpeg stderr: {result.stderr}")
                    print(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")
                    os.remove(temp_cover_path)
                else:
                    print("ffmpegを使用してメタデータを埋め込んでいます...")
                    ffmpeg_command = [
                        "ffmpeg",
                        "-i", temp_filepath,
                        "-c", "copy",
                        "-metadata", f"title={episode_title}",
                        "-metadata", f"artist={artist_name}",
                        "-metadata", f"album={program_name}",
                        "-y",
                        final_filepath,
                    ]
                    result = subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    print(f"ffmpeg stdout: {result.stdout}")
                    print(f"ffmpeg stderr: {result.stderr}")
                    print(f"処理が完了し、最終ファイルを保存しました: {final_filepath}")

                os.remove(temp_filepath)
                print("-" * 20)

        except PlaywrightTimeoutError:
            print("タイムアウトエラー: ページの読み込みまたは要素の取得に時間がかかりすぎました。")
            # デバッグ用にHTMLを保存
            html_path = os.path.join(download_dir, "error_page.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"現在のページのHTMLを {html_path} に保存しました。")
        except requests.exceptions.RequestException as e:
            print(f"ダウンロードエラー: {e}")
        except subprocess.CalledProcessError as e:
            print("ffmpegの実行に失敗しました。")
            print(f"ffmpeg stderr: {e.stderr}")
        except Exception as e:
            print(f"予期せぬエラーが発生しました: {e}")
        finally:
            if browser:
                print("ブラウザを閉じています...")
                browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="audee.jpから音声ファイルをダウンロードします。(Playwright版)")
    parser.add_argument("url", help="対象のAuDeeページのURL")
    parser.add_argument(
        "--download_dir",
        default=".",
        help="ダウンロード先のディレクトリ (デフォルト: カレントディレクトリ)",
    )
    args = parser.parse_args()

    download_directory = os.path.abspath(args.download_dir)
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)

    download_audio_from_audee_playwright(args.url, download_directory)
