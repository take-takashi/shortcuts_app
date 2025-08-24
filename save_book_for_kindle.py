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

## TODO

- テストの充実

"""

import argparse
import glob
import io
import os
import sys
import tempfile
import time

import pyautogui
import pywinctl as pwc
from PIL import Image, ImageChops


def get_kindle_window():
    """Kindleアプリのウィンドウを取得する"""
    # Kindleアプリのウィンドウを取得
    windows = pwc.getWindowsWithTitle("Kindle")
    if not windows:
        print("Kindleアプリが起動していません。", file=sys.stderr)
        sys.exit(1)
    return windows[0]


def save_debug_images(i, previous_screenshot, cropped_screenshot, diff):
    """画像比較に失敗した際にデバッグ用の画像を保存する"""
    debug_dir = "debug_images"
    os.makedirs(debug_dir, exist_ok=True)
    # RGBモードに変換してから保存
    previous_screenshot.convert("RGB").save(
        os.path.join(debug_dir, f"page_{i - 1}_previous.png")
    )
    cropped_screenshot.convert("RGB").save(
        os.path.join(debug_dir, f"page_{i}_current.png")
    )
    diff.save(os.path.join(debug_dir, f"page_{i}_diff.png"))
    print(f"デバッグ用の画像を {debug_dir} に保存しました。")


def take_screenshots(window, output_dir, pages=None, auto_stop=False):
    """スクリーンショットを撮影し、ページ送りを繰り返す"""
    # Retinaディスプレイ対応: スケールファクターを計算
    # フルスクリーンショットのサイズ（物理ピクセル）を取得
    with pyautogui.screenshot() as s:
        screenshot_width, _ = s.size
    # 画面の論理サイズを取得
    screen_width, _ = pyautogui.size()
    # スケールファクターを計算（通常1.0 or 2.0）
    scale_factor = screenshot_width / screen_width

    previous_screenshot = None

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

            # 画像比較による自動停止処理
            if auto_stop and previous_screenshot:
                # 比較前に両方の画像をRGBモードに変換してアルファチャンネルを削除
                prev_rgb = previous_screenshot.convert("RGB")
                curr_rgb = cropped_screenshot.convert("RGB")

                # 差分を計算
                diff = ImageChops.difference(prev_rgb, curr_rgb)
                # 差分がなければ（画像が同じなら）ループを抜ける
                if diff.getbbox() is None:
                    print(
                        "\n前のページと同じ画像のため、最終ページと判断して停止します。"
                    )
                    # デバッグが必要な場合は以下の行のコメントを解除
                    # save_debug_images(i, previous_screenshot, cropped_screenshot, diff)
                    break  # このループで撮影した画像は保存せずに終了

            # 画像を保存
            cropped_screenshot.save(screenshot_path)
            print(f"{screenshot_path} を保存しました。")

            # 現在の画像を次の比較のために保持
            previous_screenshot = cropped_screenshot.copy()

            # ページ送り
            pyautogui.press("right")
            print("ページ送りをしました。")

            i += 1
            # ページ送りのアニメーションなどを考慮して1秒待機
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n手動で停止されました。撮影処理を終了します。")


def convert_images_to_pdf(image_dir, output_pdf="output.pdf", quality="high"):
    """画像群をPDFに変換する"""
    # 画像ファイルの一覧を取得
    image_paths = sorted(glob.glob(os.path.join(image_dir, "*.png")))
    if not image_paths:
        print("画像ファイルが見つかりません。", file=sys.stderr)
        return

    print(f"{len(image_paths)}個の画像をPDFに変換します。(画質: {quality})")

    # Pillowで画像を開く
    pil_images = [Image.open(p) for p in image_paths]

    # high以外の場合はJPEGに変換して画質を落とす
    if quality != "high":
        jpeg_quality = {"medium": 85, "low": 75}[quality]

        images_to_save = []
        for img in pil_images:
            # PNGにアルファチャンネルがある場合、RGBに変換しないとJPEG保存でエラーになる
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # メモリ上でJPEGに変換し、再度読み込む
            buffer = io.BytesIO()
            img.save(buffer, "JPEG", quality=jpeg_quality)
            buffer.seek(0)
            jpeg_image = Image.open(buffer)
            images_to_save.append(jpeg_image)

        pil_images = images_to_save

    # PDFとして保存
    pil_images[0].save(
        output_pdf,
        save_all=True,
        append_images=pil_images[1:],
        resolution=300.0,
    )
    print(f"PDFファイル '{output_pdf}' を作成しました。")


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
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=".",
        help="PDFの出力先ディレクトリを指定します。デフォルトはカレントディレクトリです。",
    )
    parser.add_argument(
        "--auto-stop",
        action="store_true",
        help="ページの最後に到達した際に自動で撮影を停止します。",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=str,
        default="high",
        choices=["high", "medium", "low"],
        help="出力PDFの画質を指定します。high, medium, lowから選択。デフォルトはhigh。",
    )
    args = parser.parse_args()

    # STEP1: Kindleアプリのウィンドウを取得し、アクティブにする
    kindle_window = get_kindle_window()

    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"一時ディレクトリ '{temp_dir}' を作成しました。")

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
        take_screenshots(
            kindle_window,
            output_dir=temp_dir,
            pages=args.pages,
            auto_stop=args.auto_stop,
        )

        # STEP3: PDF化して保存
        # 一時ディレクトリに画像ファイルが1つ以上存在する場合のみPDF化を実行
        if len(os.listdir(temp_dir)) > 0:
            # 出力先ディレクトリが存在しない場合は作成
            os.makedirs(args.output, exist_ok=True)

            # ファイル名を本のタイトルから取得（ウィンドウタイトルから不要な部分を削除）
            book_title = kindle_window.title.replace(" - Kindle", "").strip()

            # 出力ファイルパスを構築
            pdf_filepath = os.path.join(args.output, f"{book_title}.pdf")

            convert_images_to_pdf(temp_dir, pdf_filepath, quality=args.quality)
        else:
            print(
                "スクリーンショットが撮影されなかったため、PDFは作成されませんでした。"
            )

    print("処理が完了し、一時ファイルは自動的に削除されました。")


if __name__ == "__main__":
    main()
