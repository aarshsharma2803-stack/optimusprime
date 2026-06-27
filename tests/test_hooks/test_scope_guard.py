"""Tests for hooks/pre/scope-guard.py — at least 8 scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import make_pretooluse, run_hook

_HOOK = Path(__file__).resolve().parent.parent.parent / "hooks" / "pre" / "scope-guard.py"


def _run(stdin_data, cwd):
    return run_hook(_HOOK, stdin_data, cwd)


# ── 1. No contract → exit 0 ────────────────────────────────────────────────

def test_no_contract_exits_zero(tmp_path):
    """Missing contract.json → pass silently."""
    (tmp_path / ".optimusprime").mkdir()
    stdout, stderr, rc = _run(
        make_pretooluse("Write", {"file_path": "secrets/key.pem"}),
        cwd=tmp_path,
    )
    assert rc == 0
    assert stdout.strip() == ""


# ── 2. In-scope file → exit 0 ──────────────────────────────────────────────

def test_in_scope_file_passes(tmp_optimusprime_dir):
    stdout, _, rc = _run(
        make_pretooluse("Write", {"file_path": "src/optimusprime/utils.py"}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 0
    assert stdout.strip() == ""


# ── 3. Out-of-scope exact file → exit 2 + JSON block ──────────────────────

def test_out_of_scope_file_blocked(tmp_optimusprime_dir):
    stdout, stderr, rc = _run(
        make_pretooluse("Write", {"file_path": ".env"}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 2
    decision = json.loads(stdout.strip())
    assert decision["decision"] == "block"
    assert "OPTIMUSPRIME" in decision["reason"]


# ── 4. Glob pattern blocks matching file ──────────────────────────────────

def test_glob_pattern_blocks(tmp_optimusprime_dir):
    """'*.key' pattern should block 'server.key'."""
    stdout, _, rc = _run(
        make_pretooluse("Write", {"file_path": "server.key"}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 2
    decision = json.loads(stdout.strip())
    assert decision["decision"] == "block"


# ── 5. Bash targeting out-of-scope path → exit 2 ─────────────────────────

def test_bash_oob_path_blocked(tmp_optimusprime_dir):
    stdout, _, rc = _run(
        make_pretooluse("Bash", {"command": "cat secrets/api_key.pem"}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 2
    decision = json.loads(stdout.strip())
    assert decision["decision"] == "block"


# ── 6. Malformed contract.json → exit 0 silently ─────────────────────────

def test_malformed_contract_exits_zero(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    (op_dir / "contract.json").write_text("{ not valid json }", encoding="utf-8")
    stdout, _, rc = _run(
        make_pretooluse("Write", {"file_path": "secrets/key.pem"}),
        cwd=tmp_path,
    )
    assert rc == 0
    assert stdout.strip() == ""


# ── 7. Missing .optimusprime/ altogether → exit 0 ────────────────────────

def test_missing_op_dir_exits_zero(tmp_path):
    """No .optimusprime/ directory → no contract → pass silently."""
    stdout, _, rc = _run(
        make_pretooluse("Write", {"file_path": "secrets/key.pem"}),
        cwd=tmp_path,
    )
    assert rc == 0


# ── 8. Directory prefix out_of_scope blocks nested file ───────────────────

def test_directory_prefix_blocks(tmp_optimusprime_dir):
    """'secrets/**' should block 'secrets/nested/file.txt'."""
    stdout, _, rc = _run(
        make_pretooluse("Edit", {"file_path": "secrets/nested/file.txt"}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 2
    decision = json.loads(stdout.strip())
    assert decision["decision"] == "block"


# ── 9. MultiEdit with one OOB path → exit 2 ──────────────────────────────

def test_multiedit_oob_blocked(tmp_optimusprime_dir):
    """MultiEdit uses file_path from tool_input."""
    stdout, _, rc = _run(
        make_pretooluse("MultiEdit", {"file_path": "secrets/credentials.txt", "edits": []}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 2


# ── 10. Non-write tool → exit 0 (guard only watches writes) ───────────────

def test_read_tool_always_passes(tmp_optimusprime_dir):
    stdout, _, rc = _run(
        make_pretooluse("Read", {"file_path": "secrets/key.pem"}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 0
    assert stdout.strip() == ""


# ── 11. .pem extension (glob *.pem) → exit 2 ──────────────────────────────

def test_pem_extension_blocked(tmp_optimusprime_dir):
    stdout, _, rc = _run(
        make_pretooluse("Write", {"file_path": "certs/server.pem"}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 2
