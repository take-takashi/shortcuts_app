import plistlib
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from create_shortcuts import Shortcut, builder


def test_shortcut_exposes_fluent_actions_in_order():
    shortcut = Shortcut("サンプル")
    assert shortcut.comment("説明") is shortcut
    assert shortcut.alert("確認", "続けますか？", cancel=True) is shortcut
    assert shortcut.run_shell("printf hello", shell="/bin/zsh") is shortcut
    data = shortcut.to_plist()
    assert data["WFWorkflowName"] == "サンプル"
    actions = data["WFWorkflowActions"]
    assert [a["WFWorkflowActionIdentifier"] for a in actions] == [
        "is.workflow.actions.comment",
        "is.workflow.actions.alert",
        "is.workflow.actions.runshellscript",
    ]
    assert actions[0]["WFWorkflowActionParameters"] == {"WFCommentActionText": "説明"}
    assert actions[1]["WFWorkflowActionParameters"] == {
        "WFAlertActionTitle": "確認",
        "WFAlertActionMessage": "続けますか？",
        "WFAlertActionCancelButtonShown": True,
    }
    assert actions[2]["WFWorkflowActionParameters"] == {
        "Script": "printf hello",
        "Shell": "/bin/zsh",
        "InputMode": "to stdin",
    }


def test_each_definition_and_export_snapshot_is_independent():
    first = Shortcut("one").comment("keep")
    second = Shortcut("two").comment("other")
    snapshot = first.to_plist()
    snapshot["WFWorkflowActions"][0]["WFWorkflowActionParameters"][
        "WFCommentActionText"
    ] = "changed"
    snapshot["WFWorkflowTypes"].append("MenuBar")
    snapshot["WFWorkflowIcon"]["WFWorkflowIconGlyphNumber"] = 0
    assert (
        first.to_plist()["WFWorkflowActions"][0]["WFWorkflowActionParameters"][
            "WFCommentActionText"
        ]
        == "keep"
    )
    assert first.to_plist()["WFWorkflowTypes"] == []
    assert first.to_plist()["WFWorkflowIcon"]["WFWorkflowIconGlyphNumber"] != 0
    assert (
        second.to_plist()["WFWorkflowActions"][0]["WFWorkflowActionParameters"][
            "WFCommentActionText"
        ]
        == "other"
    )


def test_alert_can_disable_cancel_and_shell_can_accept_arguments():
    data = (
        Shortcut("test")
        .alert("Notice", cancel=False)
        .run_shell('printf "%s" "$1"', shell="/bin/bash", input_mode="as arguments")
        .to_plist()
    )
    actions = data["WFWorkflowActions"]
    assert (
        actions[0]["WFWorkflowActionParameters"]["WFAlertActionCancelButtonShown"]
        is False
    )
    assert actions[1]["WFWorkflowActionParameters"]["Shell"] == "/bin/bash"
    assert actions[1]["WFWorkflowActionParameters"]["InputMode"] == "as arguments"


@pytest.mark.parametrize("name", ["", "  ", None, 1])
def test_invalid_name_is_rejected(name):
    with pytest.raises(ValueError):
        Shortcut(name)


def test_invalid_action_arguments_are_rejected():
    shortcut = Shortcut("test")
    with pytest.raises(ValueError):
        shortcut.comment(None)
    with pytest.raises(ValueError):
        shortcut.alert("confirm", cancel="false")
    with pytest.raises(ValueError):
        shortcut.run_shell(" ")
    with pytest.raises(ValueError):
        shortcut.run_shell("true", input_mode="not-a-mode")
    with pytest.raises(ValueError):
        shortcut.run_shell("true", shell="zsh")
    assert shortcut.to_plist()["WFWorkflowActions"] == []


def test_unsigned_export_is_readable_xml_without_signing_or_running(
    tmp_path, monkeypatch
):
    run = Mock(side_effect=AssertionError("must not execute a command"))
    monkeypatch.setattr(builder.subprocess, "run", run)
    shortcut = Shortcut("サンプル").comment("読めるデータ")
    target = tmp_path / "sample.plist"
    assert shortcut.export(target, sign=False) == target
    assert target.read_bytes().startswith(b"<?xml")
    assert plistlib.loads(target.read_bytes()) == shortcut.to_plist()
    assert "読めるデータ" in target.read_text()
    run.assert_not_called()


def test_signed_export_only_invokes_signer(tmp_path, monkeypatch):
    shortcut = Shortcut("not CD specific").run_shell("printf test")

    def sign(command, **kwargs):
        assert command[:4] == ["/usr/bin/shortcuts", "sign", "--mode", "anyone"]
        unsigned = Path(command[command.index("--input") + 1])
        assert unsigned.read_bytes().startswith(b"bplist00")
        assert plistlib.loads(unsigned.read_bytes()) == shortcut.to_plist()
        Path(command[command.index("--output") + 1]).write_bytes(b"signed")

    run = Mock(side_effect=sign)
    monkeypatch.setattr(builder.subprocess, "run", run)
    target = tmp_path / "sample.shortcut"
    assert shortcut.export(target) == target
    assert target.read_bytes() == b"signed"
    assert run.call_count == 1


@pytest.mark.parametrize("sign,suffix", [(True, ".shortcut"), (False, ".plist")])
@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_exports_never_replace_existing_outputs(
    tmp_path, monkeypatch, sign, suffix, kind
):
    target = tmp_path / ("sample" + suffix)
    if kind == "file":
        target.write_bytes(b"keep")
    else:
        target.symlink_to(tmp_path / "missing")
    run = Mock()
    monkeypatch.setattr(builder.subprocess, "run", run)
    with pytest.raises(FileExistsError):
        Shortcut("test").export(target, sign=sign)
    assert target.is_symlink() if kind == "symlink" else target.read_bytes() == b"keep"
    run.assert_not_called()


def test_failure_does_not_publish_partial_export(tmp_path, monkeypatch):
    monkeypatch.setattr(
        builder.subprocess,
        "run",
        Mock(side_effect=subprocess.CalledProcessError(1, "sign")),
    )
    target = tmp_path / "sample.shortcut"
    with pytest.raises(subprocess.CalledProcessError):
        Shortcut("test").export(target)
    assert not target.exists()


def test_invalid_signer_output_is_not_published(tmp_path, monkeypatch):
    monkeypatch.setattr(builder.subprocess, "run", Mock())
    with pytest.raises(RuntimeError):
        Shortcut("test").export(tmp_path / "sample.shortcut")


def test_signed_publish_race_preserves_other_file(tmp_path, monkeypatch):
    target = tmp_path / "sample.shortcut"

    def sign(command, **kwargs):
        Path(command[command.index("--output") + 1]).write_bytes(b"signed")
        target.write_bytes(b"other")

    monkeypatch.setattr(builder.subprocess, "run", sign)
    with pytest.raises(FileExistsError):
        Shortcut("test").export(target)
    assert target.read_bytes() == b"other"


def test_xml_publish_race_preserves_other_file(tmp_path, monkeypatch):
    target = tmp_path / "sample.plist"
    link = builder.os.link

    def publish(source, destination):
        target.write_bytes(b"other")
        link(source, destination)

    monkeypatch.setattr(builder.os, "link", publish)
    with pytest.raises(FileExistsError):
        Shortcut("test").export(target, sign=False)
    assert target.read_bytes() == b"other"


@pytest.mark.parametrize(
    "sign,path", [(True, "test.app"), (False, "unsigned.shortcut")]
)
def test_export_requires_appropriate_extension(tmp_path, sign, path):
    with pytest.raises(ValueError):
        Shortcut("test").export(tmp_path / path, sign=sign)
