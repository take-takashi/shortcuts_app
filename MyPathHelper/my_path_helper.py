import os
import re

from pathvalidate import sanitize_filename


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
    def sanitize_filepath(name: str) -> str:
        """
        ファイル名を無害化し、スペースをアンダースコアに置換します。

        Args:
            name (str): 無害化するファイル名。

        Returns:
            str: 無害化されたファイル名。
        """
        # 安全なファイル名に変更
        safe_name = sanitize_filename(name)
        # スペース1つ以上をアンダースコアに置換
        safe_name = re.sub(r"\s+", "_", safe_name)
        return safe_name
