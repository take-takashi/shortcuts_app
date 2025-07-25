import datetime
import json
import os
import pprint
import sys
from logging import Logger, config, getLogger

from MyPathHelper import MyPathHelper


class MyLoggerHelper:
    @staticmethod
    def setup_logger(logger_name: str = "", log_dir: str = "") -> Logger:
        """
        ロガーをセットアップして返します。

        この関数は、JSON形式の設定ファイル（logging_config.json）を読み込み、
        指定されたディレクトリにログファイルを出力するようにロガーを構成します。
        ログファイルはスクリプト名と実行日から命名されます。

        処理の流れ:
        1. JSON設定ファイル 'logging_config.json' を読み込む。
        2. log_dir（またはその代替パス）を取得・作成する。
        3. 実行中のスクリプト名と日付からログファイル名を生成。
        4. ログ設定内のファイルハンドラの出力先ファイル名を上書き。
        5. dictConfigを使ってロガー設定を適用。
        6. 設定済みのロガーインスタンスを返す。

        引数:
            logger_name (str): getLogger時の名前。
            log_dir (str): ログファイルの出力先ディレクトリ。
            空文字列の場合は適切なパスに置き換えられる。

        戻り値:
            logging.Logger: 設定済みのロガーインスタンス。
        """
        logger = getLogger(logger_name)
        with open("logging_config.json", "r") as f:
            log_config = json.load(f)

        # 指定されたディレクトリのパスを正す
        dir = MyPathHelper.replace_safe_path(log_dir)
        os.makedirs(dir, exist_ok=True)  # 念のため存在確認
        # 実行ファイル名からログファイル名を決定
        script_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
        today = datetime.datetime.now().strftime("%Y%m%d")
        log_filename = f"{script_name}-{today}.log"
        log_path = os.path.join(dir, log_filename)
        # ファイルハンドラのファイル名を動的に置き換え
        log_config["handlers"]["file"]["filename"] = log_path
        # ログ設定を適用
        config.dictConfig(log_config)
        return logger

    @staticmethod
    def fprint(obj: object) -> str:
        """
        オブジェクトを整形して文字列として返します。

        この関数は、与えられた任意のPythonオブジェクトを、
        JSON形式でインデント付きの文字列に変換します。
        JSON変換が失敗した場合は、pprintを使って可読性の高い文字列にフォールバックします。

        引数:
            obj (object): 任意のPythonオブジェクト。

        戻り値:
            str: 整形済みの文字列（JSON形式またはpprint形式）。
        """
        try:
            return json.dumps(obj, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            return pprint.pformat(obj)


# End
