import plistlib
import shlex
import subprocess
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from create_shortcuts import app, builder
from create_shortcuts.definitions import cd_import as shortcut


def test_workflow_uses_native_actions_and_cancel_before_launch():
    data = shortcut.create_shortcut().to_plist()
    actions = data["WFWorkflowActions"]
    assert [a["WFWorkflowActionIdentifier"] for a in actions] == [
        "is.workflow.actions.comment",
        "is.workflow.actions.alert",
        "is.workflow.actions.runshellscript",
    ]
    assert (
        actions[1]["WFWorkflowActionParameters"]["WFAlertActionCancelButtonShown"]
        is True
    )
    shell = actions[2]["WFWorkflowActionParameters"]
    assert shell["Script"] == shortcut.LAUNCH_SCRIPT
    assert shell["Shell"] == "/bin/zsh"
    assert shell["InputMode"] == "to stdin"
    assert data["WFWorkflowTypes"] == []


def test_export_contains_no_personal_home_or_credentials(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "do-not-export-this-token")
    data = plistlib.dumps(
        shortcut.create_shortcut().to_plist(), fmt=plistlib.FMT_XML
    ).decode()
    assert str(Path.home()) not in data
    assert "do-not-export-this-token" not in data
    assert "$HOME/github/shortcuts_app" in data
    assert ".command" not in data
    assert "/usr/bin/osascript" in data


def test_launch_script_has_valid_shell_syntax():
    subprocess.run(
        ["/bin/zsh", "-n"], input=shortcut.LAUNCH_SCRIPT, text=True, check=True
    )


