import subprocess
from unittest.mock import Mock

import pytest

from create_shortcuts import app

ID = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
OTHER_ID = "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"


def registered(name="sample", identifier=ID):
    return app.RegisteredShortcut(name, identifier)


def test_lists_registered_names_and_ids_without_running_shortcuts(monkeypatch):
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, f"sample ({ID})\nname (with parentheses) ({OTHER_ID})\n"
        )
    )
    monkeypatch.setattr(app.subprocess, "run", run)
    assert app.list_shortcuts() == [
        registered(),
        registered("name (with parentheses)", OTHER_ID),
    ]
    assert run.call_args.args[0] == ["/usr/bin/shortcuts", "list", "--show-identifiers"]


def test_malformed_listing_is_not_ignored_to_manufacture_uniqueness(monkeypatch):
    monkeypatch.setattr(
        app.subprocess,
        "run",
        Mock(
            return_value=subprocess.CompletedProcess(
                [], 0, f"sample ({ID})\ninvalid row\n"
            )
        ),
    )
    with pytest.raises(RuntimeError, match="一覧"):
        app.list_shortcuts()


def test_listing_failure_propagates(monkeypatch):
    monkeypatch.setattr(
        app.subprocess,
        "run",
        Mock(side_effect=subprocess.CalledProcessError(1, "shortcuts list")),
    )
    with pytest.raises(subprocess.CalledProcessError):
        app.list_shortcuts()


def test_finds_one_exact_name(monkeypatch):
    monkeypatch.setattr(
        app, "list_shortcuts", lambda: [registered("other"), registered()]
    )
    assert app.find_registered("sample") == registered()


def test_missing_name_returns_none(monkeypatch):
    monkeypatch.setattr(app, "list_shortcuts", lambda: [])
    assert app.find_registered("sample") is None


def test_canonically_equivalent_japanese_names_match(monkeypatch):
    record = registered("取り込んて\u3099")
    monkeypatch.setattr(app, "list_shortcuts", lambda: [record])
    assert app.find_registered("取り込んで") == record


def test_duplicate_names_are_never_automatically_selected(monkeypatch):
    monkeypatch.setattr(
        app, "list_shortcuts", lambda: [registered(), registered(identifier=OTHER_ID)]
    )
    with pytest.raises(RuntimeError, match="複数"):
        app.find_registered("sample")


def test_nfc_and_nfd_duplicates_are_not_selected(monkeypatch):
    monkeypatch.setattr(
        app,
        "list_shortcuts",
        lambda: [registered("取り込んで"), registered("取り込んて\u3099", OTHER_ID)],
    )
    with pytest.raises(RuntimeError, match="複数"):
        app.find_registered("取り込んで")


def test_import_preview_only_opens_for_unregistered_name(tmp_path, monkeypatch):
    path = tmp_path / "sample.shortcut"
    path.write_bytes(b"signed")
    find = Mock(return_value=None)
    monkeypatch.setattr(app, "find_registered", find)
    run = Mock()
    monkeypatch.setattr(app.subprocess, "run", run)
    app.open_import(path, name="sample")
    find.assert_called_once_with("sample")
    assert run.call_args.args[0] == ["/usr/bin/open", "-a", "Shortcuts", str(path)]
    assert run.call_count == 1


def test_existing_registration_stops_before_opening_preview(tmp_path, monkeypatch):
    path = tmp_path / "sample.shortcut"
    path.write_bytes(b"signed")
    monkeypatch.setattr(app, "find_registered", lambda name: registered())
    run = Mock()
    monkeypatch.setattr(app.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="登録済み"):
        app.open_import(path, name="sample")
    run.assert_not_called()


def test_artifact_name_must_match_display_name(tmp_path):
    wrong = tmp_path / "different.shortcut"
    wrong.write_bytes(b"signed")
    with pytest.raises(ValueError, match="ファイル名"):
        app.open_import(wrong, name="sample")


def test_each_generation_has_unique_directory_and_same_file_name(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CACHE_DIR", tmp_path)
    first = app.new_output_path("cd-import", "sample")
    second = app.new_output_path("cd-import", "sample")
    assert first != second
    assert first.name == second.name == "sample.shortcut"
    assert first.is_relative_to(tmp_path / "cd-import")
    assert not first.exists() and not second.exists()


@pytest.mark.parametrize(
    "key,name",
    [("../escape", "sample"), ("cd-import", "../escape"), ("cd-import", "line\nbreak")],
)
def test_unsafe_artifact_names_are_rejected(key, name):
    with pytest.raises(ValueError):
        app.new_output_path(key, name)
