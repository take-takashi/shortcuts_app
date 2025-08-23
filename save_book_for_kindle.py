"""
# 設計図

## 本アプリの目的

kindleアプリで閲覧している本をページ送りをしながらスクリーンショットを撮影する。
スクリーンショットをPDFで1冊にまとめる。

## 注意点

私的利用のみで、NotebookLMに取り込ませて勉強に利用するため。

## 前提

- 本アプリはmacで動作させる。iOSは対応しない。
- pythonで動かす。

## パッケージ

```bash
% uv add PyAutoGUI==0.9.54
% uv add pillow==11.3.0
% uv add PyWinCtl==0.4.1 # macでwindowの情報を取得するため
```

## 処理内容

### STEP1. kindleアプリの情報を取得

- すでに起動しているkindleアプリのウィンドウを取得し、アクティブフォーカス状態にする。
- kindleアプリが起動していない場合はエラーで終了

### STEP2 スクリーンショットとページ送りの繰り返し

- kindleアプリのウィンドウをスクリーンショットを撮影し、所定のフォルダに連番想定のファイル名で画像を保存する。
- kindleアプリに対して、次のページに進むようにキーを送信する。
- キーの送信後、ページ送り動作が発生すると思われるので、1秒程度のスリープを実施。

上記の動作を最後のページまでループして実行する。

*** ※ kindleアプリは、すでに本を開いた状態である前提とする。 ***
*** 【相談：一旦解決】最後のページの検出はどうするべきか？（ループの停止条件） ***
-> （1）まずは「ユーザーが手動で停止する」こととする。
-> （2）1がうまくいったらページ数を指定できるようにする。
-> （3）2もできて、うまくいけそうなら画像比較を行い、画像の無変化を最後のページとする。

### STEP3 PDF化して保存

- フォルダに保存された連番のスクリーンショット画像を1つのPDFとして保存する。

"""

import argparse
import glob
import os
import sys
import time

import pyautogui
import pywinctl as pwc
from PIL import Image


def get_kindle_window():
    """Kindleアプリのウィンドウを取得する"""
    # Kindleアプリのウィンドウを取得
    windows = pwc.getWindowsWithTitle("Kindle")
    if not windows:
        print("Kindleアプリが起動していません。", file=sys.stderr)
        sys.exit(1)
    return windows[0]


def take_screenshots(window, pages=None, output_dir="screenshots"):
    """スクリーンショットを撮影し、ページ送りを繰り返す"""
    # TODO: 保存先をtemp用のディレクトリにできる？
    # 保存先ディレクトリを作成
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"'{output_dir}'ディレクトリを作成しました。")

    # Retinaディスプレイ対応: スケールファクターを計算
    # フルスクリーンショットのサイズ（物理ピクセル）を取得
    with pyautogui.screenshot() as s:
        screenshot_width, _ = s.size
    # 画面の論理サイズを取得
    screen_width, _ = pyautogui.size()
    # スケールファクターを計算（通常1.0 or 2.0）
    scale_factor = screenshot_width / screen_width

    try:
        i = 1
        while True:
            # ページ数指定がある場合、上限に達したらループを抜ける
            if pages and i > pages:
                print(f"\n指定された {pages} ページの撮影が完了しました。")
                break

            # スクリーンショットを撮影
            screenshot_path = os.path.join(output_dir, f"page_{i:04d}.png")

            # フルスクリーンで撮影
            full_screenshot = pyautogui.screenshot()

            # Kindleウィンドウの領域を計算（物理ピクセル）
            left = window.left * scale_factor
            top = window.top * scale_factor
            right = (window.left + window.width) * scale_factor
            bottom = (window.top + window.height) * scale_factor

            # 画像を切り抜く
            cropped_screenshot = full_screenshot.crop((left, top, right, bottom))

            # 画像を保存
            cropped_screenshot.save(screenshot_path)
            print(f"{screenshot_path} を保存しました。")

            # ページ送り
            pyautogui.press("right")
            print("ページ送りをしました。")

            i += 1
            # ページ送りのアニメーションなどを考慮して1秒待機
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n手動で停止されました。撮影処理を終了します。")

    return output_dir


def convert_images_to_pdf(image_dir, output_pdf="output.pdf"):
    """画像群をPDFに変換する"""
    # 画像ファイルの一覧を取得
    image_paths = sorted(glob.glob(os.path.join(image_dir, "*.png")))
    if not image_paths:
        print("画像ファイルが見つかりません。", file=sys.stderr)
        return

    print(f"{len(image_paths)}個の画像をPDFに変換します。")

    # Pillowで画像を開く
    images = [Image.open(p) for p in image_paths]

    # TODO: 保存先ディレクトリをコマンド引数で指定したい。
    # PDFとして保存
    images[0].save(
        output_pdf,
        save_all=True,
        append_images=images[1:],
        resolution=300.0,
    )
    # TODO: PDFのファイルサイズを200MBまでに収めたいが何かいい方法はあるか？
    print(f"PDFファイル '{output_pdf}' を作成しました。")
    # TODO: PDFの保存ができたらこれまでのスクリーンショットは削除したい。


def main():
    """メイン処理"""
    # コマンドライン引数の設定
    parser = argparse.ArgumentParser(description="Kindleの本を撮影してPDF化します。")
    parser.add_argument(
        "-p",
        "--pages",
        type=int,
        help="撮影するページ数を指定します。指定しない場合は手動停止です。",
    )
    args = parser.parse_args()

    # STEP1: Kindleアプリのウィンドウを取得し、アクティブにする
    kindle_window = get_kindle_window()
    kindle_window.activate()
    print(f"'{kindle_window.title}'をアクティブにしました。")
    print("left = ", kindle_window.left)
    print("top = ", kindle_window.top)
    print("width = ", kindle_window.width)
    print("height = ", kindle_window.height)

    if args.pages:
        print(f"{args.pages}ページの撮影を3秒後に開始します...")
    else:
        print("3秒後に撮影を開始します... (Ctrl+Cで停止)")
    time.sleep(3)

    # STEP2: スクリーンショットとページ送りの繰り返し
    screenshot_dir = take_screenshots(kindle_window, pages=args.pages)

    # STEP3: PDF化して保存
    if screenshot_dir:
        # ファイル名を本のタイトルから取得（ウィンドウタイトルから不要な部分を削除）
        book_title = kindle_window.title.replace(" - Kindle", "").strip()
        pdf_filename = f"{book_title}.pdf"
        convert_images_to_pdf(screenshot_dir, pdf_filename)


if __name__ == "__main__":
    main()
