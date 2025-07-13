import os
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

def download_audio_from_audee(url, download_dir="."):
    """
    audee.jpのページから音声ファイルをダウンロードする (Chromeを使用)
    """
    # ブラウザのオプションを設定
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

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
        wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "btn-play"))
        )
        print("プレイヤーの読み込みが完了しました。")

        # JavaScriptを実行してplaylist変数を取得
        print("JavaScriptからプレイリスト情報を取得します...")
        playlist_data = driver.execute_script("return window.playlist;")
        
        if not playlist_data or not isinstance(playlist_data, list) or len(playlist_data) == 0:
            print("エラー: プレイリスト情報が見つかりませんでした。")
            return

        # 音声ファイルのURLを取得
        audio_src = playlist_data[0].get('voice')
        if not audio_src:
            print("エラー: 音声ファイルのURLが見つかりませんでした。")
            return

        print(f"音声ファイルのURLを取得しました: {audio_src}")

        # ファイルをダウンロード
        print("音声ファイルをダウンロードしています...")
        response = requests.get(audio_src, stream=True)
        response.raise_for_status() # エラーがあれば例外を発生させる

        # ファイル名を決定 (URLの最後の部分を使用)
        file_name = os.path.basename(audio_src.split('?')[0])
        if not file_name:
            file_name = "downloaded_audio.mp3" # デフォルトファイル名

        download_path = os.path.join(download_dir, file_name)

        with open(download_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f"ダウンロードが完了しました: {download_path}")

    except TimeoutException:
        print("タイムアウトエラー: 指定された音声コンテンツが時間内に見つかりませんでした。")
        # デバッグ用にHTMLを保存
        html_path = os.path.join(download_dir, "error_page.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"現在のページのHTMLを {html_path} に保存しました。")
    except requests.exceptions.RequestException as e:
        print(f"ダウンロードエラー: {e}")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
    finally:
        # ブラウザを閉じる
        print("ブラウザを閉じています...")
        driver.quit()

if __name__ == '__main__':
    # 対象のURL
    target_url = "https://audee.jp/voice/show/15492"
    
    # ダウンロード先のディレクトリ (このスクリプトと同じ場所)
    download_directory = os.path.dirname(os.path.abspath(__file__))
    
    download_audio_from_audee(target_url, download_directory)