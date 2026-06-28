"""Tests for src/optimusprime/codebase_map.py — minimum 15 tests."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from optimusprime.codebase_map import (
    CodebaseEntry,
    CodebaseMap,
    _extract_entries,
    _parse_package_json,
    _parse_pyproject,
    _parse_requirements,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def op_dir(tmp_path):
    d = tmp_path / ".optimusprime"
    d.mkdir()
    return d


@pytest.fixture
def project_root(tmp_path):
    return tmp_path


@pytest.fixture
def py_project(tmp_path, op_dir):
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "utils.py").write_text(
        "def parse_date(date_str: str):\n    pass\n\nclass Config:\n    pass\n"
    )
    (tmp_path / "src" / "auth.py").write_text(
        "def validate_token(token: str):\n    pass\n"
    )
    return tmp_path


@pytest.fixture
def ts_project(tmp_path, op_dir):
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "utils.ts").write_text(
        "export function formatDate(d: Date): string { return ''; }\n"
        "export class UserService { }\n"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# _scan_utilities — Python
# ---------------------------------------------------------------------------

def test_scan_utilities_finds_python_functions(py_project, op_dir):
    cm = CodebaseMap(py_project, op_dir)
    utils = cm._scan_utilities()
    assert "parse_date" in utils
    assert "validate_token" in utils


def test_scan_utilities_finds_python_classes(py_project, op_dir):
    cm = CodebaseMap(py_project, op_dir)
    utils = cm._scan_utilities()
    assert "Config" in utils


def test_scan_utilities_finds_ts_functions(ts_project, op_dir):
    cm = CodebaseMap(ts_project, op_dir)
    utils = cm._scan_utilities()
    assert "formatDate" in utils


def test_scan_utilities_skips_node_modules(tmp_path, op_dir):
    nm = tmp_path / "node_modules" / "lodash"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("function cloneDeep() {}\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export function myFunc() {}\n")
    cm = CodebaseMap(tmp_path, op_dir)
    utils = cm._scan_utilities()
    assert "cloneDeep" not in utils
    assert "myFunc" in utils


def test_scan_utilities_skips_pycache(tmp_path, op_dir):
    pc = tmp_path / "__pycache__"
    pc.mkdir()
    (pc / "utils.pyc").write_text("def cached_func(): pass\n")
    (tmp_path / "real.py").write_text("def real_func(): pass\n")
    cm = CodebaseMap(tmp_path, op_dir)
    utils = cm._scan_utilities()
    assert "cached_func" not in utils
    assert "real_func" in utils


def test_scan_utilities_limited_to_500(tmp_path, op_dir):
    (tmp_path / "big.py").write_text(
        "\n".join(f"def func_{i}(): pass" for i in range(600))
    )
    cm = CodebaseMap(tmp_path, op_dir)
    utils = cm._scan_utilities()
    assert len(utils) <= 500


# ---------------------------------------------------------------------------
# _scan_dependencies
# ---------------------------------------------------------------------------

def test_reads_pyproject_toml(tmp_path, op_dir):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = [\n    "click>=8.0",\n    "httpx",\n]\n'
    )
    cm = CodebaseMap(tmp_path, op_dir)
    installed, dev = cm._scan_dependencies()
    assert "click" in installed
    assert "httpx" in installed


def test_reads_package_json(tmp_path, op_dir):
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {"react": "^18.0", "axios": "1.0"},
        "devDependencies": {"jest": "29.0"},
    }))
    cm = CodebaseMap(tmp_path, op_dir)
    installed, dev = cm._scan_dependencies()
    assert "react" in installed
    assert "jest" in dev


def test_returns_empty_for_missing_files(tmp_path, op_dir):
    cm = CodebaseMap(tmp_path, op_dir)
    installed, dev = cm._scan_dependencies()
    assert installed == []
    assert dev == []


def test_strips_version_specifiers(tmp_path, op_dir):
    (tmp_path / "requirements.txt").write_text("requests>=2.28\npandas==2.0\n")
    cm = CodebaseMap(tmp_path, op_dir)
    installed, _ = cm._scan_dependencies()
    # No version specifier characters in names
    for dep in installed:
        assert ">=" not in dep and "==" not in dep


# ---------------------------------------------------------------------------
# _detect_language
# ---------------------------------------------------------------------------

def test_python_project_detection(tmp_path, op_dir):
    for i in range(5):
        (tmp_path / f"file{i}.py").write_text("pass\n")
    cm = CodebaseMap(tmp_path, op_dir)
    assert cm._detect_language() == "python"


def test_typescript_project_detection(tmp_path, op_dir):
    for i in range(5):
        (tmp_path / f"file{i}.ts").write_text("const x = 1;\n")
    cm = CodebaseMap(tmp_path, op_dir)
    assert cm._detect_language() == "typescript"


def test_mixed_project_detection(tmp_path, op_dir):
    for i in range(3):
        (tmp_path / f"file{i}.py").write_text("pass\n")
    for i in range(3):
        (tmp_path / f"file{i}.ts").write_text("const x = 1;\n")
    cm = CodebaseMap(tmp_path, op_dir)
    assert cm._detect_language() == "mixed"


# ---------------------------------------------------------------------------
# get_relevant_for_file
# ---------------------------------------------------------------------------

def test_get_relevant_returns_at_most_10(py_project, op_dir):
    cm = CodebaseMap(py_project, op_dir)
    cm._map = {
        "utilities": {
            f"func_{i}": {"file": f"src/utils.py", "line": i, "type": "function",
                          "signature": f"def func_{i}():"}
            for i in range(20)
        }
    }
    result = cm.get_relevant_for_file("src/utils.py")
    assert len(result) <= 10


def test_get_relevant_prefers_same_directory(py_project, op_dir):
    cm = CodebaseMap(py_project, op_dir)
    cm._map = {
        "utilities": {
            "same_dir_func": {"file": "src/utils.py", "line": 1, "type": "function",
                              "signature": "def same_dir_func():"},
            "other_dir_func": {"file": "lib/other.py", "line": 1, "type": "function",
                               "signature": "def other_dir_func():"},
        }
    }
    result = cm.get_relevant_for_file("src/auth.py")
    # same_dir_func should appear (same src/ dir)
    assert "same_dir_func" in result


def test_get_relevant_returns_empty_for_unknown(tmp_path, op_dir):
    cm = CodebaseMap(tmp_path, op_dir)
    cm._map = {}
    result = cm.get_relevant_for_file("nonexistent/path.py")
    assert result == {}


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------

def test_is_stale_when_file_missing(tmp_path, op_dir):
    cm = CodebaseMap(tmp_path, op_dir)
    assert cm.is_stale() is True


def test_is_stale_when_file_is_old(tmp_path, op_dir):
    map_path = op_dir / "codebase-map.json"
    map_path.write_text(json.dumps({"built_at": "2020-01-01T00:00:00Z"}))
    # Force old mtime
    old_time = time.time() - (25 * 3600)
    import os
    os.utime(str(map_path), (old_time, old_time))
    cm = CodebaseMap(tmp_path, op_dir)
    assert cm.is_stale() is True


def test_is_stale_false_when_fresh(tmp_path, op_dir):
    map_path = op_dir / "codebase-map.json"
    map_path.write_text(json.dumps({"built_at": "2026-06-28T00:00:00Z", "utilities": {}}))
    cm = CodebaseMap(tmp_path, op_dir)
    assert cm.is_stale() is False


# ---------------------------------------------------------------------------
# _detect_never_use
# ---------------------------------------------------------------------------

def test_detects_rejected_dep_from_decisions(tmp_path, op_dir):
    (op_dir / "decisions.md").write_text(
        "[2026-06-27T10:00:00Z] [agent:main] DECISION: rejected requests — use httpx instead\n"
    )
    cm = CodebaseMap(tmp_path, op_dir)
    never = cm._detect_never_use(["httpx", "click"])
    # Should include requests since it was rejected
    assert any("requests" in entry for entry in never)


def test_cross_references_installed_deps(tmp_path, op_dir):
    cm = CodebaseMap(tmp_path, op_dir)
    # requests is rejected alternative when httpx is installed
    never = cm._detect_never_use(["httpx", "click"])
    assert any("requests" in entry for entry in never)
