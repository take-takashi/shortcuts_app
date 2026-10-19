import io
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import message_automation as automation


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv(automation.LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setattr(automation, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(automation, "DEFAULT_LOG_DIR", tmp_path / "default-logs")
    yield
    if automation._log_handler is not None:
        automation.logger.removeHandler(automation._log_handler)
        automation._log_handler.close()
        automation._log_handler = None
    automation.logger.propagate = True


def invoke(message="MAC|auto:notion", *, via_stdin=False):
    with (
        patch.object(automation.sys, "stdin", io.StringIO(message if via_stdin else "")),
        patch.object(
            automation.sys,
            "argv",
            ["message_automation.py", *([] if via_stdin else [message])],
        ),
    ):
        return automation.main()


def event_log(log_dir: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in log_dir.glob("message_automation-[0-9]*.log")
    )


@pytest.mark.parametrize(
    "message",
    [
        "auto:notion",
        "MAC|unknown",
        "MAC|auto:notion|extra",
        "OTHER|auto:notion",
        "MAC|--notion-worker",
        "tailscale:off",
        "MAC|tailscale:up",
        "MAC|tailscale:on --reset",
        "MAC|tailscale:on; echo injected",
        "MAC|tailscale:off|extra",
    ],
)
def test_parse_message_rejects_invalid_or_unregistered_commands(message):
    with pytest.raises(ValueError):
        automation.parse_message(message)


def test_parse_message_accepts_registered_command_with_line_ending():
    assert automation.parse_message("MAC|auto:notion\n") == "auto:notion"


@pytest.mark.parametrize("command", ["health", "tailscale:on", "tailscale:off"])
def test_parse_message_accepts_registered_commands(command):
    assert automation.parse_message(f"MAC|{command}") == command


def test_resolve_command_uses_valid_argument_when_stdin_is_blank():
    assert automation.resolve_command(" \n", ["MAC|health"]) == "health"


def test_resolve_command_rejects_conflicting_input_channels():
    with pytest.raises(ValueError, match="異なるコマンド"):
        automation.resolve_command("MAC|health", ["MAC|auto:notion"])


def test_main_launches_only_the_fixed_detached_worker(tmp_path, capsys):
    with patch.object(automation.subprocess, "Popen", return_value=Mock(pid=1234)) as popen:
        assert invoke(via_stdin=True) == 0

    popen.assert_called_once()
    arguments = popen.call_args.args[0]
    options = popen.call_args.kwargs
    assert arguments == [
        sys.executable,
        "-u",
        str(automation.SCRIPT_DIR / "message_automation.py"),
        automation.NOTION_WORKER_ARG,
        str(options["pass_fds"][0]),
    ]
    assert options["cwd"] == automation.SCRIPT_DIR
    assert options["start_new_session"] is True
    assert options["close_fds"] is True
    assert options["stdin"] == subprocess.DEVNULL
    assert options["stderr"] == subprocess.STDOUT
    assert Path(options["stdout"].name).parent == tmp_path / "logs"
    assert "shell" not in options
    assert capsys.readouterr().out == "STARTED pid=1234\n"
    text = event_log(tmp_path / "logs")
    assert "起動を受け付けました" in text
    assert "本処理が完了" not in text
    assert "Cookie" not in text


def test_duplicate_launch_is_skipped(tmp_path, capsys):
    lock_file = automation.acquire_notion_lock()
    assert lock_file is not None
    with lock_file, patch.object(automation.subprocess, "Popen") as popen:
        assert invoke() == 0
    popen.assert_not_called()
    assert capsys.readouterr().out == "ALREADY_RUNNING\n"
    assert "重複起動をスキップ" in event_log(tmp_path / "logs")


def test_spawn_failure_is_logged_and_releases_lock(tmp_path):
    with patch.object(automation.subprocess, "Popen", side_effect=OSError("spawn failed")):
        assert invoke() == 1
    assert "spawn failed" in event_log(tmp_path / "logs")
    lock_file = automation.acquire_notion_lock()
    assert lock_file is not None
    lock_file.close()


def test_missing_script_does_not_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(automation, "SCRIPT_DIR", tmp_path)
    with patch.object(automation.subprocess, "Popen") as popen:
        assert invoke() == 1
    popen.assert_not_called()
    assert "スクリプトが見つかりません" in event_log(tmp_path / "logs")


def test_unwritable_log_directory_does_not_spawn(tmp_path, monkeypatch, capsys):
    invalid_dir = tmp_path / "not-a-directory"
    invalid_dir.write_text("file", encoding="utf-8")
    monkeypatch.setenv(automation.LOG_DIR_ENV, str(invalid_dir))
    with patch.object(automation.subprocess, "Popen") as popen:
        assert invoke() == 1
    popen.assert_not_called()
    assert "ログファイルを設定できないため起動しません" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["~/logs", "$HOME/logs", "relative-logs", ""])
def test_log_directory_is_configurable(value, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(automation.LOG_DIR_ENV, value)
    monkeypatch.setattr(automation, "SCRIPT_DIR", tmp_path)
    assert invoke("MAC|health") == 0
    expected = tmp_path / (
        "logs" if value.startswith(("~", "$")) else value or "default-logs"
    )
    assert "command=health returncode=0" in event_log(expected)


@pytest.mark.parametrize("via_stdin", [True, False])
def test_health_returns_ok_without_starting_a_worker(via_stdin, capsys):
    with patch.object(automation.subprocess, "Popen") as popen:
        assert invoke("MAC|health", via_stdin=via_stdin) == 0
    assert capsys.readouterr().out == "OK\n"
    popen.assert_not_called()


def test_find_tailscale_prefers_path():
    with patch.object(
        automation.shutil, "which", return_value="/custom/bin/tailscale"
    ) as which:
        assert automation.find_tailscale() == "/custom/bin/tailscale"
    which.assert_called_once_with("tailscale")


@pytest.mark.parametrize("candidate", automation.TAILSCALE_PATHS)
def test_find_tailscale_uses_known_paths_when_missing_from_path(candidate):
    with patch.object(
        automation.shutil,
        "which",
        side_effect=lambda name: candidate if name == candidate else None,
    ):
        assert automation.find_tailscale() == candidate


def test_find_tailscale_requires_executable_file(tmp_path, monkeypatch):
    executable = tmp_path / "tailscale"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(automation, "TAILSCALE_PATHS", (str(executable),))
    with pytest.raises(FileNotFoundError, match="Tailscale CLIが見つかりません"):
        automation.find_tailscale()
    executable.chmod(0o755)
    assert automation.find_tailscale() == str(executable)


@pytest.mark.parametrize("via_stdin", [True, False])
@pytest.mark.parametrize(
    ("action", "arguments", "output"),
    [
        ("on", ["up", "--timeout=20s"], "TAILSCALE_ON\n"),
        ("off", ["down"], "TAILSCALE_OFF\n"),
    ],
)
def test_tailscale_runs_only_fixed_cli_command(
    action, arguments, output, via_stdin, tmp_path, capsys
):
    with (
        patch.object(automation, "find_tailscale", return_value="/test/tailscale"),
        patch.object(
            automation.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ) as run,
        patch.object(automation.subprocess, "Popen") as popen,
    ):
        assert invoke(f"MAC|tailscale:{action}", via_stdin=via_stdin) == 0
    run.assert_called_once_with(
        ["/test/tailscale", *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    popen.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == output
    assert captured.err == ""
    text = event_log(tmp_path / "logs")
    assert "Tailscaleの切り替えが完了しました" in text
    assert f"command=tailscale:{action} returncode=0" in text


def test_tailscale_success_keeps_cli_warnings_in_stderr_and_log(tmp_path, capsys):
    with (
        patch.object(automation, "find_tailscale", return_value="/test/tailscale"),
        patch.object(
            automation.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout="", stderr="Warning: version mismatch\n"
            ),
        ),
    ):
        assert invoke("MAC|tailscale:on") == 0
    captured = capsys.readouterr()
    assert captured.out == "TAILSCALE_ON\n"
    assert "version mismatch" in captured.err
    assert "version mismatch" in event_log(tmp_path / "logs")


@pytest.mark.parametrize("action", ["on", "off"])
@pytest.mark.parametrize("returncode", [1, 7, -15])
def test_tailscale_failure_is_logged_without_success_output(
    action, returncode, tmp_path, capsys
):
    with (
        patch.object(automation, "find_tailscale", return_value="/test/tailscale"),
        patch.object(
            automation.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], returncode, stdout="Login required\n", stderr="CLI failed\n"
            ),
        ),
    ):
        expected_status = returncode if returncode >= 0 else 1
        assert invoke(f"MAC|tailscale:{action}") == expected_status
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Login required" in captured.err
    assert "CLI failed" in captured.err
    assert "Tailscaleの切り替えに失敗しました" in captured.err
    text = event_log(tmp_path / "logs")
    assert "Login required" in text
    assert "CLI failed" in text
    assert f"command=tailscale:{action} returncode={returncode}" in text
    assert "Tailscaleの切り替えが完了しました" not in text


def test_tailscale_missing_cli_does_not_run(tmp_path, capsys):
    with (
        patch.object(automation.shutil, "which", return_value=None),
        patch.object(automation.subprocess, "run") as run,
    ):
        assert invoke("MAC|tailscale:on") == 1
    run.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Tailscale CLIが見つかりません" in captured.err
    assert "Tailscale CLIが見つかりません" in event_log(tmp_path / "logs")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (OSError("exec failed"), "exec failed"),
        (
            subprocess.TimeoutExpired(["/test/tailscale", "up"], 25),
            "Tailscaleの操作がタイムアウトしました",
        ),
    ],
)
def test_tailscale_execution_errors_are_reported(error, message, tmp_path, capsys):
    with (
        patch.object(automation, "find_tailscale", return_value="/test/tailscale"),
        patch.object(automation.subprocess, "run", side_effect=error),
    ):
        assert invoke("MAC|tailscale:on") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err
    assert message in event_log(tmp_path / "logs")


