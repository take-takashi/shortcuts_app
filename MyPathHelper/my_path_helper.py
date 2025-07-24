import os
import re


class MyPathHelper:
    """ファイルパス操作に関するヘルパークラス。"""

    @staticmethod
    def complete_safe_path(path: str) -> str:
        """
        指定されたパスを安全で完全な絶対パスに変換します。

        Args:
            path (str): 変換するファイルパス。

        Returns:
            str: 安全で完全な絶対パス。
        """

        # DirとFilenameに分離する
        directory, filename = os.path.split(path)

        directory = MyPathHelper.replace_safe_path(directory)
        filename = MyPathHelper.sanitize_filepath(filename)
        return os.path.join(directory, filename)

    @staticmethod
    def replace_safe_path(path: str) -> str:
        """
        パス文字列を環境に合わせて展開し、正規化して絶対パスを返します。

        - ホームディレクトリ (~, ~user) を展開
        - 環境変数 ($VAR, %VAR%) を展開
        - パスを正規化 (.., . を解決)
        - 絶対パスに変換
        - シンボリックリンクを解決

        Args:
            path (str): 変換するファイルパス。

        Returns:
            str: 解決済みの絶対パス。
        """
        p = path
        # ~ または ~user をホームディレクトリに展開
        p = os.path.expanduser(p)
        # $VAR や %VAR% を環境変数に展開
        p = os.path.expandvars(p)
        # 不要な .., . などを取り除いて正規化
        p = os.path.normpath(p)
        # 相対パスを絶対パスに変換
        p = os.path.abspath(p)
        # シンボリックリンクを実体に解決した絶対パスを返す
        p = os.path.realpath(p)
        return p

    @staticmethod
    def sanitize_filepath(filename: str) -> str:
        """
        ファイル名を無害化します。

        - 使用できない文字を全角に置換
        - スペースをアンダースコアに置換

        Args:
            path (str): 無害化するファイル名。

        Returns:
            str: ファイル名部分が無害化されたファイル名。
        """

        # ファイル名に使用できない文字を全角に置換するための変換テーブルを作成
        translation_table = str.maketrans(
            {
                "<": "＜",
                ">": "＞",
                ":": "：",
                '"': "”",
                "/": "／",
                "\\": "＼",
                "|": "｜",
                "?": "？",
                "*": "＊",
            }
        )
        # ファイル名に使用できない文字を全置換
        filename = filename.translate(translation_table)

        # スペース1つ以上をアンダースコアに置換
        filename = re.sub(r"\s+", "_", filename)

        return filename
