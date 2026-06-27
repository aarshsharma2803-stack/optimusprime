"""Tests for ecosystem/installer.py — at least 6 scenarios."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "ecosystem"))

from installer import SkillInstaller, _load_skills_data, _parse_source


# ── 1. list_available() returns all 5 registry skills ────────────────────

def test_list_available_returns_five(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    installer = SkillInstaller(op_dir=op_dir)
    available = installer.list_available()
    assert len(available) == 5
    names = {s["name"] for s in available}
    assert names == {"superpowers", "gstack", "ui-ux-pro-max", "caveman", "ponytail"}


# ── 2. list_installed() empty when nothing installed ─────────────────────

def test_list_installed_empty(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    installer = SkillInstaller(op_dir=op_dir)
    assert installer.list_installed() == []


# ── 3. install() with mocked GitHub → creates skills.json entry ──────────

def test_install_mocked_github(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    installer = SkillInstaller(op_dir=op_dir)

    fake_skill_content = "---\nname: caveman\n---\nDrop filler. Be concise.\n"

    with patch("installer._github_latest_version", return_value=("1.2.3", "v1.2.3")), \
         patch("installer._fetch_skill_md", return_value=fake_skill_content):
        result = installer.install("caveman", mode="auto")

    assert result is True
    skills_data = _load_skills_data(op_dir)
    installed = skills_data["installed"]
    assert "caveman" in installed
    entry = installed["caveman"]
    assert entry["installed_version"] == "1.2.3"
    assert entry["mode"] == "auto"
    assert entry["source"] == "github:JuliusBrussee/caveman"


# ── 4. install() idempotent → second call doesn't duplicate ──────────────

def test_install_idempotent(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    installer = SkillInstaller(op_dir=op_dir)

    with patch("installer._github_latest_version", return_value=("1.2.3", "v1.2.3")), \
         patch("installer._fetch_skill_md", return_value="---\nname: caveman\n---\n"):
        installer.install("caveman")
        result = installer.install("caveman")  # second call

    assert result is True
    skills_data = _load_skills_data(op_dir)
    # Should still be only one entry
    assert len(skills_data["installed"]) == 1


# ── 5. uninstall() removes entry from skills.json ────────────────────────

def test_uninstall_removes_entry(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    installer = SkillInstaller(op_dir=op_dir)

    with patch("installer._github_latest_version", return_value=("1.2.3", "v1.2.3")), \
         patch("installer._fetch_skill_md", return_value="---\nname: caveman\n---\n"):
        installer.install("caveman")

    result = installer.uninstall("caveman")
    assert result is True
    skills_data = _load_skills_data(op_dir)
    assert "caveman" not in skills_data["installed"]


# ── 6. install() network failure → returns False, no crash ───────────────

def test_install_network_failure(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    installer = SkillInstaller(op_dir=op_dir)

    with patch("installer._github_latest_version", return_value=("main", "main")), \
         patch("installer._fetch_skill_md", return_value=None):  # None = download failed
        result = installer.install("caveman")

    assert result is False
    skills_data = _load_skills_data(op_dir)
    assert "caveman" not in skills_data.get("installed", {})


# ── 7. install() unknown skill → returns False ───────────────────────────

def test_install_unknown_skill(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    installer = SkillInstaller(op_dir=op_dir)
    result = installer.install("no-such-skill-ever")
    assert result is False


# ── 8. list_available() marks installed skills correctly ─────────────────

def test_list_available_marks_installed(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    installer = SkillInstaller(op_dir=op_dir)

    with patch("installer._github_latest_version", return_value=("1.0.0", "v1.0.0")), \
         patch("installer._fetch_skill_md", return_value="---\nname: ponytail\n---\n"):
        installer.install("ponytail")

    available = installer.list_available()
    ponytail = next(s for s in available if s["name"] == "ponytail")
    caveman = next(s for s in available if s["name"] == "caveman")
    assert ponytail["installed"] is True
    assert caveman["installed"] is False
