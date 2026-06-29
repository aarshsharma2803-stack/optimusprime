#!/usr/bin/env python3
"""OptimusPrime macOS menu bar companion app.

Requires: pip install rumps
Shows live session status in the macOS menu bar.
Updates every 2 seconds by reading .optimusprime/.

Usage: python3 optimusprime_menubar.py
       (or via: op menubar start)
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import rumps
except ImportError:
    print("ERROR: 'rumps' not installed. Run: pip install rumps", file=sys.stderr)
    sys.exit(1)

# Add src/ to path so we can import optimusprime package
_MENUBAR_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MENUBAR_DIR.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from optimusprime.menubar_data import MenuBarData  # noqa: E402

_VERSION = "v2.1.1"


class OptimusPrimeApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("⚡OP", quit_button=None)
        self._mdata = MenuBarData()
        self._lock = threading.Lock()
        # Build initial menu skeleton
        self._setup_menu()
        # Background refresh
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop, daemon=True
        )
        self._refresh_thread.start()

    # ------------------------------------------------------------------
    # Menu construction
    # ------------------------------------------------------------------

    def _setup_menu(self) -> None:
        self.menu = [
            rumps.MenuItem(f"⚡ OptimusPrime {_VERSION}"),
            rumps.separator,
            rumps.MenuItem("🎯 No active project"),
            rumps.separator,
            rumps.MenuItem("💬 Tokens: ~0"),
            rumps.MenuItem("📝 Decisions: 0"),
            rumps.MenuItem("🔁 Loops: ✅ 0"),
            rumps.separator,
            rumps.MenuItem("🤖 Skills: standby"),
            rumps.separator,
            rumps.MenuItem("Open Dashboard", callback=self.open_dashboard),
            rumps.MenuItem("Run Autopilot", callback=self.run_autopilot),
            rumps.MenuItem("View Decisions", callback=self.view_decisions),
            rumps.MenuItem("🔄 Refresh", callback=self.refresh_now),
            rumps.separator,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

    # ------------------------------------------------------------------
    # Refresh loop
    # ------------------------------------------------------------------

    def _refresh_loop(self) -> None:
        while True:
            try:
                self._mdata.load()
                self._update_display()
            except Exception:
                pass
            time.sleep(2)

    def _update_display(self) -> None:
        with self._lock:
            data = self._mdata.data
            self.title = self._mdata.title()

            # Goal
            goal = data.get("goal", "No active project")
            self.menu["🎯 No active project"].title = f"🎯 {goal}"

            # Tokens
            tokens = data.get("tokens", 0)
            cost = data.get("cost", 0.0)
            tok_str = f"~{tokens:,}" if tokens else "~0"
            self.menu["💬 Tokens: ~0"].title = f"💬 Tokens: {tok_str} (~${cost:.4f})"

            # Decisions
            dec = data.get("decision_count", 0)
            self.menu["📝 Decisions: 0"].title = f"📝 Decisions: {dec}"

            # Loops
            loops = data.get("loop_streak", 0)
            loop_icon = "⚠️" if loops >= 2 else "✅"
            self.menu["🔁 Loops: ✅ 0"].title = f"🔁 Loops: {loop_icon} {loops}"

            # Skills summary
            skills = data.get("skills", {})
            active = [n for n, m in skills.items() if m == "auto"]
            skills_str = f"ACTIVE: {', '.join(active[:3])}" if active else "standby"
            self.menu["🤖 Skills: standby"].title = f"🤖 Skills: {skills_str}"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @rumps.clicked("Open Dashboard")
    def open_dashboard(self, _: rumps.MenuItem) -> None:
        subprocess.Popen(
            ["bash", "-c", "op watch"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @rumps.clicked("Run Autopilot")
    def run_autopilot(self, _: rumps.MenuItem) -> None:
        subprocess.Popen(
            ["bash", "-c",
             "op autopilot > /tmp/op-autopilot.txt && open -a Terminal /tmp/op-autopilot.txt"],
        )

    @rumps.clicked("View Decisions")
    def view_decisions(self, _: rumps.MenuItem) -> None:
        subprocess.Popen(
            ["bash", "-c",
             "op decision list --last 20 > /tmp/op-decisions.txt"
             " && open -a Terminal /tmp/op-decisions.txt"],
        )

    @rumps.clicked("🔄 Refresh")
    def refresh_now(self, _: rumps.MenuItem) -> None:
        self._mdata.load()
        self._update_display()

    def quit_app(self, _: rumps.MenuItem) -> None:
        rumps.quit_application()


if __name__ == "__main__":
    OptimusPrimeApp().run()
