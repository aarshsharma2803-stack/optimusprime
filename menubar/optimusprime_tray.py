#!/usr/bin/env python3
"""OptimusPrime Windows/Linux system tray companion app.

Requires: pip install pystray Pillow
Shows live session status in the system tray.
Updates every 2 seconds by reading .optimusprime/.

Usage: python3 optimusprime_tray.py
       (or via: op menubar start)
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    import pystray
except ImportError:
    print("ERROR: 'pystray' not installed. Run: pip install pystray", file=sys.stderr)
    sys.exit(1)

# Add src/ to path
_MENUBAR_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MENUBAR_DIR.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from optimusprime.menubar_data import MenuBarData  # noqa: E402

_VERSION = "v2.1.1"


def _make_icon():
    """Generate 64x64 tray icon. Dark background, red lightning bolt."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (64, 64), color=(5, 5, 15))
        draw = ImageDraw.Draw(img)
        # Lightning bolt polygon
        bolt = [(32, 4), (20, 36), (30, 36), (22, 60), (44, 28), (34, 28), (44, 4)]
        draw.polygon(bolt, fill=(204, 17, 17))
        return img
    except Exception:
        try:
            from PIL import Image
            return Image.new("RGB", (64, 64), color=(204, 17, 17))
        except Exception:
            return None


def _noop(*_: Any) -> None:
    pass


def _build_menu(mdata: MenuBarData, icon_holder: list) -> "pystray.Menu":
    data = mdata.data

    goal = data.get("goal", "No active project")
    tokens = data.get("tokens", 0)
    cost = data.get("cost", 0.0)
    tok_str = f"~{tokens:,}" if tokens else "~0"
    dec_count = data.get("decision_count", 0)
    loops = data.get("loop_streak", 0)
    cmp = data.get("compression", 0)
    skills = data.get("skills", {})
    active_skills = [n for n, m in skills.items() if m == "auto"]

    def open_dashboard(icon: Any, item: Any) -> None:
        subprocess.Popen(["op", "watch"], shell=(sys.platform == "win32"))

    def run_autopilot(icon: Any, item: Any) -> None:
        subprocess.Popen(["op", "autopilot"], shell=(sys.platform == "win32"))

    def view_decisions(icon: Any, item: Any) -> None:
        subprocess.Popen(
            ["op", "decision", "list", "--last", "20"],
            shell=(sys.platform == "win32"),
        )

    def refresh_now(icon: Any, item: Any) -> None:
        mdata.load()
        icon.title = mdata.title()
        icon.menu = _build_menu(mdata, icon_holder)

    def quit_app(icon: Any, item: Any) -> None:
        icon.stop()

    items: list = [
        pystray.MenuItem(f"⚡ OptimusPrime {_VERSION}", _noop, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Goal: {goal}", _noop, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Tokens: {tok_str} (~${cost:.4f})", _noop, enabled=False),
        pystray.MenuItem(f"Decisions: {dec_count}", _noop, enabled=False),
        pystray.MenuItem(f"Loops: {loops}", _noop, enabled=False),
    ]
    if cmp:
        items.append(pystray.MenuItem(f"Compression: {cmp:.0f}%", _noop, enabled=False))
    if active_skills:
        items.append(pystray.MenuItem(
            f"Skills: {', '.join(active_skills[:3])} ACTIVE", _noop, enabled=False
        ))
    items += [
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Dashboard", open_dashboard),
        pystray.MenuItem("Run Autopilot", run_autopilot),
        pystray.MenuItem("View Decisions", view_decisions),
        pystray.MenuItem("Refresh", refresh_now),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    ]
    return pystray.Menu(*items)


def main() -> None:
    mdata = MenuBarData()
    mdata.load()

    icon_img = _make_icon()
    if icon_img is None:
        print(
            "ERROR: Could not create icon. Install Pillow: pip install Pillow",
            file=sys.stderr,
        )
        sys.exit(1)

    icon_holder: list = [None]
    icon = pystray.Icon(
        "optimusprime",
        icon_img,
        title=mdata.title(),
        menu=_build_menu(mdata, icon_holder),
    )
    icon_holder[0] = icon

    def refresh_loop() -> None:
        while True:
            time.sleep(2)
            try:
                mdata.load()
                icon.title = mdata.title()
                icon.menu = _build_menu(mdata, icon_holder)
            except Exception:
                pass

    t = threading.Thread(target=refresh_loop, daemon=True)
    t.start()
    icon.run()


if __name__ == "__main__":
    main()
