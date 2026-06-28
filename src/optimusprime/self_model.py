"""Behavioral profile engine for OptimusPrime.

Reads .optimusprime/ artifacts across sessions and builds a structured
model of Claude's patterns on this project: failure patterns, confidence
scores, and loop triggers.

Pure stdlib — no pip dependencies.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from optimusprime.utils import find_optimusprime_dir, load_json, write_json_safe

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FailurePattern:
    file_path: str
    error_type: str
    error_signature: str
    occurrence_count: int
    last_seen: str
    resolved: bool
    task_context: str


@dataclass
class ConfidenceScore:
    task_type: str
    success_count: int
    failure_count: int
    confidence: float
    sample_size: int


@dataclass
class LoopTrigger:
    error_pattern: str
    file_pattern: str
    trigger_count: int
    last_triggered: str


# ---------------------------------------------------------------------------
# Task-type keyword buckets
# ---------------------------------------------------------------------------

_TASK_BUCKETS: Dict[str, List[str]] = {
    "auth": ["auth", "jwt", "token", "login", "logout", "session", "password",
             "credential", "oauth", "bearer", "authentication", "authorization"],
    "database": ["database", "query", "sql", "orm", "migration", "db", "schema",
                 "model", "table", "row", "column", "index", "cursor", "transaction"],
    "async": ["async", "await", "concurrent", "race", "thread", "asyncio",
              "coroutine", "future", "task", "event_loop", "sleep"],
    "testing": ["test", "pytest", "jest", "mock", "fixture", "assert", "spec",
                "unittest", "integration", "e2e", "coverage"],
    "refactor": ["refactor", "rename", "extract", "move", "restructure",
                 "cleanup", "simplify", "reorganize"],
    "api": ["api", "endpoint", "route", "rest", "http", "request", "response",
            "get", "post", "put", "delete", "patch", "graphql", "websocket"],
    "frontend": ["ui", "component", "render", "css", "html", "jsx", "tsx",
                 "react", "vue", "svelte", "dom", "style", "layout"],
    "performance": ["performance", "latency", "cache", "optimize", "slow",
                    "memory", "cpu", "benchmark", "profile", "fast"],
}

# ---------------------------------------------------------------------------
# Error normalization patterns
# ---------------------------------------------------------------------------

_NORMALIZE_PATTERNS = [
    (re.compile(r"\bline\s+\d+\b", re.IGNORECASE), "line N"),
    (re.compile(r"\bcolumn\s+\d+\b", re.IGNORECASE), "column N"),
    (re.compile(r"0x[0-9a-fA-F]+"), "0xADDR"),
    (re.compile(r"\bat\s+0x[0-9a-fA-F]+"), "at 0xADDR"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[Z\+\-\d:]*"), "TIMESTAMP"),
    (re.compile(r"\b\d{5,}\b"), "N"),
]

# Flexible parser — handles multiple historical attempts.md formats:
# [ISO] ATTEMPT Tool: target → FAILED: error
# [ISO] [agent:main] FAILED: tool=Edit target=src/foo.py error=SyntaxError
# [ISO] [agent:main] FAIL TOOL: X | TARGET: Y | ERROR: Z
_FAILED_LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\].*?(?:FAIL(?:ED)?)[:\s]+(?P<body>.+)$")
_TOOL_FROM_BODY = re.compile(r"(?:ATTEMPT\s+|tool=)(\w+)")
_TARGET_FROM_BODY = re.compile(r"(?:target=|TARGET:\s*)([^\s|→]+(?:\.[a-zA-Z]+)?)")
_ERROR_FROM_BODY = re.compile(r"(?:ERROR:|FAILED:|error=)(.+?)(?:\s+line\s+\d+)?$")


# ---------------------------------------------------------------------------
# SelfModel
# ---------------------------------------------------------------------------

class SelfModel:
    """Behavioral profile of Claude on this project."""

    def __init__(self, optimusprime_dir: Path) -> None:
        self._op_dir = Path(optimusprime_dir)
        self._model: Dict[str, Any] = self._load_existing()

        try:
            from optimusprime.intelligence import IntelligenceEngine
            self._engine: Optional[Any] = IntelligenceEngine(self._op_dir)
        except Exception:
            self._engine = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> Dict[str, Any]:
        """Read all source data, build full model, write self-model.json."""
        attempts = self._parse_attempts()
        failure_patterns = self._extract_failure_patterns(attempts)
        confidence_map = self._build_confidence_map(attempts)
        loop_triggers = self._identify_loop_triggers()

        model = {
            "version": "0.1.0",
            "built_at": _utcnow(),
            "failure_patterns": {
                _fp_key(fp): {
                    "file_path": fp.file_path,
                    "error_type": fp.error_type,
                    "error_signature": fp.error_signature,
                    "occurrence_count": fp.occurrence_count,
                    "last_seen": fp.last_seen,
                    "resolved": fp.resolved,
                    "task_context": fp.task_context,
                }
                for fp in failure_patterns
            },
            "confidence_map": {
                tt: {
                    "task_type": cs.task_type,
                    "success_count": cs.success_count,
                    "failure_count": cs.failure_count,
                    "confidence": round(cs.confidence, 4),
                    "sample_size": cs.sample_size,
                }
                for tt, cs in confidence_map.items()
            },
            "loop_triggers": [
                {
                    "error_pattern": lt.error_pattern,
                    "file_pattern": lt.file_pattern,
                    "trigger_count": lt.trigger_count,
                    "last_triggered": lt.last_triggered,
                }
                for lt in loop_triggers
            ],
        }

        self._model = model
        write_json_safe(self._op_dir / "self-model.json", model)
        return model

    def get_failure_patterns(self, file_path: Optional[str] = None) -> List[FailurePattern]:
        """Return failure patterns, optionally filtered to a specific file."""
        raw = self._model.get("failure_patterns", {})
        patterns = [
            FailurePattern(
                file_path=v["file_path"],
                error_type=v["error_type"],
                error_signature=v["error_signature"],
                occurrence_count=v["occurrence_count"],
                last_seen=v["last_seen"],
                resolved=v["resolved"],
                task_context=v["task_context"],
            )
            for v in raw.values()
        ]
        if file_path:
            patterns = [p for p in patterns if file_path in p.file_path]
        return sorted(patterns, key=lambda p: -p.occurrence_count)

    def get_confidence(self, task_type: str) -> ConfidenceScore:
        """Return confidence score for a task type."""
        normalized = self._infer_task_type(task_type)
        raw = self._model.get("confidence_map", {})
        if normalized in raw:
            d = raw[normalized]
            return ConfidenceScore(
                task_type=d["task_type"],
                success_count=d["success_count"],
                failure_count=d["failure_count"],
                confidence=d["confidence"],
                sample_size=d["sample_size"],
            )
        return ConfidenceScore(
            task_type=normalized,
            success_count=0,
            failure_count=0,
            confidence=0.5,
            sample_size=0,
        )

    def get_loop_triggers(self) -> List[LoopTrigger]:
        """Return known loop triggers sorted by trigger_count descending."""
        raw = self._model.get("loop_triggers", [])
        triggers = [
            LoopTrigger(
                error_pattern=d["error_pattern"],
                file_pattern=d["file_pattern"],
                trigger_count=d["trigger_count"],
                last_triggered=d["last_triggered"],
            )
            for d in raw
        ]
        return sorted(triggers, key=lambda t: -t.trigger_count)

    def get_warnings_for_task(
        self,
        task_description: str,
        file_path: Optional[str] = None,
    ) -> List[str]:
        """Return pre-emptive warnings for a task. Never more than 5."""
        warnings: List[str] = []

        # File-specific failure patterns
        if file_path:
            file_patterns = self.get_failure_patterns(file_path=file_path)
            active = [p for p in file_patterns if not p.resolved]
            for fp in active[:2]:
                warnings.append(
                    f"{fp.file_path} has {fp.occurrence_count} unresolved "
                    f"failure pattern(s): {fp.error_type}"
                )

        # Task type confidence
        task_type = self._infer_task_type(task_description)
        if task_type != "general":
            cs = self.get_confidence(task_type)
            if cs.sample_size >= 3 and cs.confidence < 0.5:
                pct = int(cs.confidence * 100)
                warnings.append(
                    f"{task_type}-related tasks have {pct}% confidence on this "
                    f"project — {cs.failure_count} failure(s) recorded"
                )

        # Loop triggers matching task description or file
        loop_text = (task_description + " " + (file_path or "")).lower()
        for lt in self.get_loop_triggers():
            if lt.trigger_count >= 2:
                try:
                    if re.search(lt.error_pattern, loop_text, re.IGNORECASE):
                        warnings.append(
                            f"Loop trigger detected: '{lt.error_pattern}' has "
                            f"caused {lt.trigger_count} loop(s) in this project"
                        )
                except re.error:
                    pass

        # High-failure-count patterns relevant to task
        all_patterns = self.get_failure_patterns()
        task_lower = task_description.lower()
        for fp in all_patterns[:10]:
            if fp.occurrence_count >= 3 and not fp.resolved:
                fp_lower = (fp.error_type + " " + fp.task_context).lower()
                overlap = any(w in fp_lower for w in task_lower.split() if len(w) > 4)
                if overlap and fp.file_path not in (file_path or ""):
                    warnings.append(
                        f"Recurring failure ({fp.occurrence_count}x): "
                        f"{fp.error_type} in {fp.task_context}"
                    )
                    if len(warnings) >= 5:
                        break

        return warnings[:5]

    def update(self, session_data: Dict[str, Any]) -> None:
        """Merge new session data without rebuilding from scratch."""
        if not self._model:
            return

        failures_count = session_data.get("failures_count", 0)
        if failures_count <= 0:
            return

        # Increment general failure signal in confidence map
        task_type = self._infer_task_type(
            session_data.get("goal", "") + " " + session_data.get("session_id", "")
        )
        conf_map = self._model.setdefault("confidence_map", {})
        if task_type not in conf_map:
            conf_map[task_type] = {
                "task_type": task_type,
                "success_count": 0,
                "failure_count": 0,
                "confidence": 0.5,
                "sample_size": 0,
            }
        entry = conf_map[task_type]
        entry["failure_count"] += failures_count
        total = entry["success_count"] + entry["failure_count"]
        entry["confidence"] = round(entry["success_count"] / total, 4) if total else 0.5
        entry["sample_size"] = total

        write_json_safe(self._op_dir / "self-model.json", self._model)

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    def _parse_attempts(self) -> List[Dict[str, Any]]:
        """Parse attempts.md into structured records.

        Handles multiple formats:
        - [ISO] ATTEMPT Tool: target → FAILED: error
        - [ISO] [agent:main] FAILED: tool=X target=Y error=Z
        - [ISO] [agent:main] FAIL TOOL: X | TARGET: Y | ERROR: Z
        """
        attempts_path = self._op_dir / "attempts.md"
        if not attempts_path.is_file():
            return []
        records: List[Dict[str, Any]] = []
        try:
            for line in attempts_path.read_text(encoding="utf-8").splitlines():
                m = _FAILED_LINE_RE.match(line.strip())
                if not m:
                    continue
                ts = m.group("ts")
                body = m.group("body")

                # Extract tool, target, error from body (format-agnostic)
                tool_m = _TOOL_FROM_BODY.search(body)
                tool_name = tool_m.group(1) if tool_m else "Unknown"

                target_m = _TARGET_FROM_BODY.search(body)
                target = target_m.group(1).strip() if target_m else body[:40]

                error_m = _ERROR_FROM_BODY.search(body)
                error_raw = error_m.group(1).strip() if error_m else body[:80]

                records.append({
                    "timestamp": ts,
                    "tool_name": tool_name,
                    "target": target,
                    "file_path": _extract_file_path(target),
                    "error_raw": error_raw,
                    "error_type": _first_line(error_raw),
                    "error_signature": self._normalize_error(error_raw),
                    "task_context": f"{tool_name} {target[:50]}",
                })
        except Exception:
            pass
        return records

    def _extract_failure_patterns(
        self, attempts: List[Dict[str, Any]]
    ) -> List[FailurePattern]:
        """Group attempts by (file_path, error_type) into FailurePattern objects."""
        if not attempts:
            return []

        groups: Dict[str, Dict[str, Any]] = {}
        for rec in attempts:
            key = f"{rec['file_path']}::{rec['error_type']}"
            if key not in groups:
                groups[key] = {
                    "file_path": rec["file_path"],
                    "error_type": rec["error_type"],
                    "error_signature": rec["error_signature"],
                    "occurrence_count": 0,
                    "last_seen": rec["timestamp"],
                    "resolved": False,
                    "task_context": rec["task_context"],
                }
            g = groups[key]
            g["occurrence_count"] += 1
            if rec["timestamp"] > g["last_seen"]:
                g["last_seen"] = rec["timestamp"]

        # Mark resolved if a success followed a failure on the same file
        # (decisions.md mentions filename after a failure)
        decisions_path = self._op_dir / "decisions.md"
        if decisions_path.is_file():
            decisions_text = decisions_path.read_text(encoding="utf-8").lower()
            for key, g in groups.items():
                basename = Path(g["file_path"]).name.lower()
                if basename and basename in decisions_text:
                    g["resolved"] = True

        return [
            FailurePattern(**g) for g in sorted(
                groups.values(), key=lambda x: -x["occurrence_count"]
            )
        ]

    def _build_confidence_map(
        self, attempts: List[Dict[str, Any]]
    ) -> Dict[str, ConfidenceScore]:
        """Build confidence scores from decisions (successes) vs failures."""
        # Count failures by task type
        failure_counts: Dict[str, int] = {}
        for rec in attempts:
            tt = self._infer_task_type(rec["task_context"] + " " + rec["file_path"])
            failure_counts[tt] = failure_counts.get(tt, 0) + 1

        # Count successes from decisions.md (each decision = successful choice)
        success_counts: Dict[str, int] = {}
        decisions_path = self._op_dir / "decisions.md"
        if decisions_path.is_file():
            try:
                for line in decisions_path.read_text(encoding="utf-8").splitlines():
                    if "DECISION:" not in line:
                        continue
                    tt = self._infer_task_type(line)
                    success_counts[tt] = success_counts.get(tt, 0) + 1
            except Exception:
                pass

        # Also pull from learned patterns if available
        patterns = load_json(self._op_dir / "patterns.json")
        for topic, _ in patterns.get("decision_topics", {}).items():
            tt = self._infer_task_type(topic)
            success_counts[tt] = success_counts.get(tt, 0) + 1

        all_types = set(failure_counts) | set(success_counts)
        result: Dict[str, ConfidenceScore] = {}
        for tt in all_types:
            s = success_counts.get(tt, 0)
            f = failure_counts.get(tt, 0)
            total = s + f
            conf = round(s / total, 4) if total else 0.5
            result[tt] = ConfidenceScore(
                task_type=tt,
                success_count=s,
                failure_count=f,
                confidence=conf,
                sample_size=total,
            )
        return result

    def _identify_loop_triggers(self) -> List[LoopTrigger]:
        """Extract loop-causing error patterns from loop-state.json."""
        loop_state = load_json(self._op_dir / "loop-state.json")
        failures = loop_state.get("consecutive_failures", [])
        if len(failures) < 3:
            return []

        groups: Dict[str, Dict[str, Any]] = {}
        for entry in failures:
            raw_error = entry.get("error", "")
            sig = self._normalize_error(raw_error)
            target = entry.get("target", "")
            file_pat = _extract_file_path(target)
            key = f"{sig}::{file_pat}"
            if key not in groups:
                groups[key] = {
                    "error_pattern": re.escape(sig)[:80],
                    "file_pattern": file_pat,
                    "trigger_count": 0,
                    "last_triggered": entry.get("timestamp", ""),
                }
            g = groups[key]
            g["trigger_count"] += 1
            ts = entry.get("timestamp", "")
            if ts > g["last_triggered"]:
                g["last_triggered"] = ts

        # Only return groups that actually caused a loop (3+ occurrences)
        return [
            LoopTrigger(**g)
            for g in groups.values()
            if g["trigger_count"] >= 3
        ]

    def _infer_task_type(self, text: str) -> str:
        """Map text to a task type bucket via keyword matching."""
        lower = text.lower()
        best_type = "general"
        best_count = 0
        for task_type, keywords in _TASK_BUCKETS.items():
            count = sum(1 for kw in keywords if kw in lower)
            if count > best_count:
                best_count = count
                best_type = task_type
        return best_type

    def _normalize_error(self, error: str) -> str:
        """Strip line numbers, addresses, timestamps so errors deduplicate."""
        result = error
        for pattern, replacement in _NORMALIZE_PATTERNS:
            result = pattern.sub(replacement, result)
        return result.strip()

    def _load_existing(self) -> Dict[str, Any]:
        path = self._op_dir / "self-model.json"
        return load_json(path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fp_key(fp: FailurePattern) -> str:
    return f"{fp.file_path}::{fp.error_type}"


def _extract_file_path(target: str) -> str:
    """Extract the most likely file path from a tool target string."""
    # Common patterns: "src/foo.py", "tests/test_foo.py"
    m = re.search(r"[\w./\-]+\.\w+", target)
    return m.group(0) if m else target[:40]


def _first_line(text: str) -> str:
    """Return the first non-empty line, truncated to 80 chars."""
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s[:80]
    return text[:80]


def get_self_model(op_dir: Optional[Path] = None) -> SelfModel:
    """Module-level factory. Finds .optimusprime/ automatically if op_dir is None."""
    if op_dir is None:
        from optimusprime.utils import find_optimusprime_dir
        op_dir = find_optimusprime_dir()
        if op_dir is None:
            raise FileNotFoundError("No .optimusprime/ directory found")
    return SelfModel(op_dir)
