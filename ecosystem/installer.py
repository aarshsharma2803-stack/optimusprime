"""Ecosystem skill installer — install community skills from GitHub source.

Rules enforced here:
- NEVER bundle skill files: always fetch from source at install time
- NEVER modify installed skill files: treat as read-only after install
- Idempotent: re-installing an already-installed skill is a no-op (no --force yet)
- Atomic writes for skills.json: temp file + os.rename()
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ECOSYSTEM_DIR = Path(__file__).resolve().parent
_REGISTRY_PATH = _ECOSYSTEM_DIR / "registry.json"
INSTALL_BASE = Path.home() / ".optimusprime" / "skills"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_registry() -> Dict[str, Any]:
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "1.0.0", "skills": {}}


def _load_json_file(path: Path) -> Dict[str, Any]:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_skills_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.rename(tmp, path)
            return True
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            return False
    except Exception:
        return False


def _parse_source(source: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse 'github:owner/repo' → ('github', 'owner', 'repo')."""
    if source.startswith("github:"):
        parts = source[7:].split("/", 1)
        if len(parts) == 2:
            return ("github", parts[0], parts[1])
    return (None, None, None)


def _github_latest_version(owner: str, repo: str) -> Tuple[str, str]:
    """Return (version_str, git_ref) from GitHub releases API. Falls back to 'main'."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "optimusprime/0.1.0", "Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag = data.get("tag_name", "")
            if tag:
                version = tag.lstrip("v")
                return (version, tag)
    except Exception:
        pass
    return ("main", "main")


def _fetch_skill_md(owner: str, repo: str, ref: str) -> Optional[str]:
    """Download SKILL.md from GitHub raw. Tries root, then skills/ subdirectory."""
    candidates = ["SKILL.md", "skills/SKILL.md", f"skills/{repo}/SKILL.md"]
    for path in candidates:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "optimusprime/0.1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8")
        except Exception:
            continue
    return None


def _skills_json_path(op_dir: Optional[Path]) -> Optional[Path]:
    return op_dir / "skills.json" if op_dir else None


def _load_skills_data(op_dir: Optional[Path]) -> Dict[str, Any]:
    path = _skills_json_path(op_dir)
    if path is None:
        return {"version": "0.1.0", "installed": {}, "last_checked": ""}
    data = _load_json_file(path)
    if not data:
        return {"version": "0.1.0", "installed": {}, "last_checked": ""}
    data.setdefault("installed", {})
    data.setdefault("last_checked", "")
    return data


def _save_skills_data(op_dir: Optional[Path], data: Dict[str, Any]) -> bool:
    path = _skills_json_path(op_dir)
    if path is None:
        return False
    return _write_json_atomic(path, data)


class SkillInstaller:
    """Install, uninstall, and list ecosystem skills."""

    def __init__(self, op_dir: Optional[Path] = None) -> None:
        self._op_dir = op_dir
        self._registry = _load_registry()

    def install(self, skill_name: str, mode: str = "suggested") -> bool:
        """Install a skill from the registry. Idempotent — no-op if already installed."""
        registry_skills = self._registry.get("skills", {})
        if skill_name not in registry_skills:
            available = ", ".join(sorted(registry_skills.keys()))
            print(f"Error: '{skill_name}' not in registry. Available: {available}")
            return False

        entry = registry_skills[skill_name]
        source = entry.get("source", "")
        platform, owner, repo = _parse_source(source)

        if platform != "github" or not owner or not repo:
            print(f"Error: unsupported source format '{source}'")
            return False

        skills_data = _load_skills_data(self._op_dir)
        if skill_name in skills_data["installed"]:
            existing_ver = skills_data["installed"][skill_name].get("installed_version", "?")
            print(f"{skill_name} already installed (v{existing_ver})")
            return True

        print(f"Fetching {skill_name} from {source}...")
        version, ref = _github_latest_version(owner, repo)
        content = _fetch_skill_md(owner, repo, ref)

        if content is None:
            print(f"Error: could not download SKILL.md from {source} (ref={ref})")
            print("Check your internet connection or try again later.")
            return False

        install_dir = INSTALL_BASE / skill_name
        install_dir.mkdir(parents=True, exist_ok=True)
        skill_path = install_dir / "SKILL.md"
        skill_path.write_text(content, encoding="utf-8")

        skills_data["installed"][skill_name] = {
            "source": source,
            "installed_version": version,
            "previous_version": None,
            "installed_at": _utcnow(),
            "mode": mode,
            "trigger": entry.get("default_trigger", ""),
            "auto_update": entry.get("auto_update", "minor"),
            "path": str(skill_path),
        }

        if _save_skills_data(self._op_dir, skills_data):
            print(f"Installed {skill_name} v{version} from {source}")
        else:
            print(f"Installed {skill_name} v{version} (warning: could not update skills.json)")

        return True

    def uninstall(self, skill_name: str) -> bool:
        """Remove installed skill and its entry from skills.json."""
        skills_data = _load_skills_data(self._op_dir)
        installed = skills_data.get("installed", {})

        if skill_name not in installed:
            print(f"{skill_name} is not installed.")
            return False

        entry = installed[skill_name]
        skill_path_str = entry.get("path", "")
        if skill_path_str:
            skill_path = Path(skill_path_str).expanduser()
            try:
                if skill_path.is_file():
                    skill_path.unlink()
                parent = skill_path.parent
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except Exception:
                pass

        del installed[skill_name]
        skills_data["installed"] = installed
        _save_skills_data(self._op_dir, skills_data)

        print(f"Uninstalled {skill_name}")
        return True

    def list_installed(self) -> List[Dict[str, Any]]:
        """Return list of installed skills with metadata."""
        skills_data = _load_skills_data(self._op_dir)
        return [
            {"name": name, **entry}
            for name, entry in skills_data.get("installed", {}).items()
        ]

    def list_available(self) -> List[Dict[str, Any]]:
        """Return all registry skills, marked with installed status."""
        skills_data = _load_skills_data(self._op_dir)
        installed_names = set(skills_data.get("installed", {}).keys())
        result = []
        for name, entry in self._registry.get("skills", {}).items():
            result.append({
                "name": name,
                "display_name": entry.get("display_name", name),
                "description": entry.get("description", ""),
                "source": entry.get("source", ""),
                "stars": entry.get("stars", 0),
                "license": entry.get("license", ""),
                "installed": name in installed_names,
                "default_mode": entry.get("default_mode", "suggested"),
                "tags": entry.get("tags", []),
            })
        return result
