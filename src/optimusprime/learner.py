"""Cross-session learning engine for OptimusPrime.

Runs after every session ends (via learner-hook.py at Stop).
Reads session data, updates patterns.json, making each subsequent
session smarter than the last.

Pure stdlib — no pip dependencies.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from optimusprime.utils import (
    find_optimusprime_dir,
    load_json,
    utcnow_iso,
    write_json_safe,
)

# ---------------------------------------------------------------------------
# Small stop-word set for library name extraction (independent of intelligence.py)
# ---------------------------------------------------------------------------

_STOP = frozenset({
    "a", "an", "the", "is", "it", "in", "of", "to", "and", "or", "for",
    "on", "at", "by", "with", "as", "be", "was", "are", "not", "we", "i",
    "via", "vs", "per", "its", "this", "that", "our", "all", "can", "use",
    "using", "chose", "choose", "selected", "select", "adopted", "adopt",
})

# Keywords that suggest a decision is about library/package choice
_LIB_CONTEXT_WORDS = frozenset({
    "install", "import", "package", "library", "module", "use", "using",
    "chose", "selected", "adopt", "dependency", "dep", "pip", "npm", "yarn",
})

# Regex for parsing attempts.md lines
_FAILED_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\].*?FAILED[:\s]+(?P<body>.+)$"
)
_TOOL_RE = re.compile(r"tool=(\S+)")
_TARGET_RE = re.compile(r"target=(\S+)")
_ERROR_RE = re.compile(r"error=(.+?)(?:\s+line\s+\d+)?$")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LearnerSession:
    session_id: str
    goal: str
    decisions_this_session: list = field(default_factory=list)   # List[DecisionRecord]
    attempts_this_session: list = field(default_factory=list)    # List[dict]
    todos_added: int = 0
    complexity_budget: str = "moderate"
    skills_activated: list = field(default_factory=list)         # List[str]
    captured_at: str = ""


# ---------------------------------------------------------------------------
# Learner
# ---------------------------------------------------------------------------


class Learner:
    """Cross-session learning engine. Reads session artifacts, updates patterns.json."""

    def __init__(self, optimusprime_dir: Path) -> None:
        self._op_dir = Path(optimusprime_dir)
        self._patterns = self._load_or_init_patterns()
        self._engine = self._load_engine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def learn(self, session: Optional[LearnerSession] = None) -> Dict[str, Any]:
        """Main entry point. Orchestrates all learning. Returns summary dict."""
        if session is None:
            session = self._extract_session_delta()

        result: Dict[str, Any] = {}
        try:
            result["skill_thresholds"] = self._learn_skill_thresholds(session)
        except Exception:
            result["skill_thresholds"] = {}
        try:
            result["failure_patterns"] = self._learn_failure_patterns(session)
        except Exception:
            result["failure_patterns"] = {}
        try:
            result["user_preferences"] = self._learn_user_preferences(session)
        except Exception:
            result["user_preferences"] = {}
        try:
            result["topic_patterns"] = self._learn_topic_patterns(session)
        except Exception:
            result["topic_patterns"] = {}
        try:
            result["scope_suggestions"] = self._learn_scope_suggestions(session)
        except Exception:
            result["scope_suggestions"] = {}
        try:
            self._append_session_history(session)
        except Exception:
            pass
        try:
            self._update_patterns_json()
        except Exception:
            pass

        result["sessions_analyzed"] = self._patterns.get("sessions_analyzed", 0)
        return result

    # ------------------------------------------------------------------
    # Session delta extraction
    # ------------------------------------------------------------------

    def _extract_session_delta(self) -> LearnerSession:
        """Build a LearnerSession from what changed THIS session specifically."""
        # decisions_cursor: index into decisions list up to last processed session
        cursor = self._patterns.get("decisions_cursor", 0)

        all_decisions = self._engine._decisions if self._engine else []
        new_decisions = all_decisions[cursor:]

        # Update cursor to current total (saved in _update_patterns_json)
        self._patterns["decisions_cursor"] = len(all_decisions)

        # Goal and session_id: prefer resume.json (written by session-logger first)
        resume = load_json(self._op_dir / "resume.json")
        session_id = resume.get("session_id", "")
        goal = resume.get("goal", "")

        # Fallback chain for goal
        if not goal:
            contract = load_json(self._op_dir / "contract.json")
            goal = contract.get("goal", "")
        if not goal:
            goal = self._read_snapshot_goal()

        # complexity_budget from contract
        contract = load_json(self._op_dir / "contract.json")
        complexity_budget = contract.get("complexity_budget", "moderate")
        if isinstance(complexity_budget, dict):
            complexity_budget = "full"
        complexity_budget = str(complexity_budget)

        # session_id fallback from session-state.json
        if not session_id:
            state = load_json(self._op_dir / "session-state.json")
            session_id = state.get("session_id", "")
        if not session_id:
            now = utcnow_iso()
            session_id = now[:10].replace("-", "") + "-" + now[11:19].replace(":", "")

        return LearnerSession(
            session_id=session_id,
            goal=goal,
            decisions_this_session=new_decisions,
            attempts_this_session=self._read_new_attempts(),
            todos_added=self._count_new_todos(),
            complexity_budget=complexity_budget,
            skills_activated=self._read_active_skills(),
            captured_at=utcnow_iso(),
        )

    # ------------------------------------------------------------------
    # Learning methods
    # ------------------------------------------------------------------

    def _learn_skill_thresholds(self, session: LearnerSession) -> Dict[str, Any]:
        """Adapt skill activation thresholds based on observed token usage."""
        cost_log = load_json(self._op_dir / "cost-log.json")
        sessions = cost_log.get("sessions", [])
        token_count = 0
        if sessions:
            last = sessions[-1]
            token_count = (
                last.get("input_tokens", 0) + last.get("output_tokens", 0) +
                last.get("estimated_input_tokens", 0) + last.get("estimated_output_tokens", 0)
            )

        # Read installed skills
        skills_data = load_json(self._op_dir / "skills.json")
        installed = skills_data.get("installed", {})

        changed: Dict[str, Any] = {}
        skill_activation = self._patterns.setdefault("skill_activation", {})

        for skill_name, entry in installed.items():
            mode = entry.get("mode", "suggested")
            if mode != "auto":
                continue

            sa = skill_activation.setdefault(skill_name, {
                "user_threshold_tokens": 60000,
                "default_threshold_tokens": 60000,
                "learned_from_sessions": 0,
                "confidence": "default",
            })

            default_threshold = sa.get("default_threshold_tokens", 60000)

            if token_count > 0:
                recent = sa.setdefault("_recent_activations", [])
                recent.append(token_count)
                # Keep last 10 observations
                sa["_recent_activations"] = recent[-10:]
                sa["learned_from_sessions"] = sa.get("learned_from_sessions", 0) + 1

                # After 3 consistent observations, update if meaningfully different
                if len(sa["_recent_activations"]) >= 3:
                    avg = sum(sa["_recent_activations"]) / len(sa["_recent_activations"])
                    if abs(avg - default_threshold) / max(default_threshold, 1) > 0.1:
                        sa["user_threshold_tokens"] = int(avg)
                        sa["confidence"] = "learned"
                        changed[skill_name] = int(avg)

        return changed

    def _learn_failure_patterns(self, session: LearnerSession) -> Dict[str, Any]:
        """Index new failures by file and mark resolved ones."""
        failure_patterns = self._patterns.setdefault("failure_patterns", {})
        now = utcnow_iso()
        indexed: Dict[str, Any] = {}

        for attempt in session.attempts_this_session:
            target = attempt.get("target", "")
            error = attempt.get("error", "")
            file_key = target if target else "unknown"

            entry = failure_patterns.setdefault(file_key, {
                "errors": [],
                "occurrence_count": 0,
                "last_seen": now,
                "resolved": False,
            })

            if error and error not in entry.get("errors", []):
                entry.setdefault("errors", []).append(error)
            entry["occurrence_count"] = entry.get("occurrence_count", 0) + 1
            entry["last_seen"] = now
            entry["resolved"] = False
            indexed[file_key] = entry["occurrence_count"]

        # Mark resolved: same file appeared in new decisions (Claude fixed it)
        for file_key, fp_entry in failure_patterns.items():
            if fp_entry.get("resolved"):
                continue
            basename = Path(file_key).name.lower()
            if not basename or basename == "unknown":
                continue
            for dec in session.decisions_this_session:
                raw_lower = dec.raw.lower()
                if basename in raw_lower and "block" not in dec.raw[:20].lower():
                    fp_entry["resolved"] = True
                    break

        return indexed

    def _learn_user_preferences(self, session: LearnerSession) -> Dict[str, Any]:
        """Build running model of how this user works."""
        prefs = self._patterns.setdefault("user_preferences", {
            "explanation_depth": "unknown",
            "avg_decisions_per_session": 0.0,
            "avg_failed_attempts_per_session": 0.0,
            "complexity_distribution": {"minimal": 0, "moderate": 0, "full": 0},
            "preferred_libraries": {},
            "avoided_libraries": {},
        })

        # Running average update (Welford's online mean)
        n = max(1, self._patterns.get("sessions_analyzed", 0) + 1)
        decisions_count = len(session.decisions_this_session)
        attempts_count = len(session.attempts_this_session)

        old_dec = prefs.get("avg_decisions_per_session", 0.0)
        prefs["avg_decisions_per_session"] = round(old_dec + (decisions_count - old_dec) / n, 2)

        old_att = prefs.get("avg_failed_attempts_per_session", 0.0)
        prefs["avg_failed_attempts_per_session"] = round(old_att + (attempts_count - old_att) / n, 2)

        # Complexity distribution
        budget = session.complexity_budget.lower()
        dist = prefs.setdefault("complexity_distribution", {"minimal": 0, "moderate": 0, "full": 0})
        if budget in ("minimal", "moderate", "full"):
            dist[budget] = dist.get(budget, 0) + 1
        elif budget:
            dist["moderate"] = dist.get("moderate", 0) + 1

        # Library preferences from DECIDED/REJECTED lines
        preferred = prefs.setdefault("preferred_libraries", {})
        avoided = prefs.setdefault("avoided_libraries", {})

        for dec in session.decisions_this_session:
            text_lower = dec.decided.lower()
            if not any(kw in text_lower for kw in _LIB_CONTEXT_WORDS):
                continue

            decided_words = self._extract_lib_names(dec.decided)
            for word in decided_words:
                preferred[word] = preferred.get(word, 0) + 1

            for rej in (dec.rejected if hasattr(dec, "rejected") else []):
                rej_words = self._extract_lib_names(rej)
                for word in rej_words:
                    avoided[word] = avoided.get(word, 0) + 1

        # Explanation depth proxy from complexity budget
        if budget == "minimal":
            prefs["explanation_depth"] = "minimal"
        elif budget == "full":
            prefs["explanation_depth"] = "detailed"
        elif prefs.get("explanation_depth") == "unknown" and budget:
            prefs["explanation_depth"] = "moderate"

        return {
            "decisions": decisions_count,
            "attempts": attempts_count,
            "complexity": budget,
        }

    def _learn_topic_patterns(self, session: LearnerSession) -> Dict[str, Any]:
        """Update topic knowledge from intelligence engine patterns."""
        if not self._engine:
            return {}

        all_patterns = self._engine.find_patterns()
        topic_data = self._patterns.setdefault("decision_topics", {})
        unstable_areas: List[str] = []

        for pat in all_patterns:
            topic = pat.topic

            session_dates = sorted({r.session_date for r in pat.decisions if r.session_date})
            sessions_active = len(session_dates)

            all_rejections: List[str] = []
            for rec in pat.decisions:
                if hasattr(rec, "rejected"):
                    all_rejections.extend(rec.rejected)
            top_rejs = [r for r, _ in Counter(all_rejections).most_common(3)]

            entry = topic_data.get(topic, {
                "total_decisions": 0,
                "sessions_active": 0,
                "avg_velocity": 0.0,
                "top_rejections": [],
                "unstable": False,
            })
            entry["total_decisions"] = pat.decision_count
            entry["sessions_active"] = sessions_active
            entry["avg_velocity"] = pat.velocity
            entry["top_rejections"] = top_rejs

            # Unstable if velocity > 3.0 AND more than one session (single session excluded)
            entry["unstable"] = pat.velocity > 3.0 and sessions_active > 1

            topic_data[topic] = entry
            if entry["unstable"]:
                unstable_areas.append(topic)

        self._patterns["unstable_areas"] = sorted(set(unstable_areas))
        return {"topics": len(all_patterns), "unstable": unstable_areas}

    def _learn_scope_suggestions(self, session: LearnerSession) -> Dict[str, Any]:
        """Track repeated scope-guard blocks and suggest contract reviews."""
        scope_log_path = self._op_dir / "scope-guard-log.json"
        if not scope_log_path.is_file():
            return {}

        try:
            raw = scope_log_path.read_text(encoding="utf-8")
            entries = json.loads(raw)
            if not isinstance(entries, list):
                return {}
        except Exception:
            return {}

        # Count blocks per file
        block_counts: Dict[str, int] = {}
        for entry in entries:
            fp = entry.get("file_path", "")
            if fp:
                block_counts[fp] = block_counts.get(fp, 0) + 1

        scope_suggestions = self._patterns.setdefault("scope_suggestions", [])
        existing_files = {s["file"] for s in scope_suggestions}
        added: Dict[str, Any] = {}

        for fp, count in block_counts.items():
            if count >= 3:
                if fp not in existing_files:
                    scope_suggestions.append({
                        "file": fp,
                        "block_count": count,
                        "suggestion": f"Blocked {count} times — review your scope contract",
                        "created_at": utcnow_iso(),
                    })
                    existing_files.add(fp)
                    added[fp] = count
                else:
                    for s in scope_suggestions:
                        if s["file"] == fp:
                            s["block_count"] = count

        return added

    def _append_session_history(self, session: LearnerSession) -> None:
        """Add this session to session_history, capped at 20 entries."""
        history = self._patterns.setdefault("session_history", [])

        topics: List[str] = []
        if self._engine and session.decisions_this_session:
            try:
                pats = self._engine.find_patterns(session.decisions_this_session)
                topics = [p.topic for p in pats]
            except Exception:
                pass

        history.append({
            "session_id": session.session_id,
            "goal": session.goal[:100] if session.goal else "",
            "decisions_made": len(session.decisions_this_session),
            "attempts_failed": len(session.attempts_this_session),
            "todos_added": session.todos_added,
            "topics": topics,
            "skills_activated": session.skills_activated,
            "captured_at": session.captured_at,
        })

        if len(history) > 20:
            self._patterns["session_history"] = history[-20:]

    def _update_patterns_json(self) -> None:
        """Atomically increment sessions_analyzed and save patterns.json."""
        self._patterns["version"] = "1.0.0"
        self._patterns["last_updated"] = utcnow_iso()
        self._patterns["sessions_analyzed"] = self._patterns.get("sessions_analyzed", 0) + 1

        history = self._patterns.get("session_history", [])
        if history:
            self._patterns["last_session_id"] = history[-1]["session_id"]

        write_json_safe(self._op_dir / "patterns.json", self._patterns)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_or_init_patterns(self) -> Dict[str, Any]:
        p = self._op_dir / "patterns.json"
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {
            "version": "1.0.0",
            "last_updated": utcnow_iso(),
            "sessions_analyzed": 0,
            "last_session_id": None,
            "decisions_cursor": 0,
            "skill_activation": {},
            "failure_patterns": {},
            "user_preferences": {
                "explanation_depth": "unknown",
                "avg_decisions_per_session": 0.0,
                "avg_failed_attempts_per_session": 0.0,
                "complexity_distribution": {"minimal": 0, "moderate": 0, "full": 0},
                "preferred_libraries": {},
                "avoided_libraries": {},
            },
            "decision_topics": {},
            "unstable_areas": [],
            "scope_suggestions": [],
            "session_history": [],
        }

    def _load_engine(self):
        try:
            from optimusprime.intelligence import IntelligenceEngine
            return IntelligenceEngine(self._op_dir)
        except Exception:
            return None

    def _read_new_attempts(self) -> List[Dict[str, Any]]:
        """Read failed attempts from today's entries in attempts.md."""
        attempts_path = self._op_dir / "attempts.md"
        if not attempts_path.is_file():
            return []

        today = utcnow_iso()[:10]
        results: List[Dict[str, Any]] = []
        try:
            for line in attempts_path.read_text(encoding="utf-8").splitlines():
                m = _FAILED_RE.match(line.strip())
                if not m:
                    continue
                ts = m.group("ts")
                if not ts.startswith(today):
                    continue
                body = m.group("body")
                tool_m = _TOOL_RE.search(body)
                target_m = _TARGET_RE.search(body)
                error_m = _ERROR_RE.search(body)
                results.append({
                    "tool": tool_m.group(1) if tool_m else "",
                    "target": target_m.group(1) if target_m else "",
                    "error": error_m.group(1).strip() if error_m else body[:80],
                })
        except Exception:
            pass
        return results

    def _count_new_todos(self) -> int:
        """Count TODO/FIXME lines added today in todos.md."""
        todos_path = self._op_dir / "todos.md"
        if not todos_path.is_file():
            return 0
        today = utcnow_iso()[:10]
        count = 0
        try:
            for line in todos_path.read_text(encoding="utf-8").splitlines():
                if today in line and re.search(r"\b(?:TODO|FIXME|HACK|XXX)\b", line, re.IGNORECASE):
                    count += 1
        except Exception:
            pass
        return count

    def _read_active_skills(self) -> List[str]:
        """Return names of skills currently installed in auto mode."""
        skills_data = load_json(self._op_dir / "skills.json")
        installed = skills_data.get("installed", {})
        return [name for name, entry in installed.items() if entry.get("mode") == "auto"]

    def _read_snapshot_goal(self) -> str:
        """Extract goal from session-snapshot.md."""
        snapshot_path = self._op_dir / "session-snapshot.md"
        if not snapshot_path.is_file():
            return ""
        try:
            lines = snapshot_path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if line.strip() == "## Goal":
                    if i + 1 < len(lines):
                        return lines[i + 1].strip()
        except Exception:
            pass
        return ""

    def _extract_lib_names(self, text: str) -> List[str]:
        """Extract candidate library names from text (lowercase words, no stop words)."""
        words = re.findall(r"[a-z][a-z0-9_-]*", text.lower())
        return [w for w in words if len(w) >= 3 and w not in _STOP]


# ---------------------------------------------------------------------------
# Module-level factory
# ---------------------------------------------------------------------------


def get_learner(op_dir: Optional[Path] = None) -> "Learner":
    """Create a Learner for op_dir. Auto-detects if None."""
    if op_dir is None:
        op_dir = find_optimusprime_dir()
    if op_dir is None:
        raise FileNotFoundError("No .optimusprime/ directory found")
    return Learner(op_dir)
