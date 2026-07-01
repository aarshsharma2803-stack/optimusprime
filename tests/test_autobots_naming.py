"""Tests for Auto Bots naming (Issue 16)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load_module(rel: str):
    p = _ROOT / rel
    spec = importlib.util.spec_from_file_location(p.stem.replace("-", "_"), p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads((_ROOT / "ecosystem" / "registry.json").read_text())["skills"]


# ---- 1. registry.json has bot_name for all 5 skills -----------------------

def test_registry_all_skills_have_bot_name(registry):
    for name, info in registry.items():
        assert "bot_name" in info, f"{name} missing bot_name"
        assert info["bot_name"], f"{name} bot_name is empty"


# ---- 2. bot_names follow "X Bot" convention --------------------------------

def test_registry_bot_names_end_with_bot(registry):
    for name, info in registry.items():
        assert info["bot_name"].endswith("Bot"), (
            f"{name} bot_name '{info['bot_name']}' should end with 'Bot'"
        )


# ---- 3. menubar_data loads bot_names from registry -------------------------

def test_menubar_data_loads_bot_names(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    # Fake skills.json with two installed skills
    (op_dir / "skills.json").write_text(json.dumps({
        "installed": {
            "caveman": {"mode": "auto"},
            "ponytail": {"mode": "auto"},
        }
    }))
    mod = importlib.util.spec_from_file_location(
        "menubar_data", _ROOT / "src" / "optimusprime" / "menubar_data.py"
    )
    mmod = importlib.util.module_from_spec(mod)
    mod.loader.exec_module(mmod)
    mbd = mmod.MenuBarData(op_dir)
    mbd.load()
    assert "bot_names" in mbd.data
    assert mbd.data["bot_names"].get("caveman") == "Caveman Bot"
    assert mbd.data["bot_names"].get("ponytail") == "Ponytail Bot"


# ---- 4. watch.py has AUTO BOTS panel label ---------------------------------

def test_watch_has_auto_bots_panel():
    src = (_ROOT / "src" / "optimusprime" / "cli" / "commands" / "watch.py").read_text()
    assert "AUTO BOTS" in src


# ---- 5. watch.py uses 🤖 {bot_name} ({name}) format -----------------------

def test_watch_displays_bot_name_format():
    src = (_ROOT / "src" / "optimusprime" / "cli" / "commands" / "watch.py").read_text()
    assert "bot_name" in src
    assert "🤖" in src


# ---- 6. skills.py shows 🤖 AUTO BOTS header and bot_name label -------------

def test_skills_command_shows_auto_bots_format():
    src = (_ROOT / "src" / "optimusprime" / "cli" / "commands" / "skills.py").read_text()
    assert "AUTO BOTS" in src
    assert "bot_name" in src
    assert "🤖" in src
