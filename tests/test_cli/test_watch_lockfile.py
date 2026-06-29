"""Tests for op watch PID lockfile (Issue 3)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from optimusprime.cli.commands.watch import (
    LOCKFILE,
    check_single_instance,
    cleanup_lockfile,
)
from optimusprime.cli.op import cli


@pytest.fixture(autouse=True)
def clean_lockfile():
    """Always remove lockfile before and after each test."""
    LOCKFILE.unlink(missing_ok=True)
    yield
    LOCKFILE.unlink(missing_ok=True)


@pytest.fixture
def op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()
    return op


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_first_invocation_writes_pid_lockfile():
    """check_single_instance() writes PID to lockfile when not already running."""
    assert not LOCKFILE.exists()
    check_single_instance()
    assert LOCKFILE.exists()
    pid = int(LOCKFILE.read_text().strip())
    assert pid == os.getpid()


def test_second_invocation_detects_running():
    """If lockfile contains our own PID, check_single_instance exits 0 with message."""
    LOCKFILE.write_text(str(os.getpid()))
    with pytest.raises(SystemExit) as exc_info:
        check_single_instance()
    assert exc_info.value.code == 0


def test_stale_lockfile_cleaned_up():
    """If lockfile has PID of dead process, it is removed and we proceed."""
    # PID 999999 almost certainly doesn't exist
    LOCKFILE.write_text("999999")
    # Should not raise SystemExit — stale file gets cleaned up
    try:
        check_single_instance()
    except SystemExit:
        pytest.fail("Should not exit on stale lockfile")
    # After cleanup + rewrite, lockfile should have our PID
    assert LOCKFILE.exists()
    assert int(LOCKFILE.read_text().strip()) == os.getpid()


def test_cleanup_removes_lockfile():
    """cleanup_lockfile() deletes the lockfile."""
    LOCKFILE.write_text(str(os.getpid()))
    assert LOCKFILE.exists()
    cleanup_lockfile()
    assert not LOCKFILE.exists()


def test_cleanup_is_idempotent():
    """cleanup_lockfile() is safe to call even when lockfile absent."""
    assert not LOCKFILE.exists()
    cleanup_lockfile()  # must not raise
    assert not LOCKFILE.exists()
