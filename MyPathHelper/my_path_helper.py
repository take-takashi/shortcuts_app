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
        p = MyPathHelper.replace_safe_path(path)
        p = MyPathHelper.sanitize_filepath(p)
        return p

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
    def sanitize_filepath(path: str) -> str:
        """
        ファイルパスのファイル名部分を無害化します。

        - 使用できない文字を全角に置換
        - スペースをアンダースコアに置換

        Args:
            path (str): 無害化するファイルパス。

        Returns:
            str: ファイル名部分が無害化されたファイルパス。
        """
        # パスからディレクトリ名とファイル名を取得
        directory, filename = os.path.split(path)
        print("dir = ", directory)
        print("filename = ", filename)

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
        filename = filename.translate(translation_table)

        # スペース1つ以上をアンダースコアに置換
        filename = re.sub(r"\s+", "_", filename)
        print("sani = ", filename)

        # ディレクトリ名と無害化されたファイル名を結合して返す
        return os.path.join(directory, filename)
