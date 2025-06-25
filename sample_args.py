import argparse
import sys


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

        return 0
    except Exception as e:
        print(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
