import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def get_html_with_headless_browser(url: str) -> str:
    """
    指定されたURLをヘッドレスブラウザで開き、HTMLソースを取得します。
    JavaScriptによって動的に生成されるコンテンツも取得できます。

    Args:
        url (str): 取得したいページのURL。

    Returns:
        str: ページのHTMLソース。
    """
    options = Options()
    options.add_argument("--headless")  # ヘッドレスモードを有効にする
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
    )

    # webdriver_managerを使って自動的にchromedriverをダウンロード・管理
    service = Service(ChromeDriverManager().install())

    driver = None  # driver変数を初期化
    html_source = ""
    try:
        driver = webdriver.Chrome(service=service, options=options)
        print(f"ヘッドレスブラウザでURLを開いています: {url}")
        driver.get(url)

        # JavaScriptがコンテンツを読み込むのを待つ（秒数は適宜調整してください）
        print("コンテンツの読み込みを5秒間待機します...")
        time.sleep(5)

        html_source = driver.page_source
        print("HTMLソースの取得に成功しました。")

    except Exception as e:
        print(f"エラーが発生しました: {e}")
    finally:
        if driver:
            driver.quit()
            print("ブラウザを終了しました。")

    return html_source


if __name__ == "__main__":
    # 取得したいウェブページのURLを指定
    target_url = "https://www.yahoo.co.jp/"
    html = get_html_with_headless_browser(target_url)

    if html:
        # 取得したHTMLをファイルに保存する例
        output_filename = "yahoo_source.html"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"取得したHTMLソースを {output_filename} に保存しました。")
