
import os
import subprocess
import sys

from dotenv import load_dotenv

from MyLoggerHelper import MyLoggerHelper

# ===== 前提条件 ==============================================================
# PCにffmpegをインストールしていること

# ===== Config Begin ==========================================================
# .envを読み込む
load_dotenv()
LOG_DIR = os.getenv("LOG_DIR", "~/Downloads")

# ===== Config End ============================================================
logger = MyLoggerHelper.setup_logger(__name__, LOG_DIR)

# ファイルサイズを返す関数
def get_size_bytes(file: str) -> int:
    return os.path.getsize(file)


def main():
    # ffmpegで動画を綺麗に分割したい
    print("FFmpegで動画を綺麗に分割します")

    # コマンドライン引数を取得
    args = sys.argv[1:]
    # コマンドライン引数をそれぞれファイルパスとして処理する
    file = args[0] # 引数最初の一個のみ処理

    input_video = file

    # TODO: ここでファイル存在チェック

    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_video
    ]

    duration_output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8").strip()
    duration_sec = float(duration_output)

    # ステップ 1：動画の総バイト数と再生時間を取得
    file_size_bytes = get_size_bytes(input_video)

    print("file_size_bytes: ", file_size_bytes)
    print("duration_sec2: ", duration_sec)

    # ステップ 2：5GiBに相当する再生時間を計算（ちょっと引いておく）
    five_gib = (5 * 1024 ** 3) - (1024 ** 2 * 100)  # 5GiB in bytes - a little
    ratio = five_gib / file_size_bytes
    split_time_sec = duration_sec * ratio

    print("Target split time (sec):", split_time_sec)

    # ステップ 3：分割の準備として「その時点のキーフレーム」付近を探す（オプション）

    # ===== 分割処理 =====
    safe_margin = 10.0  # 10秒（分割する際の安全マージン）

    # 5GiB付近で分割する際のパート数算出
    num_parts = int(duration_sec // split_time_sec) + (1 if duration_sec % split_time_sec > 0 else 0)
    duration_per_part = split_time_sec
    base_path = input_video.rsplit(".", 1)[0]
    for i in range(num_parts):
        start = max(0, duration_per_part * i - safe_margin)
        duration = duration_per_part + safe_margin
        output_path = f"{base_path}_part{i+1}.mp4"

        cmd = [
            "ffmpeg",
            "-ss", f"{start}",
            "-i", input_video,
            "-t", f"{duration}",
            "-c", "copy",
            "-avoid_negative_ts", "1",
            output_path
        ]

        print(f"[{i+1}/{num_parts}] ffmpegで分割中: {output_path}")
        subprocess.run(cmd, check=True)

        # TODO: ffmpegの出力を抑える

        # キーフレームを特定してそこで分割する線は再度練る（-skip_frameを使ってみる）

if __name__ == "__main__":
    main()
    exit(0)