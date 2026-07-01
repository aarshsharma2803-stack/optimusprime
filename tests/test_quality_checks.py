"""Tests for post-write-analyzer.py Check G (SOLID, security, SQL injection)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ANALYZER = Path(__file__).resolve().parent.parent / "hooks" / "post" / "post-write-analyzer.py"


def _load():
    spec = importlib.util.spec_from_file_location("post_write_analyzer", _ANALYZER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


# ---- G1: Function too long (SOLID) ----------------------------------------

def test_g1_flags_long_python_function(mod):
    lines = ["    x = 1\n"] * 35
    content = "def process_data(data):\n" + "".join(lines)
    flags = mod._check_quality(content, "src/processor.py")
    assert any("SOLID" in f for f in flags)


def test_g1_allows_short_function(mod):
    content = "def parse(x):\n    return int(x)\n"
    flags = mod._check_quality(content, "src/parser.py")
    assert not any("SOLID" in f for f in flags)


# ---- G2: Hardcoded secrets (SECURITY) -------------------------------------

def test_g2_flags_hardcoded_password(mod):
    content = 'password = "supersecret123"\n'
    flags = mod._check_quality(content, "src/config.py")
    assert any("SECURITY" in f and "credential" in f for f in flags)


def test_g2_flags_hardcoded_api_key(mod):
    content = 'api_key = "sk-1234567890abcdef"\n'
    flags = mod._check_quality(content, "src/client.py")
    assert any("SECURITY" in f for f in flags)


def test_g2_allows_env_var_pattern(mod):
    content = 'api_key = os.environ["API_KEY"]\n'
    flags = mod._check_quality(content, "src/client.py")
    assert not any("credential" in f for f in flags)


# ---- G3: SQL injection (SECURITY) -----------------------------------------

def test_g3_flags_sql_concatenation(mod):
    content = 'query = "SELECT * FROM users WHERE id = " + user_id\n'
    flags = mod._check_quality(content, "src/db.py")
    assert any("SQL" in f or "parameterized" in f for f in flags)


def test_g3_flags_fstring_sql(mod):
    content = 'sql = f"SELECT * FROM orders WHERE user_id = {uid}"\n'
    flags = mod._check_quality(content, "src/repo.py")
    assert any("SQL" in f or "injection" in f for f in flags)


def test_g3_allows_parameterized_query(mod):
    content = 'cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))\n'
    flags = mod._check_quality(content, "src/db.py")
    assert not any("SQL" in f for f in flags)
