import os


class MyPathHelper:
    @staticmethod
    def replace_safe_path(path: str) -> str:
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
