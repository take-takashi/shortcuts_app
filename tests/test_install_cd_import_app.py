import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

import install_cd_import_app as app


def test_launcher_quotes_paths_for_applescript_and_shell():
    source = app.launcher_source(Path('/tmp/a "quote" and spaces/import.command'))
    assert 'tell application "Terminal"' in source
    assert 'do script "\'/tmp/a \\"quote\\" and spaces/import.command\'"' in source


def test_installer_does_not_replace_existing_application(tmp_path):
    output = tmp_path / "CD.app"
    output.mkdir()
    marker = output / "existing"
    marker.write_text("keep")
    with pytest.raises(FileExistsError):
        app.install(output)
    assert marker.read_text() == "keep"


def test_installer_only_compiles_and_does_not_launch_or_upload(tmp_path, monkeypatch):
    def compile_app(command, **kwargs):
        assert command[0] == "/usr/bin/osacompile"
        Path(command[2]).mkdir()
        return subprocess.CompletedProcess(command, 0)

    run = Mock(side_effect=compile_app)
    monkeypatch.setattr(app.subprocess, "run", run)
    output = tmp_path / "CD.app"
    assert app.install(output) == output
    assert output.is_dir()
    assert run.call_count == 1
