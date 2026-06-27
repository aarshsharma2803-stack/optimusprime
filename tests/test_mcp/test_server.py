"""Tests for MCP server tool functions.

Loads server.py with mocked mcp SDK so tests run without pip install mcp.
Tests the underlying Python logic directly — not the MCP wire protocol.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SERVER_PATH = _REPO_ROOT / "mcp" / "server.py"


def _load_server(monkeypatch):
    """Load mcp/server.py with mocked mcp SDK. Returns the module."""
    # Patch mcp SDK before import
    mock_mcp = MagicMock()
    mock_fastmcp_cls = MagicMock(return_value=MagicMock())
    mock_mcp.server.fastmcp.FastMCP = mock_fastmcp_cls

    # The @mcp.tool() decorator must return the function unchanged
    mock_mcp_instance = mock_fastmcp_cls.return_value
    mock_mcp_instance.tool.return_value = lambda f: f

    monkeypatch.setitem(sys.modules, "mcp", mock_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", mock_mcp.server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", mock_mcp.server.fastmcp)

    # Ensure src/ is on path
    src = str(_REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    spec = importlib.util.spec_from_file_location("mcp_server_under_test", _SERVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def server_mod(monkeypatch):
    return _load_server(monkeypatch)


# ── 1. get_contract() returns correct fields ─────────────────────────────

def test_get_contract_returns_fields(server_mod, op_dir, monkeypatch):
    monkeypatch.setattr(server_mod, "_op_dir", lambda: op_dir)
    result = server_mod.get_contract()
    assert result["status"] == "ok"
    assert "Build the OptimusPrime" in result["goal"]
    assert isinstance(result["in_scope_files"], list)
    assert isinstance(result["out_of_scope_files"], list)
    assert result["agent_id"] == "main"


# ── 2. get_contract() with no contract → no_contract status ──────────────

def test_get_contract_missing(server_mod, op_dir, monkeypatch):
    (op_dir / "contract.json").unlink(missing_ok=True)
    monkeypatch.setattr(server_mod, "_op_dir", lambda: op_dir)
    result = server_mod.get_contract()
    assert result["status"] == "no_contract"
    assert "message" in result


# ── 3. search_decisions("atomic") → ranked results ───────────────────────

def test_search_decisions_ranked(server_mod, op_dir, monkeypatch):
    monkeypatch.setattr(server_mod, "_op_dir", lambda: op_dir)
    result = server_mod.search_decisions("atomic")
    assert result["status"] == "ok"
    assert result["total_indexed"] >= 10
    assert len(result["results"]) >= 1
    assert "atomic" in result["results"][0]["body"].lower()


# ── 4. get_snapshot() parses all sections correctly ──────────────────────

def test_get_snapshot_parses_sections(server_mod, op_dir, monkeypatch):
    monkeypatch.setattr(server_mod, "_op_dir", lambda: op_dir)
    result = server_mod.get_snapshot()
    assert result["status"] == "ok"
    assert "Build the OptimusPrime" in result.get("goal", "") or result.get("raw_snapshot", "")
    assert "raw_snapshot" in result
    assert "## Goal" in result["raw_snapshot"]


# ── 5. get_attempts() returns last N ─────────────────────────────────────

def test_get_attempts_last_n(server_mod, op_dir, monkeypatch):
    monkeypatch.setattr(server_mod, "_op_dir", lambda: op_dir)
    result = server_mod.get_attempts(last_n=2)
    assert result["status"] == "ok"
    assert result["count"] <= 2
    # Fixture has 3 attempts, asking for last 2
    assert len(result["attempts"]) <= 2


# ── 6. get_todos() returns open TODOs ────────────────────────────────────

def test_get_todos_returns_open(server_mod, op_dir, monkeypatch):
    monkeypatch.setattr(server_mod, "_op_dir", lambda: op_dir)
    result = server_mod.get_todos()
    assert result["status"] == "ok"
    assert result["open_count"] >= 1
    todos = result["todos"]
    assert any("utils.py" in t.get("body", "") or "scope-guard" in t.get("body", "") for t in todos)


# ── 7. get_cost() with no cost-log → no_cost_data ───────────────────────

def test_get_cost_missing(server_mod, op_dir, monkeypatch):
    (op_dir / "cost-log.json").unlink(missing_ok=True)
    monkeypatch.setattr(server_mod, "_op_dir", lambda: op_dir)
    result = server_mod.get_cost()
    assert result["status"] == "no_cost_data"


# ── 8. get_cost() with data → returns sessions + total ───────────────────

def test_get_cost_with_data(server_mod, op_dir, monkeypatch):
    cost_log = {"sessions": [
        {"session_id": "s1", "input_tokens": 10000, "output_tokens": 3000, "estimated_cost_usd": 0.075},
        {"session_id": "s2", "input_tokens": 8000, "output_tokens": 2500, "estimated_cost_usd": 0.06},
    ]}
    (op_dir / "cost-log.json").write_text(json.dumps(cost_log))
    monkeypatch.setattr(server_mod, "_op_dir", lambda: op_dir)
    result = server_mod.get_cost()
    assert result["status"] == "ok"
    assert result["session_count"] == 2
    total = result["total"]
    assert total["input_tokens"] == 18000
    assert total["output_tokens"] == 5500
    assert abs(total["estimated_cost_usd"] - 0.135) < 0.001


# ── 9. All tools handle missing .optimusprime/ gracefully ─────────────────

def test_all_tools_handle_no_op_dir(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "_op_dir", lambda: None)
    for fn in [
        lambda: server_mod.get_contract(),
        lambda: server_mod.search_decisions("test"),
        lambda: server_mod.get_snapshot(),
        lambda: server_mod.get_attempts(),
        lambda: server_mod.get_todos(),
        lambda: server_mod.get_cost(),
    ]:
        result = fn()
        assert isinstance(result, dict)
        assert result.get("status") in ("no_op_dir", "no_contract", "no_decisions",
                                         "no_snapshot", "no_attempts", "no_todos",
                                         "no_cost_data", "ok")


# ── 10. search_decisions top_k capped at 20 ──────────────────────────────

def test_search_decisions_top_k_capped(server_mod, op_dir, monkeypatch):
    monkeypatch.setattr(server_mod, "_op_dir", lambda: op_dir)
    result = server_mod.search_decisions("decision", top_k=100)
    assert result["status"] == "ok"
    assert len(result["results"]) <= 20
