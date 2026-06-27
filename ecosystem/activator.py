"""Contextual skill activator — reads session signals, recommends/activates skills.

Reads from .optimusprime/ to understand the current session context,
then evaluates each installed skill's activation_signals to decide:
  "activate" — auto-mode skill, signals match → inject into session
  "suggest"  — suggested-mode skill, signals match → recommend to user
  "skip"     — no matching signals, or manual mode

Called by session-logger.py to inject skill suggestions into session-snapshot.md.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ECOSYSTEM_DIR = Path(__file__).resolve().parent
if str(_ECOSYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_ECOSYSTEM_DIR))

from installer import _load_json_file, _load_registry, _load_skills_data


def _load_contract(op_dir: Path) -> Dict[str, Any]:
    return _load_json_file(op_dir / "contract.json")


def _load_cost_log(op_dir: Path) -> Dict[str, Any]:
    return _load_json_file(op_dir / "cost-log.json")


def _load_loop_state(op_dir: Path) -> Dict[str, Any]:
    return _load_json_file(op_dir / "loop-state.json")


def _git_changed_files(project_root: Optional[Path]) -> List[str]:
    """Return list of files changed this session via git diff HEAD."""
    if not project_root:
        return []
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except Exception:
        pass
    return []


def _total_tokens_last_session(cost_log: Dict[str, Any]) -> int:
    """Estimate current session tokens from most recent cost-log entry."""
    sessions = cost_log.get("sessions", [])
    if not sessions:
        return 0
    last = sessions[-1]
    return last.get("input_tokens", 0) + last.get("output_tokens", 0) + last.get(
        "estimated_input_tokens", 0
    ) + last.get("estimated_output_tokens", 0)


def _session_duration_mins(contract: Dict[str, Any]) -> float:
    """Estimate session duration in minutes from contract created_at."""
    created = contract.get("created_at", "")
    if not created:
        return 0.0
    try:
        dt = datetime.fromisoformat(created.rstrip("Z")).replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return 0.0


def _files_touched_from_loop_state(loop_state: Dict[str, Any]) -> List[str]:
    """Extract filenames from loop-state consecutive_failures targets."""
    files = []
    for entry in loop_state.get("consecutive_failures", []):
        target = entry.get("target", "")
        if target and not target.startswith("/proc") and "." in target:
            files.append(target)
    return list(set(files))


# ---------------------------------------------------------------------------
# Signal evaluation
# ---------------------------------------------------------------------------


def _eval_signal(signal: str, signals_ctx: Dict[str, Any]) -> bool:
    """Evaluate one activation signal string against current context signals.

    Signal grammar:
      "complexity_budget:full"         → signals_ctx["complexity_budget"] == "full"
      "goal_keywords:kw1,kw2,kw3"     → any keyword in signals_ctx["goal_keywords"]
      "files_touched:.tsx,.jsx,.css"   → any extension in signals_ctx["files_touched"]
      "token_estimate_over:60000"      → signals_ctx["token_estimate"] > N
    """
    if ":" not in signal:
        return False

    sig_type, _, sig_value = signal.partition(":")
    sig_type = sig_type.strip().lower()

    if sig_type == "complexity_budget":
        budget = signals_ctx.get("complexity_budget", "")
        if isinstance(budget, dict):
            # dict form (files_max / tokens_max) — treat as "full"
            return sig_value == "full"
        return str(budget).lower() == sig_value.lower()

    if sig_type == "goal_keywords":
        keywords = [kw.strip().lower() for kw in sig_value.split(",") if kw.strip()]
        goal = signals_ctx.get("goal_keywords", "").lower()
        return any(kw in goal for kw in keywords)

    if sig_type == "files_touched":
        extensions = [ext.strip().lower() for ext in sig_value.split(",") if ext.strip()]
        touched = [f.lower() for f in signals_ctx.get("files_touched", [])]
        return any(
            any(f.endswith(ext) for f in touched) for ext in extensions
        )

    if sig_type == "token_estimate_over":
        try:
            threshold = int(sig_value.replace(",", ""))
        except ValueError:
            return False
        return signals_ctx.get("token_estimate", 0) > threshold

    return False


class SkillActivator:
    """Evaluate installed skills against current session context and recommend actions."""

    def __init__(self, op_dir: Optional[Path] = None) -> None:
        self._op_dir = op_dir
        self._registry = _load_registry()

    def get_active_signals(self, optimusprime_dir: Optional[Path] = None) -> Dict[str, Any]:
        """Collect current session context into a signals dict.

        Returns:
            complexity_budget: str — "full", "minimal", or empty
            goal_keywords: str — full goal text for keyword matching
            files_touched: list[str] — files changed this session
            token_estimate: int — estimated tokens in current session
            session_duration_mins: float — minutes since session start
        """
        op_dir = optimusprime_dir or self._op_dir
        if op_dir is None:
            return {
                "complexity_budget": "",
                "goal_keywords": "",
                "files_touched": [],
                "token_estimate": 0,
                "session_duration_mins": 0.0,
            }

        contract = _load_contract(op_dir)
        cost_log = _load_cost_log(op_dir)
        loop_state = _load_loop_state(op_dir)

        # Walk up for project root (git repo)
        project_root: Optional[Path] = None
        current = op_dir.parent
        for _ in range(10):
            if (current / ".git").exists():
                project_root = current
                break
            parent = current.parent
            if parent == current:
                break
            current = parent

        changed = _git_changed_files(project_root)
        loop_files = _files_touched_from_loop_state(loop_state)
        all_files = list(set(changed + loop_files))

        # Also include in_scope patterns as hints (extract extensions)
        for pattern in contract.get("in_scope", []):
            if pattern.startswith("*.") or "/." in pattern or pattern.startswith("."):
                all_files.append(f"hint{pattern.lstrip('*')}")

        budget = contract.get("complexity_budget", "")
        if isinstance(budget, dict):
            budget = "full"

        return {
            "complexity_budget": str(budget),
            "goal_keywords": contract.get("goal", ""),
            "files_touched": all_files,
            "token_estimate": _total_tokens_last_session(cost_log),
            "session_duration_mins": _session_duration_mins(contract),
        }

    def evaluate(self, skill_name: str, signals: Dict[str, Any]) -> str:
        """Evaluate whether skill should activate, be suggested, or be skipped.

        Returns "activate" | "suggest" | "skip".
        Respects per-skill mode from skills.json: auto → can activate, suggested → can only suggest.
        """
        # Get per-skill installed mode — uninstalled skills are always skipped
        skills_data = _load_skills_data(self._op_dir)
        installed = skills_data.get("installed", {})
        if skill_name not in installed:
            return "skip"
        installed_entry = installed[skill_name]
        installed_mode = installed_entry.get("mode", "suggested")

        if installed_mode == "manual":
            return "skip"

        # Get activation signals from registry
        registry_entry = self._registry.get("skills", {}).get(skill_name, {})
        activation_signals = registry_entry.get("activation_signals", [])

        if not activation_signals:
            return "skip"

        # Any signal matching is sufficient to trigger
        matched = any(_eval_signal(sig, signals) for sig in activation_signals)
        if not matched:
            return "skip"

        if installed_mode == "auto":
            return "activate"
        return "suggest"

    def get_recommendations(
        self, optimusprime_dir: Optional[Path] = None
    ) -> List[Dict[str, str]]:
        """Run evaluate() for every installed skill. Used by session-logger.

        Returns list of {skill, action, reason} for activate/suggest actions only.
        """
        op_dir = optimusprime_dir or self._op_dir
        signals = self.get_active_signals(op_dir)
        skills_data = _load_skills_data(op_dir)
        installed = skills_data.get("installed", {})

        recommendations: List[Dict[str, str]] = []
        for skill_name in installed:
            action = self.evaluate(skill_name, signals)
            if action == "skip":
                continue

            # Build human-readable reason from matched signals
            registry_entry = self._registry.get("skills", {}).get(skill_name, {})
            matched_sigs = [
                s for s in registry_entry.get("activation_signals", [])
                if _eval_signal(s, signals)
            ]
            reason = "; ".join(matched_sigs) if matched_sigs else "activation threshold met"

            recommendations.append({
                "skill": skill_name,
                "display_name": registry_entry.get("display_name", skill_name),
                "action": action,
                "reason": reason,
            })

        return recommendations
