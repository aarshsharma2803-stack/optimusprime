"""Tests for OptimusPrime install scripts."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_REMOTE_SH = REPO_ROOT / "install-remote.sh"


def test_install_remote_exists_and_valid_bash():
    assert INSTALL_REMOTE_SH.is_file(), "install-remote.sh not found"
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_REMOTE_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash -n install-remote.sh failed:\n{result.stderr}"


def test_install_sh_update_flag_recognized():
    content = INSTALL_SH.read_text()
    assert "--update" in content, "install.sh missing --update flag handling"
    # Also verify install.sh is syntactically valid bash
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash -n install.sh failed:\n{result.stderr}"


def test_install_sh_uninstall_flag_recognized():
    content = INSTALL_SH.read_text()
    assert "--uninstall" in content, "install.sh missing --uninstall flag handling"
    assert "MODE" in content, "install.sh missing MODE variable for flag dispatch"


def test_install_sh_progress_format():
    content = INSTALL_SH.read_text()
    # step() uses printf with %d/7 format
    assert "%d/7]" in content, \
        "install.sh missing [X/7] progress format in step() function"
    # Verify all 7 step() calls are present
    step_calls = [ln.strip() for ln in content.splitlines() if ln.strip().startswith("step ")]
    assert len(step_calls) == 7, \
        f"Expected 7 step() calls, found {len(step_calls)}: {step_calls}"


def test_install_sh_python_version_check():
    content = INSTALL_SH.read_text()
    assert "PYMAJ" in content, "install.sh missing PYMAJ version variable"
    assert "PYMIN" in content, "install.sh missing PYMIN version variable"
    # Must check minor < 8 to catch Python 3.7 and below
    assert "PYMIN" in content and '"8"' in content or "8 ]" in content or "lt 8" in content, \
        "install.sh missing Python 3.8 minimum version check"


def test_install_sh_post_install_verification():
    content = INSTALL_SH.read_text()
    assert "import optimusprime" in content, \
        "install.sh missing post-install package verification"
    assert "op --version" in content or '"op" --version' in content, \
        "install.sh missing op command verification"


def test_install_sh_uninstall_preserves_data():
    content = INSTALL_SH.read_text()
    assert "data is preserved" in content, \
        "install.sh --uninstall missing 'data is preserved' message"


def test_install_remote_contains_correct_repo_url():
    content = INSTALL_REMOTE_SH.read_text()
    assert "aarshsharma2803-stack/optimusprime" in content, \
        "install-remote.sh missing correct GitHub repo URL"