def test_main_does_not_run_unregistered_command(tmp_path, capsys):
    with patch.object(automation.subprocess, "Popen") as popen:
        assert invoke("MAC|rm -rf /") == 2
    popen.assert_not_called()
    assert "許可されていないコマンド" in capsys.readouterr().err
    assert "コマンドの解決に失敗" in event_log(tmp_path / "logs")


@pytest.mark.parametrize("returncode", [0, 7, -15])
def test_worker_logs_completion_or_failure_and_releases_lock(returncode, tmp_path):
    automation.configure_logger()
    lock_file = automation.acquire_notion_lock()
    assert lock_file is not None
    # 起動元がロックFDを渡した後で閉じる状況を再現する。
    inherited_fd = os.dup(lock_file.fileno())
    lock_file.close()
    with patch.object(
        automation.subprocess, "run", return_value=Mock(returncode=returncode)
    ) as run:
        expected_status = returncode if returncode >= 0 else 1
        assert automation.run_notion_worker(inherited_fd) == expected_status

    run.assert_called_once_with(
        [
            sys.executable,
            "-u",
            str(automation.SCRIPT_DIR / "download_and_upload_for_notion.py"),
        ],
        cwd=automation.SCRIPT_DIR,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        pass_fds=(inherited_fd,),
        check=False,
    )
    text = event_log(tmp_path / "logs")
    assert ("本処理が完了しました" if returncode == 0 else "本処理が失敗しました") in text
    assert f"returncode={returncode}" in text
    assert "elapsed=" in text
    next_lock = automation.acquire_notion_lock()
    assert next_lock is not None
    next_lock.close()


