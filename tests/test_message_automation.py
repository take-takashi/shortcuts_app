import io
import sys
from unittest.mock import Mock, patch

import pytest

import message_automation


@pytest.mark.parametrize(
    "message",
    [
        "auto:notion",
        "MAC|unknown",
        "MAC|auto:notion|extra",
        "OTHER|auto:notion",
    ],
)
def test_parse_message_rejects_invalid_or_unregistered_commands(message):
    with pytest.raises(ValueError):
        message_automation.parse_message(message)


def test_parse_message_accepts_registered_command_with_line_ending():
    assert message_automation.parse_message("MAC|auto:notion\n") == "auto:notion"


def test_parse_message_accepts_health_command():
    assert message_automation.parse_message("MAC|health") == "health"


def test_resolve_command_uses_valid_argument_when_stdin_is_blank():
    assert message_automation.resolve_command(" \n", ["MAC|health"]) == "health"


def test_resolve_command_rejects_conflicting_input_channels():
    with pytest.raises(ValueError, match="異なるコマンド"):
        message_automation.resolve_command("MAC|health", ["MAC|auto:notion"])


def test_main_runs_only_the_registered_script():
    completed = Mock(returncode=0)
    with (
        patch.object(message_automation.sys, "stdin", io.StringIO("MAC|auto:notion\n")),
        patch.object(message_automation.sys, "argv", ["message_automation.py"]),
        patch.object(message_automation.subprocess, "run", return_value=completed) as run,
    ):
        assert message_automation.main() == 0

    run.assert_called_once_with(
        [
            sys.executable,
            str(message_automation.SCRIPT_DIR / "download_and_upload_for_notion.py"),
        ],
        cwd=message_automation.SCRIPT_DIR,
        check=False,
    )


def test_health_command_returns_ok_without_running_a_script(capsys):
    with (
        patch.object(message_automation.sys, "stdin", io.StringIO("MAC|health")),
        patch.object(message_automation.sys, "argv", ["message_automation.py"]),
        patch.object(message_automation.subprocess, "run") as run,
    ):
        assert message_automation.main() == 0

    assert capsys.readouterr().out == "OK\n"
    run.assert_not_called()


def test_health_command_can_be_passed_as_argument(capsys):
    with (
        patch.object(message_automation.sys, "stdin", io.StringIO("")),
        patch.object(
            message_automation.sys,
            "argv",
            ["message_automation.py", "MAC|health"],
        ),
        patch.object(message_automation.subprocess, "run") as run,
    ):
        assert message_automation.main() == 0

    assert capsys.readouterr().out == "OK\n"
    run.assert_not_called()


def test_main_does_not_run_unregistered_command():
    with (
        patch.object(message_automation.sys, "stdin", io.StringIO("MAC|rm -rf /")),
        patch.object(message_automation.sys, "argv", ["message_automation.py"]),
        patch.object(message_automation.subprocess, "run") as run,
        patch("builtins.print") as print_error,
    ):
        assert message_automation.main() == 2

    run.assert_not_called()
    print_error.assert_called_once()
