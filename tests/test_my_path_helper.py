import logging
import os
import sys

# プロジェクトのルートディレクトリをsys.pathに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from MyPathHelper import MyPathHelper

# print用logger
logger = logging.getLogger(__name__)


#
# replace_safe_path のテスト
#


def test_replace_safe_path_expanduser():
    """ホームディレクトリが正しく展開されることを確認する。"""
    path = "~/test_dir/test_file.txt"
    expected_path = os.path.expanduser(path)
    assert MyPathHelper.replace_safe_path(path) == expected_path


def test_replace_safe_path_expandvars(monkeypatch):
    """環境変数が正しく展開されることを確認する。"""
    monkeypatch.setenv("TEST_VAR", "test_value")
    path = os.path.join("$TEST_VAR", "test_file.txt")
    # os.path.expandvars は Windows 形式 (%VAR%) をサポートしていないため、
    # Python の os.path.expandvars の挙動に合わせる
    expected_path = os.path.abspath(os.path.join("test_value", "test_file.txt"))
    assert MyPathHelper.replace_safe_path(path) == expected_path


def test_replace_safe_path_normpath():
    """パスが正しく正規化されることを確認する。"""
    path = "/some/dir/../other_dir/./test_file.txt"
    expected_path = os.path.abspath("/some/other_dir/test_file.txt")
    assert MyPathHelper.replace_safe_path(path) == expected_path


def test_replace_safe_path_abspath():
    """相対パスが絶対パスに変換されることを確認する。"""
    path = os.path.join("relative_dir", "test_file.txt")
    expected_path = os.path.abspath(path)
    assert MyPathHelper.replace_safe_path(path) == expected_path


#
# sanitize_filepath のテスト
#


def test_sanitize_filepath():
    """ファイル名が無害化され、スペースがアンダースコアに置換されることを確認する。"""
    path = os.path.join(
        "/path",
        "to",
        "directory",
        'file name with spaces and invalid chars<>:"\\|?*.txt',
    )
    expected_path = os.path.join(
        "/path",
        "to",
        "directory",
        "file_name_with_spaces_and_invalid_chars＜＞：”＼｜？＊.txt",
    )

    p = MyPathHelper.complete_safe_path(path)
    logger.info(f"path = {p}")
    logger.info(f"expected_path = {expected_path}")

    assert MyPathHelper.complete_safe_path(path) == expected_path


#
# complete_safe_path のテスト
#


def test_complete_safe_path(monkeypatch):
    """
    パスの展開とファイル名の無害化が両方正しく行われることを確認する。
    """
    monkeypatch.setenv("COMPLETE_TEST", "complete_dir")
    path = os.path.join(
        "~", "some_dir", "..", "$COMPLETE_TEST", "invalid: file name?.txt"
    )
    home_dir = os.path.expanduser("~")
    expected_path = os.path.join(home_dir, "complete_dir", "invalid：_file_name？.txt")
    assert MyPathHelper.complete_safe_path(path) == expected_path
