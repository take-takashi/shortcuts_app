import plistlib
import subprocess
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from create_shortcuts import builder
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
    assert "$HOME/github/shortcuts_app/import_cd_to_notion.command" in data


def test_launch_script_has_valid_shell_syntax():
    subprocess.run(
        ["/bin/zsh", "-n"], input=shortcut.LAUNCH_SCRIPT, text=True, check=True
    )


def test_missing_launcher_fails_without_opening_terminal(tmp_path):
    result = subprocess.run(
        ["/bin/zsh", "-c", shortcut.LAUNCH_SCRIPT],
        env={"HOME": str(tmp_path), "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "見つかりません" in result.stderr


def test_launch_uses_each_macs_home_and_only_opens_command_file(tmp_path):
    home = tmp_path / 'home with spaces and "quotes"'
    launcher = home / "github/shortcuts_app/import_cd_to_notion.command"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/zsh\nexit 99\n")
    launcher.chmod(0o755)
    fake_open = tmp_path / "open"
    recorded = tmp_path / "arguments"
    fake_open.write_text('#!/bin/zsh\nprintf "%s\\n" "$@" > "$RECORDED"\n')
    fake_open.chmod(0o755)
    script = shortcut.LAUNCH_SCRIPT.replace("/usr/bin/open", '"$FAKE_OPEN"')
    subprocess.run(
        ["/bin/zsh", "-c", script],
        check=True,
        env={
            "HOME": str(home),
            "FAKE_OPEN": str(fake_open),
            "RECORDED": str(recorded),
            "PATH": "",
        },
    )
    assert recorded.read_text().splitlines() == ["-a", "Terminal", str(launcher)]


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
