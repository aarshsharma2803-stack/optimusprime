"""Tests for op menubar CLI command group."""

from __future__ import annotations

import platform
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from optimusprime.cli.op import cli
from optimusprime.cli.commands.menubar import _PID_FILE, _MACOS_SCRIPT, _TRAY_SCRIPT


@pytest.fixture(autouse=True)
def clean_pid():
    _PID_FILE.unlink(missing_ok=True)
    yield
    _PID_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_menubar_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["menubar", "--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    assert "stop" in result.output
    assert "status" in result.output


def test_menubar_status_shows_not_running():
    runner = CliRunner()
    result = runner.invoke(cli, ["menubar", "status"])
    assert result.exit_code == 0
    assert "Not running" in result.output


def test_menubar_start_writes_pid_file(tmp_path: Path):
    """op menubar start writes PID to ~/.optimusprime/menubar.pid."""
    fake_script = tmp_path / "fake_menubar.py"
    fake_script.write_text("import time; time.sleep(60)")

    with patch("optimusprime.cli.commands.menubar._MACOS_SCRIPT", new=fake_script):
        with patch("optimusprime.cli.commands.menubar._TRAY_SCRIPT", new=fake_script):
            with patch("optimusprime.cli.commands.menubar.subprocess.Popen") as mock_popen:
                mock_proc = type("FakeProc", (), {"pid": 77777})()
                mock_popen.return_value = mock_proc
                runner = CliRunner()
                result = runner.invoke(cli, ["menubar", "start"])

    assert result.exit_code == 0
    assert "77777" in result.output
    assert _PID_FILE.is_file()
    assert _PID_FILE.read_text().strip() == "77777"


def test_menubar_stop_removes_pid_file():
    """op menubar stop kills process and removes PID file."""
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text("12345")

    with patch("optimusprime.cli.commands.menubar._is_running", return_value=True):
        with patch("optimusprime.cli.commands.menubar.os.kill") as mock_kill:
            mock_kill.return_value = None
            runner = CliRunner()
            result = runner.invoke(cli, ["menubar", "stop"])

    assert result.exit_code == 0
    assert "stopped" in result.output.lower() or "12345" in result.output
    assert not _PID_FILE.exists()


def test_autostart_unsupported_on_non_macos():
    """On non-macOS, autostart reports 'macOS only' and exits cleanly."""
    runner = CliRunner()
    with patch("optimusprime.cli.commands.menubar.platform.system", return_value="Linux"):
        result = runner.invoke(cli, ["menubar", "autostart"])
    assert result.exit_code == 0
    assert "macOS" in result.output
