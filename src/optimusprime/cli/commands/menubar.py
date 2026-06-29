"""op menubar — manage the OptimusPrime menu bar / system tray companion app."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

import click

_GLOBAL_OP_DIR = Path.home() / ".optimusprime"
_PID_FILE = _GLOBAL_OP_DIR / "menubar.pid"

# Locate menubar scripts relative to this file:
# commands/ -> cli/ -> optimusprime/ -> src/ -> <repo-root>
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_MENUBAR_DIR = _REPO_ROOT / "menubar"
_MACOS_SCRIPT = _MENUBAR_DIR / "optimusprime_menubar.py"
_TRAY_SCRIPT = _MENUBAR_DIR / "optimusprime_tray.py"


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def _read_pid() -> "int | None":
    try:
        if _PID_FILE.is_file():
            return int(_PID_FILE.read_text().strip())
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

@click.group("menubar")
def menubar() -> None:
    """Manage the OptimusPrime menu bar / system tray companion app."""


@menubar.command("start")
def menubar_start() -> None:
    """Start the menu bar companion app (detached background process)."""
    pid = _read_pid()
    if pid is not None and _is_running(pid):
        click.echo(f"Already running (PID {pid})")
        return

    is_macos = platform.system() == "Darwin"
    script = _MACOS_SCRIPT if is_macos else _TRAY_SCRIPT

    if not script.exists():
        click.echo(f"ERROR: Menu bar script not found at {script}", err=True)
        sys.exit(1)

    try:
        _GLOBAL_OP_DIR.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _PID_FILE.write_text(str(proc.pid))
        click.echo(f"⚡ OptimusPrime menu bar started (PID {proc.pid})")
    except Exception as e:
        click.echo(f"ERROR: Failed to start menu bar app: {e}", err=True)
        sys.exit(1)


@menubar.command("stop")
def menubar_stop() -> None:
    """Stop the menu bar companion app."""
    pid = _read_pid()
    if pid is None:
        click.echo("Not running (no PID file)")
        return
    if not _is_running(pid):
        _PID_FILE.unlink(missing_ok=True)
        click.echo("Not running (stale PID cleaned up)")
        return
    try:
        os.kill(pid, 15)  # SIGTERM
        _PID_FILE.unlink(missing_ok=True)
        click.echo(f"OptimusPrime menu bar stopped (PID {pid})")
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)


@menubar.command("status")
def menubar_status() -> None:
    """Check if the menu bar app is running."""
    pid = _read_pid()
    if pid is None:
        click.echo("Not running")
        return
    if _is_running(pid):
        click.echo(f"Running (PID {pid})")
    else:
        _PID_FILE.unlink(missing_ok=True)
        click.echo("Not running (stale PID cleaned up)")


@menubar.command("autostart")
def menubar_autostart() -> None:
    """Enable OptimusPrime to auto-start at login (macOS LaunchAgent)."""
    if platform.system() != "Darwin":
        click.echo("autostart is only supported on macOS")
        return

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / "com.optimusprime.menubar.plist"

    venv_py = Path.home() / ".optimusprime" / "venv" / "bin" / "python3"
    log_path = Path.home() / ".optimusprime" / "menubar.log"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.optimusprime.menubar</string>
    <key>ProgramArguments</key>
    <array>
        <string>{venv_py}</string>
        <string>{_MACOS_SCRIPT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""
    plist_path.write_text(plist_content)
    try:
        subprocess.run(
            ["launchctl", "load", str(plist_path)],
            check=False, capture_output=True,
        )
    except Exception:
        pass
    click.echo("⚡ OptimusPrime will start at login")
    click.echo(f"  Plist: {plist_path}")
