import argparse
import sys

from MyFfmpegHelper import MyFfmpegHelper


def parse_args(argv):
    """
    引数を解析する。

    Args:
        argv (list): コマンドライン引数のリスト。sys.argv[1:]を想定。

    Returns:
        argparse.Namespace: 解析された引数を持つオブジェクト。

    Raises:
        argparse.ArgumentError: 引数の解析に失敗した場合。
    """
    parser = argparse.ArgumentParser(description="起動引数を確認するスクリプト")
    parser.add_argument("files", nargs="+", help="アップロードするファイルのパス")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    try:
        if argv is None:
            argv = sys.argv[1:]

        args = parse_args(argv)

        print("渡ってきた引数（ファイル想定）: ", args.files)

        file = args.files[0]

        split_size = (5 * 1024**3) - (1024**2 * 100)  # 5GiBとマージン

        split_points = MyFfmpegHelper.get_split_points_by_size(file, split_size)

        all_duration = MyFfmpegHelper.get_duration_sec(file)
        print("動画の長さ（秒）：", all_duration)

        print("分割秒数リスト：", split_points)

        # それぞれのリストからキーフレームを取得する

        split_keyframe_points = MyFfmpegHelper.get_split_keyframe_sec_by_size(
            file, split_size
        )

        print("分割キーフレーム秒数：", split_keyframe_points)

        return 0
    except Exception as e:
        print(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