def test_worker_logs_unexpected_exception(tmp_path):
    automation.configure_logger()
    lock_file = automation.acquire_notion_lock()
    assert lock_file is not None
    inherited_fd = os.dup(lock_file.fileno())
    lock_file.close()
    with patch.object(automation.subprocess, "run", side_effect=OSError("exec failed")):
        assert automation.run_notion_worker(inherited_fd) == 1
    assert "exec failed" in event_log(tmp_path / "logs")
    assert "本処理の実行に失敗" in event_log(tmp_path / "logs")


@pytest.mark.parametrize("extra_args", [[], ["0"], ["not-a-fd"], ["3", "extra"]])
def test_internal_worker_rejects_invalid_arguments(extra_args, tmp_path):
    with (
        patch.object(
            automation.sys,
            "argv",
            ["message_automation.py", automation.NOTION_WORKER_ARG, *extra_args],
        ),
        patch.object(automation.subprocess, "run") as run,
    ):
        assert automation.main() == 1
    run.assert_not_called()
    assert "ワーカーの起動に失敗" in event_log(tmp_path / "logs")


def test_internal_worker_rejects_unrelated_lock_fd(tmp_path):
    automation.configure_logger()
    lock_file = automation.acquire_notion_lock()
    assert lock_file is not None
    lock_file.close()
    unrelated = tmp_path / "unrelated-file"
    unrelated.write_text("not a lock", encoding="utf-8")
    with unrelated.open("a+") as handle:
        inherited_fd = os.dup(handle.fileno())
    with patch.object(automation.subprocess, "run") as run:
        with pytest.raises(ValueError, match="ロックFDが一致しません"):
            automation.run_notion_worker(inherited_fd)
    run.assert_not_called()


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("background test worker did not finish in time")


