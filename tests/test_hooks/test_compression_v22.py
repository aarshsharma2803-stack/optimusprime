"""Tests for output-compressor.py passes 4, 5, 6."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_COMPRESSOR = Path(__file__).resolve().parent.parent.parent / "hooks" / "post" / "output-compressor.py"


def _load():
    spec = importlib.util.spec_from_file_location("output_compressor", _COMPRESSOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


# ---- Pass 5: tool success messages ----------------------------------------

def test_pass5_strips_successfully_created(mod):
    text = "Successfully created the auth module with 42 lines of code.\n\nDone."
    compressed, removed = mod._compress(text)
    assert "Successfully created" not in compressed
    assert removed > 0


def test_pass5_strips_i_have_successfully(mod):
    text = "I have successfully implemented the feature you requested.\n"
    compressed, removed = mod._compress(text)
    assert "I have successfully" not in compressed


def test_pass5_strips_file_has_been_created(mod):
    text = "The file has been created with all the logic you requested.\n"
    compressed, removed = mod._compress(text)
    assert "The file has been created" not in compressed


def test_pass5_keeps_code_untouched(mod):
    text = (
        "```python\n"
        "def create_user():\n"
        "    # Successfully created in db\n"
        "    return User()\n"
        "```\n"
    )
    compressed, _ = mod._compress(text)
    # Code block must remain intact
    assert "def create_user" in compressed


# ---- Pass 4: heavy explanation compression ---------------------------------

def test_pass4_triggers_on_no_code(mod):
    """11 prose lines (no code) → heavy_explanation=True → first-sentence kept."""
    text = "\n".join([
        "Connection pooling maintains open database connections for reuse.",
        "The pool allocates connections to incoming requests on demand.",
        "A request returns its connection to the pool on completion.",
        "This eliminates reconnect overhead for each database query.",
        "Pool size directly impacts throughput under sustained load.",
        "Idle timeout controls automatic removal of stale connections.",
        "Health checks run periodically to detect broken connections.",
        "Most frameworks expose pool sizing via standard configuration.",
        "A small pool causes queuing; a large pool wastes resources.",
        "Benchmarking reveals optimal sizing for production traffic.",
        "Connection reuse also reduces server-side resource consumption.",
    ]) + "\n"
    compressed, removed = mod._compress(text)
    assert removed > 0


def test_pass4_preserves_keep_signals(mod):
    """Paragraphs with 'you should', 'warning', etc. survive compression."""
    text = (
        "```python\nresult = x * 2\n```\n\n"
        "You must configure the timeout before deploying to production. "
        "If you skip this step the service will hang on startup. "
        "Warning: default timeout is 0 which means no limit and can cause hangs.\n"
    )
    compressed, _ = mod._compress(text)
    # Warning/you must signals → keep_signals → preserved
    assert "Warning" in compressed or "must" in compressed


# ---- Pass 6: redundant code comment stripping ------------------------------

def test_pass6_strips_redundant_comment(mod):
    text = (
        "```python\n"
        "# get user by id\n"
        "def get_user_by_id(user_id):\n"
        "    return db.get(user_id)\n"
        "```\n"
    )
    compressed, removed = mod._compress(text)
    assert "# get user by id" not in compressed
    assert "def get_user_by_id" in compressed


def test_pass6_keeps_todo_comments(mod):
    text = (
        "```python\n"
        "# TODO: add retry logic\n"
        "def get_user(user_id):\n"
        "    return db.get(user_id)\n"
        "```\n"
    )
    compressed, _ = mod._compress(text)
    assert "TODO" in compressed


def test_pass6_keeps_important_comments(mod):
    text = (
        "```python\n"
        "# NOTE: must call before any DB operation\n"
        "def initialize_db(conn):\n"
        "    conn.connect()\n"
        "```\n"
    )
    compressed, _ = mod._compress(text)
    assert "NOTE" in compressed
