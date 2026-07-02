"""Tests for .claude-plugin/plugin.json commands array."""

from __future__ import annotations

import json
from pathlib import Path

_PLUGIN_JSON = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"


def _load_plugin() -> dict:
    return json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))


def test_plugin_json_is_valid():
    data = _load_plugin()
    assert isinstance(data, dict)
    assert "name" in data


def test_commands_array_has_5_entries():
    data = _load_plugin()
    commands = data.get("commands", [])
    assert len(commands) == 5, f"Expected 5 commands, got {len(commands)}"


def test_each_command_has_required_fields():
    data = _load_plugin()
    for cmd in data.get("commands", []):
        assert "name" in cmd, f"Missing 'name' in {cmd}"
        assert "description" in cmd, f"Missing 'description' in {cmd}"
        assert "prompt" in cmd, f"Missing 'prompt' in {cmd}"
        assert len(cmd["description"]) > 10
        assert len(cmd["prompt"]) > 5


def test_all_command_names_start_with_op():
    data = _load_plugin()
    for cmd in data.get("commands", []):
        assert cmd["name"].startswith("op-"), f"Command '{cmd['name']}' does not start with 'op-'"
