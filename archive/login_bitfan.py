from playwright.sync_api import sync_playwright

LOGIN_URL = "https://bitfan.id/users/sign_in"
STORAGE_STATE_PATH = "bitfan_storage_state.json"


def login_bitfan():
    with sync_playwright() as p:
        print("ブラウザを起動しています... (ログインプロセスを確認できます)")
        browser = p.chromium.launch(
            headless=False
        )  # ヘッドレスをFalseにしてブラウザを表示
        page = browser.new_page()

        print(f"ログインページにアクセスしています: {LOGIN_URL}")
        page.goto(LOGIN_URL)

        # ユーザーに手動でのログインを促す
        print("ブラウザが開きました。bitfan.jpに手動でログインしてください。")
        print("ログイン後、このターミナルに戻り、Enterキーを押してください。")

        input("ログインが完了したらEnterキーを押してください...")

        # ログイン後の状態を保存
        print(f"ログイン状態を {STORAGE_STATE_PATH} に保存しています...")
        page.context.storage_state(path=STORAGE_STATE_PATH)
        print("ログイン状態が保存されました。")

        browser.close()
        print("ブラウザを閉じました。")


if __name__ == "__main__":
    login_bitfan()
