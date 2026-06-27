"""Ecosystem skill updater — check and apply updates, rollback, pin versions.

Semver policy (enforced here):
  patch  (x.y.Z → x.y.Z+1): silent, auto-apply
  minor  (x.Y.z → x.Y+1.z): silent + log, auto-apply
  major  (X.y.z → X+1.y.z): notify only, NEVER auto-apply

Auto-updates NEVER happen mid-session — only called at SessionStart.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ECOSYSTEM_DIR = Path(__file__).resolve().parent
if str(_ECOSYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_ECOSYSTEM_DIR))

from installer import (
    SkillInstaller,
    _fetch_skill_md,
    _github_latest_version,
    _load_json_file,
    _load_registry,
    _load_skills_data,
    _parse_source,
    _save_skills_data,
    _utcnow,
    _write_json_atomic,
    INSTALL_BASE,
)


def _parse_semver(v: str) -> Tuple[int, int, int]:
    """Parse 'v1.2.3' or '1.2.3' → (1, 2, 3). Returns (0,0,0) on failure."""
    clean = v.strip().lstrip("v")
    parts = clean.split(".")
    try:
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except Exception:
        return (0, 0, 0)


def _update_type(current: str, latest: str) -> str:
    """Return 'none'|'patch'|'minor'|'major' comparing current → latest."""
    c = _parse_semver(current)
    l = _parse_semver(latest)
    if l <= c:
        return "none"
    if l[0] > c[0]:
        return "major"
    if l[1] > c[1]:
        return "minor"
    return "patch"


def _within_24h(iso_ts: str) -> bool:
    """Return True if timestamp is within the last 24 hours."""
    if not iso_ts:
        return False
    try:
        dt = datetime.fromisoformat(iso_ts.rstrip("Z")).replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt) < timedelta(hours=24)
    except Exception:
        return False


def _cache_path(op_dir: Optional[Path]) -> Optional[Path]:
    return op_dir / "skills-cache.json" if op_dir else None


def _load_cache(op_dir: Optional[Path]) -> Dict[str, Any]:
    path = _cache_path(op_dir)
    if not path:
        return {}
    data = _load_json_file(path)
    return data if data else {}


def _save_cache(op_dir: Optional[Path], data: Dict[str, Any]) -> None:
    path = _cache_path(op_dir)
    if path:
        _write_json_atomic(path, data)


def _update_log_path(op_dir: Optional[Path]) -> Optional[Path]:
    return op_dir / "skills-update-log.md" if op_dir else None


def _append_update_log(op_dir: Optional[Path], line: str) -> None:
    path = _update_log_path(op_dir)
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = _utcnow()
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
    except Exception:
        pass


class SkillUpdater:
    """Check and apply ecosystem skill updates according to semver policy."""

    def __init__(self, op_dir: Optional[Path] = None) -> None:
        self._op_dir = op_dir
        self._registry = _load_registry()
        self._installer = SkillInstaller(op_dir=op_dir)

    def check_updates(self, skills_json_path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
        """Return {skill_name: {current, latest, update_type}} for all installed skills.

        Throttled: skips GitHub API calls if last_check was within 24 hours.
        Returns {} silently on network failure.
        """
        op_dir = skills_json_path.parent if skills_json_path else self._op_dir
        skills_data = _load_skills_data(op_dir)
        installed = skills_data.get("installed", {})
        if not installed:
            return {}

        cache = _load_cache(op_dir)
        last_check = cache.get("last_check", "")
        if _within_24h(last_check):
            # Return from cache without hitting GitHub
            cached_updates = cache.get("updates", {})
            return cached_updates

        results: Dict[str, Dict[str, str]] = {}
        for skill_name, entry in installed.items():
            current_ver = entry.get("installed_version", "0.0.0")
            source = entry.get("source", "")
            _, owner, repo = _parse_source(source)
            if not owner or not repo:
                continue

            try:
                latest_ver, _ = _github_latest_version(owner, repo)
            except Exception:
                continue

            utype = _update_type(current_ver, latest_ver)
            results[skill_name] = {
                "current": current_ver,
                "latest": latest_ver,
                "update_type": utype,
            }

        # Cache results
        cache["last_check"] = _utcnow()
        cache["updates"] = results
        _save_cache(op_dir, cache)

        return results

    def apply_updates(
        self, skills_json_path: Optional[Path] = None, policy: str = "minor"
    ) -> List[str]:
        """Apply updates according to policy. Returns list of updated skill names.

        policy "patch": apply patch only
        policy "minor": apply patch + minor (default)
        policy "none":  never auto-apply
        Major updates: always notify, never auto-apply regardless of policy.
        """
        if policy == "none":
            return []

        op_dir = skills_json_path.parent if skills_json_path else self._op_dir
        updates = self.check_updates(skills_json_path)
        if not updates:
            return []

        apply_types = {"patch"}
        if policy == "minor":
            apply_types.add("minor")

        skills_data = _load_skills_data(op_dir)
        updated: List[str] = []

        for skill_name, info in updates.items():
            utype = info["update_type"]

            if utype == "none":
                continue

            if utype == "major":
                msg = (
                    f"NOTIFY: {skill_name} v{info['latest']} available "
                    f"(major update from v{info['current']}, not auto-applied)"
                )
                print(f"OptimusPrime: {msg}")
                _append_update_log(op_dir, msg)
                continue

            installed_entry = skills_data["installed"].get(skill_name, {})
            skill_policy = installed_entry.get("auto_update", "minor")

            # Respect per-skill override
            if skill_policy == "pin" or skill_policy == "none":
                continue
            if skill_policy == "patch" and utype != "patch":
                continue

            if utype not in apply_types:
                continue

            # Apply the update
            source = installed_entry.get("source", "")
            _, owner, repo = _parse_source(source)
            if not owner or not repo:
                continue

            latest_ver, ref = _github_latest_version(owner, repo)
            content = _fetch_skill_md(owner, repo, ref)
            if content is None:
                continue

            skill_path_str = installed_entry.get("path", "")
            if not skill_path_str:
                skill_path = INSTALL_BASE / skill_name / "SKILL.md"
            else:
                skill_path = Path(skill_path_str).expanduser()

            try:
                skill_path.parent.mkdir(parents=True, exist_ok=True)
                skill_path.write_text(content, encoding="utf-8")
            except Exception:
                continue

            prev_ver = installed_entry.get("installed_version", "?")
            skills_data["installed"][skill_name]["previous_version"] = prev_ver
            skills_data["installed"][skill_name]["installed_version"] = latest_ver
            _save_skills_data(op_dir, skills_data)

            msg = f"Updated {skill_name} v{prev_ver} → v{latest_ver} ({utype}, silent)"
            _append_update_log(op_dir, msg)
            updated.append(skill_name)

        return updated

    def rollback(self, skill_name: str) -> bool:
        """Re-install previous_version for skill. Reverts the last update."""
        skills_data = _load_skills_data(self._op_dir)
        entry = skills_data.get("installed", {}).get(skill_name)

        if entry is None:
            print(f"{skill_name} is not installed.")
            return False

        prev_ver = entry.get("previous_version")
        if not prev_ver:
            print(f"{skill_name} has no previous version recorded. Cannot rollback.")
            return False

        source = entry.get("source", "")
        _, owner, repo = _parse_source(source)
        if not owner or not repo:
            print(f"Cannot parse source '{source}'.")
            return False

        # GitHub tags are usually "v{version}"
        ref = f"v{prev_ver}" if not prev_ver.startswith("v") else prev_ver
        content = _fetch_skill_md(owner, repo, ref)
        if content is None:
            # Try without 'v' prefix
            content = _fetch_skill_md(owner, repo, prev_ver)
        if content is None:
            print(f"Error: could not download v{prev_ver} from {source}")
            return False

        skill_path_str = entry.get("path", "")
        skill_path = (
            Path(skill_path_str).expanduser() if skill_path_str else INSTALL_BASE / skill_name / "SKILL.md"
        )
        try:
            skill_path.parent.mkdir(parents=True, exist_ok=True)
            skill_path.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"Error writing skill file: {e}")
            return False

        current_ver = entry.get("installed_version", "?")
        skills_data["installed"][skill_name]["installed_version"] = prev_ver
        skills_data["installed"][skill_name]["previous_version"] = None
        _save_skills_data(self._op_dir, skills_data)

        _append_update_log(self._op_dir, f"Rolled back {skill_name} v{current_ver} → v{prev_ver}")
        print(f"Rolled back {skill_name} to v{prev_ver}")
        return True

    def pin(self, skill_name: str, version: Optional[str] = None) -> bool:
        """Pin skill to current (or specified) version — disables auto-updates."""
        skills_data = _load_skills_data(self._op_dir)
        entry = skills_data.get("installed", {}).get(skill_name)

        if entry is None:
            print(f"{skill_name} is not installed.")
            return False

        if version and version != entry.get("installed_version"):
            # Install the specific version first
            source = entry.get("source", "")
            _, owner, repo = _parse_source(source)
            if owner and repo:
                ref = f"v{version}" if not version.startswith("v") else version
                content = _fetch_skill_md(owner, repo, ref)
                if content is None:
                    print(f"Error: could not download v{version} from {source}")
                    return False
                skill_path_str = entry.get("path", "")
                skill_path = (
                    Path(skill_path_str).expanduser()
                    if skill_path_str
                    else INSTALL_BASE / skill_name / "SKILL.md"
                )
                try:
                    skill_path.parent.mkdir(parents=True, exist_ok=True)
                    skill_path.write_text(content, encoding="utf-8")
                except Exception as e:
                    print(f"Error writing skill file: {e}")
                    return False
                skills_data["installed"][skill_name]["previous_version"] = entry.get(
                    "installed_version"
                )
                skills_data["installed"][skill_name]["installed_version"] = version

        target_ver = version or entry.get("installed_version", "?")
        skills_data["installed"][skill_name]["auto_update"] = "pin"
        _save_skills_data(self._op_dir, skills_data)

        print(f"Pinned {skill_name} to v{target_ver}")
        return True

    def unpin(self, skill_name: str) -> bool:
        """Restore default auto_update policy from registry for skill."""
        skills_data = _load_skills_data(self._op_dir)
        entry = skills_data.get("installed", {}).get(skill_name)

        if entry is None:
            print(f"{skill_name} is not installed.")
            return False

        registry_entry = self._registry.get("skills", {}).get(skill_name, {})
        default_policy = registry_entry.get("auto_update", "minor")

        skills_data["installed"][skill_name]["auto_update"] = default_policy
        _save_skills_data(self._op_dir, skills_data)

        print(f"Unpinned {skill_name} — auto-updates resumed (policy: {default_policy})")
        return True