@pytest.fixture
def isolated_app(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    shutil.copy2(automation.SCRIPT_DIR / "message_automation.py", app_dir)
    # 実際のNotion・Cookieには触らず、明示的な解放まで待つ小さな処理で検証する。
    (app_dir / "download_and_upload_for_notion.py").write_text(
        """import os
import sys
import time
from pathlib import Path
root = Path(__file__).parent
with (root / 'started').open('a') as marker:
    marker.write(f'{os.getpid()} session={os.getsid(0)}\\n')
print('worker stdout', flush=True)
print('worker stderr', file=sys.stderr, flush=True)
deadline = time.monotonic() + 20
while not (root / 'release').exists():
    if time.monotonic() > deadline:
        raise RuntimeError('test release timed out')
    time.sleep(0.02)
raise SystemExit(int((root / 'exit-code').read_text()))
""",
        encoding="utf-8",
    )
    (app_dir / "exit-code").write_text("0", encoding="utf-8")
    environment = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        automation.LOG_DIR_ENV: str(tmp_path / "logs"),
    }
    yield app_dir, environment
    (app_dir / "release").touch()
    if (app_dir / "started").exists():
        wait_until(
            lambda: "本処理が完了" in event_log(tmp_path / "logs")
            or "本処理が失敗" in event_log(tmp_path / "logs")
        )


@pytest.mark.parametrize("returncode", [0, 7])
def test_real_background_launch_returns_early_prevents_duplicates_and_can_restart(
    isolated_app, tmp_path, returncode
):
    app_dir, environment = isolated_app
    (app_dir / "exit-code").write_text(str(returncode), encoding="utf-8")
    command = [sys.executable, str(app_dir / "message_automation.py"), "MAC|auto:notion"]

    # capture_outputのパイプをワーカーが引き継ぐと、ここがタイムアウトする。
    accepted = subprocess.run(
        command, input="", capture_output=True, text=True, env=environment, timeout=5
    )
    assert accepted.returncode == 0
    assert accepted.stdout.startswith("STARTED pid=")
    assert not (app_dir / "release").exists()
    wait_until(lambda: (app_dir / "started").exists())
    assert f"session={os.getsid(0)}\n" not in (app_dir / "started").read_text()

    # 出力先が異なっていても同じ実行ロックを使う。
    duplicate = subprocess.run(
        command,
        input="",
        capture_output=True,
        text=True,
        env={**environment, automation.LOG_DIR_ENV: str(tmp_path / "other-logs")},
        timeout=5,
    )
    assert duplicate.returncode == 0
    assert duplicate.stdout == "ALREADY_RUNNING\n"
    assert len((app_dir / "started").read_text().splitlines()) == 1

    (app_dir / "release").touch()
    result_marker = "本処理が完了しました" if returncode == 0 else "本処理が失敗しました"
    wait_until(lambda: result_marker in event_log(tmp_path / "logs"))
    assert f"returncode={returncode}" in event_log(tmp_path / "logs")
    output_log = next(
        (tmp_path / "logs").glob("message_automation-notion-*.log")
    ).read_text()
    assert "worker stdout" in output_log
    assert "worker stderr" in output_log

    # ロックファイル自体が残っていても、処理終了後は再起動できる。
    restarted = subprocess.run(
        command, input="", capture_output=True, text=True, env=environment, timeout=5
    )
    assert restarted.returncode == 0
    assert restarted.stdout.startswith("STARTED pid=")
    wait_until(lambda: event_log(tmp_path / "logs").count(result_marker) == 2)


def test_simultaneous_launches_start_only_one_job(isolated_app):
    app_dir, environment = isolated_app
    command = [sys.executable, str(app_dir / "message_automation.py"), "MAC|auto:notion"]

    def launch():
        return subprocess.run(
            command, input="", capture_output=True, text=True, env=environment, timeout=5
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(launch) for _ in range(4)]
        results = [future.result() for future in futures]
    assert all(result.returncode == 0 for result in results)
    assert sum(result.stdout.startswith("STARTED pid=") for result in results) == 1
    assert sum(result.stdout == "ALREADY_RUNNING\n" for result in results) == 3
    wait_until(lambda: (app_dir / "started").exists())
    assert len((app_dir / "started").read_text().splitlines()) == 1
