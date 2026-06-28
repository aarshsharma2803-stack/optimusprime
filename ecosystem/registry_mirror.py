"""Fallback mirror support for ecosystem skill installs.

Used automatically by installer.py when the primary GitHub source
fails (network error, 404, rate limit).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Mirror map: primary GitHub URL suffix → fallback raw URL
_MIRRORS: dict[str, str] = {
    "obra/superpowers":                  "https://cdn.jsdelivr.net/gh/obra/superpowers@main/SKILL.md",
    "garrytan/gstack":                   "https://cdn.jsdelivr.net/gh/garrytan/gstack@main/SKILL.md",
    "nextlevelbuilder/ui-ux-pro-max-skill": "https://cdn.jsdelivr.net/gh/nextlevelbuilder/ui-ux-pro-max-skill@main/SKILL.md",
    "JuliusBrussee/caveman":             "https://cdn.jsdelivr.net/gh/JuliusBrussee/caveman@main/SKILL.md",
    "DietrichGebert/ponytail":           "https://cdn.jsdelivr.net/gh/DietrichGebert/ponytail@main/SKILL.md",
}

# registry.json maps skill name → {"source": "github:owner/repo", ...}
_REGISTRY_PATH = Path(__file__).parent / "registry.json"


def _source_for(skill_name: str) -> Optional[str]:
    """Return owner/repo for a skill name, or None if not in registry."""
    try:
        reg = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        entry = reg.get(skill_name, {})
        source = entry.get("source", "")
        # source is "github:owner/repo"
        if source.startswith("github:"):
            return source[len("github:"):]
    except Exception:
        pass
    return None


def check_source(skill_name: str) -> bool:
    """Return True if skill_name is in registry and has a known mirror."""
    owner_repo = _source_for(skill_name)
    return owner_repo in _MIRRORS if owner_repo else False


def get_fallback(skill_name: str) -> Optional[str]:
    """Return mirror URL for skill_name, or None if no mirror exists."""
    owner_repo = _source_for(skill_name)
    return _MIRRORS.get(owner_repo) if owner_repo else None


def log_failure(skill_name: str, error: str) -> None:
    """Append failure entry to .optimusprime/skills-errors.md."""
    from optimusprime.utils import find_optimusprime_dir  # lazy import — stdlib-safe callers

    op_dir = find_optimusprime_dir()
    if op_dir is None:
        return
    log_path = op_dir / "skills-errors.md"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] SKILL_FETCH_ERROR skill={skill_name} error={error[:200]}\n"
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