def test_missing_project_fails_without_opening_terminal(tmp_path):
    result = subprocess.run(
        ["/bin/zsh", "-c", shortcut.LAUNCH_SCRIPT],
        env={"HOME": str(tmp_path), "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "見つかりません" in result.stderr


def test_missing_mise_fails_without_opening_terminal(tmp_path):
    (tmp_path / "github/shortcuts_app").mkdir(parents=True)
    script = shortcut.LAUNCH_SCRIPT.replace(
        "/opt/homebrew/bin/mise", shlex.quote(str(tmp_path / "missing-brew"))
    ).replace("/usr/local/bin/mise", shlex.quote(str(tmp_path / "missing-local")))
    result = subprocess.run(
        ["/bin/zsh", "-c", script],
        env={"HOME": str(tmp_path), "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "miseが見つかりません" in result.stderr


@pytest.mark.parametrize("mise_location", ["path", "local"])
def test_launch_passes_paths_as_arguments_and_never_runs_mise_itself(
    tmp_path, mise_location
):
    home = tmp_path / "home with spaces, 'single' and \"double\" quotes"
    project = home / "github/shortcuts_app"
    project.mkdir(parents=True)
    bin_dir = tmp_path / "bin" if mise_location == "path" else home / ".local/bin"
    bin_dir.mkdir(parents=True)
    mise = bin_dir / "mise"
    mise.write_text("#!/bin/zsh\nexit 99\n")
    mise.chmod(0o755)
    fake_osascript = tmp_path / "osascript"
    recorded = tmp_path / "arguments"
    recorded_script = tmp_path / "applescript"
    fake_osascript.write_text(
        '#!/bin/zsh\nprintf "%s\\n" "$@" > "$RECORDED"\nwhile IFS= read -r line; do printf "%s\\n" "$line"; done > "$RECORDED_SCRIPT"\n'
    )
    fake_osascript.chmod(0o755)
    script = shortcut.LAUNCH_SCRIPT.replace("/usr/bin/osascript", '"$FAKE_OSASCRIPT"')
    subprocess.run(
        ["/bin/zsh", "-c", script],
        check=True,
        env={
            "HOME": str(home),
            "FAKE_OSASCRIPT": str(fake_osascript),
            "RECORDED": str(recorded),
            "RECORDED_SCRIPT": str(recorded_script),
            "PATH": str(bin_dir) if mise_location == "path" else "",
        },
    )
    assert recorded.read_text().splitlines() == ["-", str(project), str(mise)]
    assert 'tell application "Terminal"' in recorded_script.read_text()
    assert "do script commandText" in recorded_script.read_text()
    assert " run import-cd" in recorded_script.read_text()
    assert ".command" not in recorded_script.read_text()


def applescript_source():
    _, marker, body = shortcut.LAUNCH_SCRIPT.partition("<<'APPLESCRIPT'\n")
    assert marker
    source, marker, _ = body.partition("\nAPPLESCRIPT")
    assert marker
    return source


def test_applescript_compiles_without_running_terminal(tmp_path):
    source = tmp_path / "launcher.applescript"
    source.write_text(applescript_source())
    subprocess.run(
        ["/usr/bin/osacompile", "-o", str(tmp_path / "launcher.scpt"), str(source)],
        check=True,
        capture_output=True,
    )


def test_terminal_command_quotes_paths_without_running_import(tmp_path):
    prefix, marker, _ = applescript_source().partition(
        '    tell application "Terminal"'
    )
    assert marker and "do script" not in prefix
    project = str(tmp_path / "project with 'single' and \"double\" quotes")
    mise = str(tmp_path / "mise with spaces")
    result = subprocess.run(
        ["/usr/bin/osascript", "-", project, mise],
        input=prefix + "    return commandText\nend run\n",
        text=True,
        capture_output=True,
        check=True,
    )
    assert shlex.split(result.stdout.strip()) == [
        "cd",
        project,
        "&&",
        mise,
        "run",
        "import-cd",
    ]


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_build_does_not_replace_existing_files(tmp_path, monkeypatch, kind):
    target = tmp_path / "CD.shortcut"
    if kind == "file":
        target.write_bytes(b"keep")
    else:
        target.symlink_to(tmp_path / "missing")
    run = Mock()
    monkeypatch.setattr(builder.subprocess, "run", run)
    with pytest.raises(FileExistsError):
        shortcut.create_shortcut().export(target)
    run.assert_not_called()
    assert target.is_symlink() if kind == "symlink" else target.read_bytes() == b"keep"


def test_signs_binary_plist_and_never_runs_or_imports_shortcut(tmp_path, monkeypatch):
    def sign(command, **kwargs):
        assert command[:4] == ["/usr/bin/shortcuts", "sign", "--mode", "anyone"]
        assert kwargs["check"] is True
        source = Path(command[command.index("--input") + 1])
        assert source.read_bytes().startswith(b"bplist00")
        assert (
            plistlib.loads(source.read_bytes()) == shortcut.create_shortcut().to_plist()
        )
        Path(command[command.index("--output") + 1]).write_bytes(b"signed-shortcut")
        return subprocess.CompletedProcess(command, 0)

    run = Mock(side_effect=sign)
    monkeypatch.setattr(builder.subprocess, "run", run)
    target = tmp_path / "CD.shortcut"
    assert shortcut.create_shortcut().export(target) == target
    assert target.read_bytes() == b"signed-shortcut"
    assert run.call_count == 1


def test_sign_failure_leaves_no_importable_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        builder.subprocess,
        "run",
        Mock(side_effect=subprocess.CalledProcessError(1, "shortcuts sign")),
    )
    target = tmp_path / "CD.shortcut"
    with pytest.raises(subprocess.CalledProcessError):
        shortcut.create_shortcut().export(target)
    assert not target.exists()


def test_publish_race_preserves_other_file(tmp_path, monkeypatch):
    target = tmp_path / "CD.shortcut"

    def sign(command, **kwargs):
        Path(command[command.index("--output") + 1]).write_bytes(b"signed")
        target.write_bytes(b"created-by-someone-else")

    monkeypatch.setattr(builder.subprocess, "run", sign)
    with pytest.raises(FileExistsError):
        shortcut.create_shortcut().export(target)
    assert target.read_bytes() == b"created-by-someone-else"


def test_rejects_non_shortcut_output(tmp_path):
    with pytest.raises(ValueError):
        shortcut.create_shortcut().export(tmp_path / "CD.app")


def test_task_name_matches_definition_and_has_no_aliases():
    package = Path(shortcut.__file__).resolve().parents[1]
    config = tomllib.loads((package / ".mise.toml").read_text())
    name = Path(shortcut.__file__).stem.replace("_", "-")
    assert set(config["tasks"]) == {name}
    task = config["tasks"][name]
    assert "alias" not in task
    assert (
        task["run"]
        == f"uv run --locked python -m create_shortcuts.definitions.{Path(shortcut.__file__).stem}"
    )
    assert (package / task["dir"]).resolve() == package.parent


def test_no_legacy_task_or_script_entry_point_remains():
    root = Path(shortcut.__file__).resolve().parents[2]
    config = tomllib.loads((root / ".mise.toml").read_text())
    assert "export-cd-shortcut" not in config["tasks"]
    assert "create-cd-shortcut" not in config["tasks"]
    assert not (root / "create_cd_import_shortcut.py").exists()


def test_definition_name_matches_confirmed_registered_name():
    assert shortcut.NAME == "CDを取り込んでNotionへUpload"


def test_cli_checks_target_generates_and_opens_preview_only(
    tmp_path, monkeypatch, capsys
):
    target = app.RegisteredShortcut(
        shortcut.NAME, "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    )
    resolve = Mock(return_value=target)
    opened = Mock()
    definition = Mock()
    definition.export.side_effect = lambda path: path
    monkeypatch.setattr(app, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(app, "resolve_target", resolve)
    monkeypatch.setattr(app, "open_import", opened)
    monkeypatch.setattr(shortcut, "create_shortcut", lambda: definition)
    assert shortcut.main([]) == 0
    resolve.assert_called_once_with(shortcut.NAME, new=False)
    output = definition.export.call_args.args[0]
    assert output.name == shortcut.NAME + ".shortcut"
    assert output.is_relative_to(tmp_path / "cd-import")
    opened.assert_called_once_with(
        output, name=shortcut.NAME, expected_target=target, new=False
    )
    text = capsys.readouterr().out
    assert target.identifier in text
    assert "確認" in text


def test_cli_refuses_ambiguous_or_missing_target_before_signing(tmp_path, monkeypatch):
    definition = Mock()
    monkeypatch.setattr(shortcut, "create_shortcut", lambda: definition)
    monkeypatch.setattr(
        app, "resolve_target", Mock(side_effect=RuntimeError("対象を確認"))
    )
    opened = Mock()
    monkeypatch.setattr(app, "open_import", opened)
    assert shortcut.main([]) == 1
    definition.export.assert_not_called()
    opened.assert_not_called()


def test_cli_new_mode_is_explicit(tmp_path, monkeypatch):
    definition = Mock()
    definition.export.side_effect = lambda path: path
    resolve = Mock(return_value=None)
    monkeypatch.setattr(shortcut, "create_shortcut", lambda: definition)
    monkeypatch.setattr(app, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(app, "resolve_target", resolve)
    opened = Mock()
    monkeypatch.setattr(app, "open_import", opened)
    assert shortcut.main(["--new"]) == 0
    resolve.assert_called_once_with(shortcut.NAME, new=True)
    assert opened.call_args.kwargs["new"] is True
