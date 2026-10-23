import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

import import_cd_to_notion as app


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def album_root(tmp_path):
    root = tmp_path / "album"
    root.mkdir()
    metadata = {
        "title": "テストアルバム",
        "artist": "Artist",
        "album_artist": "Artist",
        "tracks": [{"number": 1, "title": "曲", "artist": "Singer"}],
    }
    contents = {
        "aac/album.json": json.dumps(metadata, ensure_ascii=False).encode(),
        "aac/cover.jpg": b"cover",
        "aac/01 曲.m4a": b"aac",
        "capture/audio.bin": b"untouched pcm",
        "capture/toc.bin": b"toc",
        "capture/recipe.json": b"{}",
        "capture/metadata/album.json": b"metadata",
    }
    artifacts = {}
    for name, data in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        artifacts[name] = {"file": name, "bytes": len(data), "sha256": digest(path)}
    report = {
        "schema_version": 2,
        "operation": "import",
        "status": "complete",
        "archival_verified": False,
        "result": {
            "directory": "aac",
            "archive_directory": "capture",
            "album": artifacts["aac/album.json"],
            "artwork": artifacts["aac/cover.jpg"],
            "track_count": 1,
            "metadata_tagged": True,
            "loudness_normalized": True,
            "tracks": [{"number": 1, "title": "曲", **artifacts["aac/01 曲.m4a"]}],
            "archive": [v for k, v in artifacts.items() if k.startswith("capture/")],
        },
    }
    (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return root


def fake_helper():
    helper = Mock()
    helper.get_max_upload_size.return_value = 5 * 1024**3
    helper.get_or_create_tag_page.side_effect = ["album-tag", "artist-tag"]
    helper.upload_file_data.side_effect = ["cover-upload", "zip-upload", "song-upload"]
    helper.attach_uploaded_file.side_effect = ["cover-block", "zip-block", "song-block"]
    helper.create_music_page.return_value = "song-page"
    helper.set_page_icon.return_value = None
    helper.update_file_property.return_value = None
    return helper


def test_zip_contains_entire_capture_and_no_derived_audio(album_root):
    album = app.load_album(album_root)
    archive = app.build_capture_zip(album)
    with zipfile.ZipFile(archive) as saved:
        assert set(saved.namelist()) == {
            entry["file"] for entry in album.result["archive"]
        }
        for name in saved.namelist():
            assert saved.read(name) == (album_root / name).read_bytes()
    assert app.build_capture_zip(album) == archive


@pytest.mark.parametrize(
    "mutation", ["audio", "cover", "extra", "symlink", "traversal"]
)
def test_load_album_refuses_changed_or_unexpected_files(album_root, mutation):
    if mutation == "audio":
        (album_root / "capture/audio.bin").write_bytes(b"corrupt")
    elif mutation == "cover":
        (album_root / "aac/cover.jpg").write_bytes(b"wrong")
    elif mutation == "extra":
        (album_root / "capture/private.txt").write_text("never upload")
    elif mutation == "symlink":
        (album_root / "capture/audio.bin").unlink()
        (album_root / "capture/audio.bin").symlink_to(album_root / "aac/cover.jpg")
    else:
        path = album_root / "report.json"
        report = json.loads(path.read_bytes())
        report["result"]["artwork"]["file"] = "capture/../aac/cover.jpg"
        path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        app.load_album(album_root)


def test_existing_wrong_zip_is_never_overwritten(album_root):
    album = app.load_album(album_root)
    archive = album_root / "capture.zip"
    archive.write_bytes(b"existing")
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        app.build_capture_zip(album)
    assert archive.read_bytes() == b"existing"


def test_upload_places_cover_first_zip_second_and_uses_same_album_tag(album_root):
    album = app.load_album(album_root)
    archive = app.build_capture_zip(album)
    helper = fake_helper()
    state = app.Journal(album, "music-db", "tags-db")
    app.upload_album(album, archive, helper, state)
    assert [c.args[0] for c in helper.upload_file_data.call_args_list] == [
        str(album_root / "aac/cover.jpg"),
        str(archive),
        str(album_root / "aac/01 曲.m4a"),
    ]
    calls = helper.attach_uploaded_file.call_args_list
    assert calls[0].args[:2] == ("album-tag", "cover-upload")
    assert calls[0].kwargs["position"] == {"type": "start"}
    assert calls[1].args[:2] == ("album-tag", "zip-upload")
    assert calls[1].kwargs["position"] == {
        "type": "after_block",
        "after_block": {"id": "cover-block"},
    }
    helper.set_page_icon.assert_called_once_with("album-tag", "cover-upload")
    album_files = helper.update_file_property.call_args_list[0]
    assert album_files.args[0] == "album-tag"
    assert [f["file_upload"]["id"] for f in album_files.args[1]] == [
        "cover-upload",
        "zip-upload",
    ]
    assert album_files.kwargs == {"prepend": True}
    create = helper.create_music_page.call_args
    assert create.args[1:] == ("music-db", "album-tag", "artist-tag")
    assert create.args[0]["artist"] == "Singer"
    assert create.args[0]["track"] == "1/1"
    assert json.loads(state.path.read_bytes())["status"] == "complete"
    helper.reset_mock()
    app.upload_album(album, archive, helper, app.Journal(album, "music-db", "tags-db"))
    helper.upload_file_data.assert_not_called()
    helper.attach_uploaded_file.assert_not_called()
    helper.create_music_page.assert_not_called()


def test_limit_checked_before_any_notion_mutation(album_root):
    album = app.load_album(album_root)
    archive = app.build_capture_zip(album)
    helper = fake_helper()
    helper.get_max_upload_size.return_value = 1
    with pytest.raises(ValueError, match="上限"):
        app.upload_album(
            album, archive, helper, app.Journal(album, "music-db", "tags-db")
        )
    helper.get_or_create_tag_page.assert_not_called()
    helper.upload_file_data.assert_not_called()


def test_safe_upload_failure_resumes_without_recreating_page_or_cover(album_root):
    album = app.load_album(album_root)
    archive = app.build_capture_zip(album)
    helper = fake_helper()
    helper.upload_file_data.side_effect = ["cover-upload", RuntimeError("offline")]
    with pytest.raises(RuntimeError, match="offline"):
        app.upload_album(
            album, archive, helper, app.Journal(album, "music-db", "tags-db")
        )
    helper.reset_mock()
    helper.upload_file_data.side_effect = ["zip-upload", "song-upload"]
    helper.attach_uploaded_file.side_effect = ["zip-block", "song-block"]
    helper.get_or_create_tag_page.side_effect = ["artist-tag"]
    app.upload_album(album, archive, helper, app.Journal(album, "music-db", "tags-db"))
    helper.set_page_icon.assert_not_called()
    assert len(helper.upload_file_data.call_args_list) == 2
    assert helper.get_or_create_tag_page.call_count == 1


def test_uncertain_append_stops_instead_of_silently_duplicating(album_root):
    album = app.load_album(album_root)
    archive = app.build_capture_zip(album)
    helper = fake_helper()
    helper.attach_uploaded_file.side_effect = TimeoutError("response lost")
    with pytest.raises(TimeoutError):
        app.upload_album(
            album, archive, helper, app.Journal(album, "music-db", "tags-db")
        )
    helper.reset_mock()
    with pytest.raises(RuntimeError, match="確認"):
        app.upload_album(
            album, archive, helper, app.Journal(album, "music-db", "tags-db")
        )
    helper.attach_uploaded_file.assert_not_called()
    helper.upload_file_data.assert_not_called()


def test_journal_cannot_be_reused_for_another_database(album_root):
    album = app.load_album(album_root)
    app.Journal(album, "music-db", "tags-db")
    with pytest.raises(ValueError, match="設定"):
        app.Journal(album, "different-db", "tags-db")


def test_prepare_only_never_constructs_notion_client(album_root, monkeypatch, capsys):
    factory = Mock(side_effect=AssertionError("network must not be used"))
    monkeypatch.setattr(app, "make_notion_helper", factory)
    monkeypatch.setattr(app, "STATE_DIR", album_root.parent / "state")
    assert app.main([str(album_root), "--prepare-only"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "prepared"
    assert Path(result["archive"]).is_file()
    factory.assert_not_called()


def test_diskflow_runs_in_its_own_mise_project_and_parses_stdout(tmp_path, monkeypatch):
    expected = {"schema_version": 2, "status": "complete", "result": {"tracks": []}}
    run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(expected)))
    monkeypatch.setattr(app.subprocess, "run", run)
    monkeypatch.setenv("usage_output", "wrong-parent-output")
    monkeypatch.setenv("VIRTUAL_ENV", "/wrong/venv")
    monkeypatch.setenv("NOTION_TOKEN", "dummy-secret-not-for-diskflow")
    output = tmp_path / "output"
    assert (
        app.run_diskflow(
            Path("/mise"), Path("/diskflow"), output, None, "Artist", None, False
        )
        == expected
    )
    args = run.call_args.args[0]
    assert args[:6] == ["/mise", "-C", "/diskflow", "run", "import", "--"]
    assert args[6:] == ["--output", str(output), "--search", "Artist"]
    assert run.call_args.kwargs["cwd"] == Path("/diskflow")
    assert "usage_output" not in run.call_args.kwargs["env"]
    assert "VIRTUAL_ENV" not in run.call_args.kwargs["env"]
    assert "NOTION_TOKEN" not in run.call_args.kwargs["env"]


def test_import_lock_prevents_concurrent_entry_points(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "STATE_DIR", tmp_path)
    with app.import_lock():
        with pytest.raises(RuntimeError, match="実行中"):
            with app.import_lock():
                pytest.fail("must not acquire a second lock")
    with app.import_lock():
        pass


def test_upload_detects_changed_cover_before_attaching(album_root):
    album = app.load_album(album_root)
    archive = app.build_capture_zip(album)
    helper = fake_helper()

    def corrupt(path):
        Path(path).write_bytes(b"changed during upload")
        return "unused-upload"

    helper.upload_file_data.side_effect = corrupt
    with pytest.raises(ValueError, match="送信中"):
        app.upload_album(
            album, archive, helper, app.Journal(album, "music-db", "tags-db")
        )
    helper.attach_uploaded_file.assert_not_called()
    helper.set_page_icon.assert_not_called()


def test_expired_unattached_blob_is_uploaded_again(album_root):
    album = app.load_album(album_root)
    archive = app.build_capture_zip(album)
    journal = app.Journal(album, "music-db", "tags-db")
    journal.data["steps"] = {"album_tag": "album-tag", "cover_upload": "expired-cover"}
    journal.save()
    helper = fake_helper()
    helper.file_upload_is_ready.return_value = False
    helper.get_or_create_tag_page.side_effect = ["artist-tag"]
    app.upload_album(album, archive, helper, app.Journal(album, "music-db", "tags-db"))
    helper.file_upload_is_ready.assert_called_once_with("expired-cover")
    assert helper.attach_uploaded_file.call_args_list[0].args[1] == "cover-upload"


def test_explicit_api_rejection_allows_normal_retry(album_root):
    import requests

    album = app.load_album(album_root)
    journal = app.Journal(album, "music-db", "tags-db")
    response = Mock(status_code=403)
    with pytest.raises(requests.HTTPError):
        journal.step(
            "page", Mock(side_effect=requests.HTTPError(response=response)), unsafe=True
        )
    resumed = app.Journal(album, "music-db", "tags-db")
    assert resumed.step("page", lambda: "page-id", unsafe=True) == "page-id"


def test_corrupt_zip_with_correct_names_is_refused(album_root):
    album = app.load_album(album_root)
    path = album_root / "capture.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for entry in album.result["archive"]:
            data = album.file(entry).read_bytes()
            if entry["file"] == "capture/audio.bin":
                data = b"x" * len(data)
            archive.writestr(entry["file"], data)
    with pytest.raises(ValueError, match="変更"):
        app.build_capture_zip(album)
