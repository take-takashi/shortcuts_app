import math
import os
import subprocess


class MyFfmpegHelper:
    @staticmethod
    def get_duration_sec(input_video: str) -> float:
        """
        動画の長さ（秒：小数）を取得する。

        Args:
            input_video (str): 動画ファイルのパス。

        Returns:
            float: 動画の長さ（秒）。

        Raises:
            Exception: ffprobeの実行中にエラーが発生した場合。
        """
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                input_video,
            ]

            output = (
                subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
                .decode("utf-8")
                .strip()
            )
            duration_sec = float(output)

            return duration_sec

        except Exception as e:
            raise Exception(f"エラーが発生しました: {e}")

    @staticmethod
    def get_size_bytes(input_video: str) -> int:
        """
        ファイルのサイズをバイト単位で取得する。

        Args:
            input_video (str): 動画ファイルのパス。

        Returns:
            int: ファイルのサイズ（バイト）。

        Raises:
            Exception: ファイルが存在しない場合。
        """
        return os.path.getsize(input_video)

    @staticmethod
    def get_split_sec_by_size(
        input_video: str, split_size_bytes: int = 5 * 1024**3
    ) -> float:
        """
        指定された動画を指定されたサイズで分割するときの、分割時間を計算する。

        Args:
            input_video (str): 動画ファイルのパス。
            split_size_bytes (int): 分割したい動画ファイルサイズ（バイト）。デフォルトは5GiB。

        Returns:
            float: 分割目安の時間（秒）。

        Raises:
            Exception: 動画の長さやファイルサイズの取得中にエラーが発生した場合。
        """
        try:
            # 動画の尺を取得
            duration_sec = MyFfmpegHelper.get_duration_sec(input_video)
            # 動画のファイルサイズを取得
            file_size_bytes = MyFfmpegHelper.get_size_bytes(input_video)

            # 分割したいファイルサイズにおける尺を計算
            ratio = split_size_bytes / file_size_bytes
            split_time_sec = duration_sec * ratio

            return split_time_sec

        except Exception as e:
            raise Exception(f"エラーが発生しました: {e}")

    @staticmethod
    def get_keyframes(
        input_video: str, split_time_sec: float = None, read_duration: int = 10
    ) -> list[float]:
        """
        指定された動画からキーフレームの秒数リストを取得する。

        Args:
            input_video (str): 入力動画ファイルのパス。
            split_time_sec (float, optional):  動画を分割する時間間隔（秒）。Noneの場合は分割しない。Defaults to None.

        Returns:
            list[float]: キーフレームの秒数のリスト。

        Raises:
            Exception: ffprobeの実行中にエラーが発生した場合。
        """
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-skip_frame",
                "nokey",
                "-select_streams",
                "v:0",
                "-show_entries",
                "frame=pkt_dts_time",
                "-of",
                "csv=p=0",
            ]

            # キーフレーム調査を行う秒数が指定してあれば、
            # 指定秒数＋手前の幅分読み込む設定にする
            if split_time_sec is not None:
                start_time = max(0, split_time_sec - read_duration)
                cmd.extend(["-read_intervals", f"{start_time}%+{read_duration}"])

            cmd.append(input_video)

            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode(
                "utf-8"
            )
            keyframe_times = [
                float(t.strip().rstrip(",")) for t in output.strip().splitlines()
            ]
            return keyframe_times

        except Exception as e:
            raise Exception(f"エラーが発生しました: {e}")

    @staticmethod
    def get_split_keyframe_sec(input_video: str, split_sec: float) -> float:
        """
        指定された秒数 `split_sec` の直前のキーフレームの秒数を取得します。

        Args:
            input_video (str): 入力動画ファイルのパス。
            split_sec (float): 分割したい秒数。

        Returns:
            float: 指定された秒数 `split_sec` の直前のキーフレームの秒数。

        Raises:
            Exception: キーフレームの取得中にエラーが発生した場合。
        """
        try:
            # 分割したい秒数より直前のキーフレームリストを取得する
            keyframes = MyFfmpegHelper.get_keyframes(input_video, split_sec, 10)

            # split_secに最も近いキーフレームを探す
            closest_keyframe_sec = min(keyframes, key=lambda x: abs(x - split_sec))

            return closest_keyframe_sec

        except Exception as e:
            raise Exception(f"エラーが発生しました: {e}")

    @staticmethod
    def get_split_points_by_size(
        input_video: str, split_size_bytes: int = 5 * 1024**3
    ) -> list[float]:
        """
        動画を指定されたサイズで分割するための分割点を計算します。

        Args:
            input_video (str): 入力動画ファイルのパス。
            split_size_bytes (int): 分割後のファイルの目標サイズ（バイト単位）。デフォルトは5GiB。

        Returns:
            list[float]: 分割点の秒数のリスト。

        Raises:
            Exception: 動画の長さの取得中にエラーが発生した場合。
        """
        # 動画の尺を取得
        duration = MyFfmpegHelper.get_duration_sec(input_video)
        # 指定のファイルサイズにおける尺を取得
        split_sec = MyFfmpegHelper.get_split_sec_by_size(input_video, split_size_bytes)
        return [i * split_sec for i in range(1, math.ceil(duration / split_sec))]

    @staticmethod
    def get_split_keyframe_sec_by_size(
        input_video: str, split_size_bytes: int = 5 * 1024**3
    ) -> list[float]:
        """
        動画を指定されたサイズで分割するためのキーフレーム分割点を計算します。

        Args:
            input_video (str): 入力動画ファイルのパス。
            split_size_bytes (int): 分割後のファイルの目標サイズ（バイト単位）。デフォルトは5GiB。

        Returns:
            list[float]: 分割点の秒数のリスト。各分割点は、指定されたサイズに最も近いキーフレームに基づいています。

        Raises:
            Exception: 動画の長さの取得中にエラーが発生した場合、またはキーフレームの取得中にエラーが発生した場合。
        """
        # 動画を指定のサイズで分割する際の秒数リストを取得
        split_points = MyFfmpegHelper.get_split_points_by_size(
            input_video, split_size_bytes
        )
        # 分割する秒数リストから、それぞれ一番手前のキーフレームの秒数に変換
        for i, split_point in enumerate(split_points):
            split_points[i] = MyFfmpegHelper.get_split_keyframe_sec(
                input_video, split_point
            )

        return split_points

    @staticmethod
    def sample_get_keyframes(input_video: str) -> str:
        """
        指定された動画からキーフレームの情報（60秒分）をサンプル的に取得する。
        Args:
            input_video (str): 入力動画ファイルのパス。
        Returns:
            str: キーフレームの情報を返す。
        Raises:
            Exception: エラーが発生した場合。
        """
        try:
            cmd = [
                "ffprobe",
                "-read_intervals",
                "%+60",
                "-v",
                "error",
                "-skip_frame",
                "nokey",
                "-select_streams",
                "v:0",
                "-show_entries",
                "frame",
                "-of",
                "default",
                input_video,
            ]
            # 試しに60秒の出力
            # ヘッダーを確認用

            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode(
                "utf-8"
            )

            return output
        except Exception as e:
            raise Exception(f"エラーが発生しました: {e}")

    @staticmethod
    def is_video(file_path: str) -> bool:
        """
        指定されたファイルが動画ファイルかどうかを判定します。

        Args:
            file_path (str): 判定するファイルのパス。

        Returns:
            bool: 動画ファイルの場合はTrue、そうでない場合はFalse。
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    file_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return "video" in result.stdout
        except subprocess.CalledProcessError:
            return False

    @staticmethod
    def split_video_lossless_by_keyframes(
        input_video: str, output_dir: str = None, split_size_bytes: int = 5 * 1024**3
    ) -> list[str]:
        """
        無劣化で動画をキーフレーム単位に分割する。

        Args:
            input_video (str): 入力動画のパス。
            output_dir (str): 分割後の動画を保存するディレクトリ。
            split_size_bytes (int): 各分割ファイルの目標サイズ（バイト）。デフォルトは5GiB。

        Returns:
            list[str]: 作成されたファイルパスのリスト。

        Raises:
            Exception: 分割中にエラーが発生した場合。
        """
        try:
            if output_dir is None:
                output_dir = os.path.dirname(input_video)

            os.makedirs(output_dir, exist_ok=True)

            duration = MyFfmpegHelper.get_duration_sec(input_video)
            keyframes = MyFfmpegHelper.get_split_keyframe_sec_by_size(
                input_video, split_size_bytes
            )
            # 開始点と終了点を追加（分割に活用）
            keyframes = [0.0] + keyframes + [duration]

            output_files = []
            # 元のファイル名を取得
            base_name = os.path.splitext(os.path.basename(input_video))[0]
            # 分割数分だけ分割する
            for i in range(len(keyframes) - 1):
                start = keyframes[i]
                end = keyframes[i + 1]
                output_file = os.path.join(output_dir, f"{base_name}_part{i + 1}.mp4")

                cmd = [
                    "ffmpeg",
                    "-ss",
                    str(start),
                    "-to",
                    str(end),
                    "-i",
                    input_video,
                    "-c",
                    "copy",
                    output_file,
                ]
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                output_files.append(output_file)

            return output_files

        except Exception as e:
            raise Exception(f"エラーが発生しました: {e}")

    @staticmethod
    def is_vbr(input_video: str, sample_duration: int = 10) -> bool:
        """
        動画がVBR（可変ビットレート）かどうかを大まかに判定する。
        指定された秒数分のパケットサイズをサンプリングし、そのばらつきから判断する。

        Args:
            input_video (str): 動画ファイルのパス。
            sample_duration (int): 分析する動画の先頭からの秒数。デフォルトは10秒。

        Returns:
            bool: VBRと判定された場合はTrue、CBRと判定された場合はFalse。

        Raises:
            Exception: ffprobeの実行中にエラーが発生した場合。
        """
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=size",
                "-of",
                "csv=p=0",
                "-read_intervals",
                f"%+{sample_duration}",
                input_video,
            ]

            output = (
                subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
                .decode("utf-8")
                .strip()
            )

            if not output:
                # パケット情報が取得できない場合は、判定不能としてCBRとみなす
                return False

            packet_sizes = [int(s.strip()) for s in output.splitlines()]

            if len(packet_sizes) < 2:
                # パケットが1つ以下の場合は、判定不能としてCBRとみなす
                return False

            # パケットサイズの標準偏差を計算
            mean = sum(packet_sizes) / len(packet_sizes)
            variance = sum(
                [((x - mean) ** 2) for x in packet_sizes]
            ) / len(packet_sizes)
            std_dev = math.sqrt(variance)

            # 標準偏差が平均値の10%を超える場合はVBRと判定
            # この閾値は経験的なもので、調整が必要な場合がある
            if std_dev > mean * 0.1:
                return True
            else:
                return False

        except Exception as e:
            raise Exception(f"エラーが発生しました: {e}")