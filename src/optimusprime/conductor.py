"""OptimusPrime Conductor — agentic orchestration engine.

You define a goal. Conductor breaks it into subtasks, runs Claude
headlessly on each, evaluates output with the full intelligence layer,
escalates to human when stuck, continues autonomously otherwise.

Guardrails: scope enforcement, self-model, codebase map,
loop detection, done checker, convention extractor.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from optimusprime.utils import append_to_file, find_optimusprime_dir, write_json_safe

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SubTask:
    id: str
    description: str
    file_scope: List[str]
    status: str = "pending"           # pending|running|done|failed|escalated|skipped
    attempts: int = 0
    max_attempts: int = 3
    output: str = ""
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    token_estimate: int = 0
    decisions_made: int = 0


@dataclass
class ConductorSession:
    session_id: str
    goal: str
    subtasks: List[SubTask]
    status: str = "planning"          # planning|running|paused|done|aborted
    created_at: str = ""
    total_tokens: int = 0
    total_cost_estimate: float = 0.0
    escalation_count: int = 0
    human_interventions: List[str] = field(default_factory=list)


class EscalationReason:
    LOOP_DETECTED       = "loop_detected"
    LOW_CONFIDENCE      = "low_confidence"
    SCOPE_VIOLATION     = "scope_violation"
    DONE_CHECK_FAILED   = "done_check_failed"
    MAX_ATTEMPTS        = "max_attempts"
    CONTRADICTION       = "contradiction"


# ---------------------------------------------------------------------------
# Conductor
# ---------------------------------------------------------------------------

_NOW = lambda: datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

_COST_PER_1K_TOKENS = 0.003   # rough estimate


def _est_tokens(text: str) -> int:
    """Simple word-count × 1.3 approximation."""
    return int(len(text.split()) * 1.3)


# Task-type keyword buckets for planning
_TASK_BUCKETS = {
    "auth":      ["auth", "login", "jwt", "session", "oauth", "password", "token"],
    "api":       ["api", "endpoint", "route", "rest", "http", "handler", "controller"],
    "testing":   ["test", "spec", "coverage", "pytest", "jest", "assert"],
    "frontend":  ["ui", "component", "react", "vue", "css", "page", "form"],
    "database":  ["db", "database", "sql", "migration", "model", "schema", "query"],
    "infra":     ["deploy", "docker", "ci", "pipeline", "config", "env", "infra"],
    "refactor":  ["refactor", "restructure", "rename", "clean", "simplify", "extract"],
    "docs":      ["doc", "readme", "comment", "docstring"],
}


class Conductor:
    """Orchestration engine for autonomous Claude Code sessions."""

    def __init__(self, optimusprime_dir: Path, project_root: Path) -> None:
        self._op_dir = Path(optimusprime_dir)
        self._root = Path(project_root)
        self._session_path = self._op_dir / "conductor-session.json"
        self._log_path = self._op_dir / "conductor-log.md"
        self._esc_path = self._op_dir / "conductor-escalations.md"
        self._plan_path = self._op_dir / "conductor-plan.md"
        self._summary_path = self._op_dir / "conductor-summary.md"

        # Load intelligence layers lazily
        self._engine: Any = None
        self._self_model: Any = None
        self._codebase_map: Any = None

    # ------------------------------------------------------------------
    # Intelligence layer loaders
    # ------------------------------------------------------------------

    def _get_engine(self) -> Any:
        if self._engine is None:
            try:
                from optimusprime.intelligence import IntelligenceEngine
                self._engine = IntelligenceEngine(self._op_dir)
            except Exception:
                self._engine = None
        return self._engine

    def _get_self_model(self) -> Any:
        if self._self_model is None:
            try:
                from optimusprime.self_model import SelfModel
                self._self_model = SelfModel(self._op_dir)
            except Exception:
                self._self_model = None
        return self._self_model

    def _get_codebase_map(self) -> Any:
        if self._codebase_map is None:
            try:
                from optimusprime.codebase_map import CodebaseMap
                self._codebase_map = CodebaseMap(self._root, self._op_dir)
            except Exception:
                self._codebase_map = None
        return self._codebase_map

    # ------------------------------------------------------------------
    # plan()
    # ------------------------------------------------------------------

    def plan(self, goal: str) -> ConductorSession:
        """Break a goal into an ordered list of subtasks."""
        # Prerequisite check
        problems = self._check_prerequisites()
        if problems:
            raise RuntimeError("\n".join(problems))

        session_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        contract = self._load_json_safe(self._op_dir / "contract.json")

        # Use IntelligenceEngine to analyse the goal
        reasoning = ""
        engine = self._get_engine()
        if engine:
            try:
                reasoning = engine.reason_about(goal)
            except Exception:
                reasoning = ""

        # Break goal into subtasks
        subtasks = self._decompose_goal(goal, contract, reasoning)

        # Pre-flight: self-model warnings
        preflight_warnings: List[str] = []
        sm = self._get_self_model()
        if sm:
            try:
                preflight_warnings = sm.get_warnings_for_task(task_description=goal)[:3]
            except Exception:
                pass

        # Pre-flight: contradiction check
        contradictions: List[str] = []
        if engine:
            try:
                from optimusprime.intelligence import DecisionRecord
                past = engine._decisions[:20] if hasattr(engine, "_decisions") else []
                if past:
                    results = engine.detect_contradictions(goal, past)
                    contradictions = [r.explanation for r in results[:2]]
            except Exception:
                pass

        # Budget estimate
        avg_tokens = 2000
        budget_tokens = len(subtasks) * avg_tokens
        budget_cost = budget_tokens * _COST_PER_1K_TOKENS / 1000

        # Write conductor-plan.md
        self._write_plan_md(
            goal=goal,
            subtasks=subtasks,
            warnings=preflight_warnings,
            contradictions=contradictions,
            budget_tokens=budget_tokens,
            budget_cost=budget_cost,
            contract=contract,
        )

        session = ConductorSession(
            session_id=session_id,
            goal=goal,
            subtasks=subtasks,
            status="planning",
            created_at=_NOW(),
        )
        self._save_session(session)
        return session

    def _decompose_goal(
        self, goal: str, contract: Dict, reasoning: str
    ) -> List[SubTask]:
        """Break goal into at most 8 ordered subtasks."""
        goal_lower = goal.lower()
        contract_in_scope = contract.get("in_scope", contract.get("in_scope_files", []))

        # Determine task types from goal
        active_buckets = []
        for bucket, keywords in _TASK_BUCKETS.items():
            if any(kw in goal_lower for kw in keywords):
                active_buckets.append(bucket)

        # Build subtasks based on task types
        subtasks: List[SubTask] = []
        idx = 1

        def _make(desc: str, files: List[str]) -> SubTask:
            nonlocal idx
            st = SubTask(
                id=f"subtask-{idx:03d}",
                description=desc,
                file_scope=files,
            )
            idx += 1
            return st

        # Extract file references from goal
        file_refs = re.findall(r"\b(?:src/|tests/|hooks/|cli/)[\w./]+\b", goal)
        src_files = [f for f in contract_in_scope if "src" in f or "lib" in f][:3]
        test_files = [f for f in contract_in_scope if "test" in f][:2]

        # Generic decomposition strategy
        if "refactor" in goal_lower or "restructure" in goal_lower:
            subtasks.append(_make(f"Analyse existing code structure for: {goal[:60]}", src_files or ["src/"]))
            subtasks.append(_make(f"Refactor core logic: {goal[:60]}", src_files or ["src/"]))
            subtasks.append(_make("Update tests to match refactored code", test_files or ["tests/"]))

        elif "build" in goal_lower or "implement" in goal_lower or "create" in goal_lower or "add" in goal_lower:
            # Build tasks: utilities first, core logic, tests
            if "database" in active_buckets or "db" in goal_lower:
                subtasks.append(_make(f"Create database models/schema: {goal[:50]}", ["src/"]))
            if "api" in active_buckets:
                subtasks.append(_make(f"Build API handlers: {goal[:50]}", ["src/"]))
            if "auth" in active_buckets:
                subtasks.append(_make(f"Implement authentication logic: {goal[:50]}", ["src/"]))
            if "frontend" in active_buckets:
                subtasks.append(_make(f"Build UI components: {goal[:50]}", ["src/"]))

            # If no specific buckets, generic build
            if not subtasks:
                subtasks.append(_make(f"Implement core utilities for: {goal[:60]}", src_files or ["src/"]))
                subtasks.append(_make(f"Implement main logic: {goal[:60]}", src_files or ["src/"]))

            subtasks.append(_make(f"Write tests for: {goal[:60]}", test_files or ["tests/"]))

        elif "fix" in goal_lower or "debug" in goal_lower or "repair" in goal_lower:
            subtasks.append(_make(f"Diagnose and locate bug: {goal[:60]}", src_files or ["src/"]))
            subtasks.append(_make(f"Fix the identified issue: {goal[:60]}", file_refs or src_files or ["src/"]))
            subtasks.append(_make("Verify fix with tests", test_files or ["tests/"]))

        elif "test" in goal_lower or "coverage" in goal_lower:
            subtasks.append(_make(f"Write unit tests for: {goal[:60]}", test_files or ["tests/"]))
            subtasks.append(_make(f"Write integration tests for: {goal[:60]}", test_files or ["tests/"]))

        else:
            # Generic fallback: 3 subtasks
            subtasks.append(_make(f"Analyse and plan: {goal[:60]}", src_files or ["src/"]))
            subtasks.append(_make(f"Implement: {goal[:60]}", src_files or ["src/"]))
            subtasks.append(_make("Verify and test", test_files or ["tests/"]))

        # Enforce max 8 subtasks
        return subtasks[:8]

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(
        self, session: ConductorSession, dry_run: bool = False
    ) -> ConductorSession:
        """Main orchestration loop. Executes subtasks in order."""
        session.status = "running"
        self._save_session(session)

        prev_decisions_count = self._count_decisions()

        for subtask in session.subtasks:
            if subtask.status in ("done", "escalated", "skipped"):
                continue
            if session.status == "paused":
                break

            success = False
            while subtask.attempts < subtask.max_attempts and not success:
                subtask.status = "running"
                subtask.started_at = _NOW()
                self._save_session(session)

                # Step 1: Pre-subtask intelligence check
                context_pkg = self._build_context_package(subtask)

                # Step 2: Build Claude prompt
                contract = self._load_json_safe(self._op_dir / "contract.json")
                prompt = self._build_subtask_prompt(subtask, session, context_pkg, contract)

                # Step 3: Execute
                if dry_run:
                    raw_output = f"SUBTASK COMPLETE: {subtask.description}"
                    exit_code = 0
                else:
                    raw_output, exit_code = self._execute_subtask(prompt)

                subtask.attempts += 1
                subtask.output = raw_output[:2000]
                subtask.token_estimate = _est_tokens(raw_output)

                # Step 4 & 5: Parse output and check done
                complete_found = "SUBTASK COMPLETE" in raw_output
                refused = any(
                    phrase in raw_output for phrase in [
                        "I cannot", "I don't know how", "I'm unable",
                        "I can't", "I am unable",
                    ]
                )

                # Step 6: Evaluate
                escalation_reason = self._check_escalation(
                    subtask, raw_output, complete_found, refused
                )

                if escalation_reason:
                    subtask.status = "escalated"
                    subtask.completed_at = _NOW()
                    session.escalation_count += 1
                    self._log_escalation(subtask, escalation_reason, raw_output)
                    self._log_to_file(
                        self._log_path,
                        f"ESCALATED subtask-{subtask.id}: {escalation_reason}",
                    )
                    session.status = "paused"
                    self._save_session(session)
                    success = True  # break inner loop

                elif complete_found:
                    subtask.status = "done"
                    subtask.completed_at = _NOW()
                    # Track decisions made during this subtask
                    new_count = self._count_decisions()
                    subtask.decisions_made = max(0, new_count - prev_decisions_count)
                    prev_decisions_count = new_count

                    session.total_tokens += subtask.token_estimate
                    session.total_cost_estimate += (
                        subtask.token_estimate * _COST_PER_1K_TOKENS / 1000
                    )
                    self._log_to_file(
                        self._log_path,
                        f"SUBTASK DONE: {subtask.id} — {subtask.description[:60]}",
                    )
                    self._save_session(session)
                    success = True

                else:
                    # Failed but not escalated — will retry if attempts < max
                    subtask.error = raw_output[:200]
                    if subtask.attempts >= subtask.max_attempts:
                        escalation_reason = EscalationReason.MAX_ATTEMPTS
                        subtask.status = "escalated"
                        subtask.completed_at = _NOW()
                        session.escalation_count += 1
                        self._log_escalation(subtask, escalation_reason, raw_output)
                        session.status = "paused"
                        self._save_session(session)
                        success = True

                if not dry_run and not success:
                    time.sleep(2)  # brief pause between retries

            if not dry_run:
                time.sleep(2)  # brief pause between subtasks

        # Session complete
        all_done = all(s.status in ("done", "skipped") for s in session.subtasks)
        has_escalation = any(s.status == "escalated" for s in session.subtasks)

        if session.status != "paused":
            session.status = "done" if all_done else ("paused" if has_escalation else "done")

        self._write_summary(session)
        self._save_session(session)
        return session

    def resume(self, escalation_context: str = "") -> ConductorSession:
        """Resume a paused session after human intervention."""
        if not self._session_path.is_file():
            raise RuntimeError("No conductor session found. Run 'op conductor start' first.")
        session = self._load_session()
        if session.status not in ("paused", "planning"):
            raise RuntimeError(f"Session is {session.status}, not paused. Cannot resume.")

        if escalation_context:
            session.human_interventions.append(
                f"[{_NOW()}] {escalation_context}"
            )

        # Inject context into next pending/escalated subtask
        for st in session.subtasks:
            if st.status in ("escalated", "failed", "pending"):
                if escalation_context:
                    st.error = f"[HUMAN CONTEXT]: {escalation_context}"
                # Reset to pending so it gets retried
                if st.status == "escalated":
                    st.status = "pending"
                    st.attempts = 0  # fresh start after human intervention
                break

        session.status = "running"
        self._save_session(session)
        return self.run(session)

    def abort(self) -> None:
        """Mark session aborted. Write final state."""
        if not self._session_path.is_file():
            raise RuntimeError("No conductor session found.")
        session = self._load_session()
        session.status = "aborted"
        self._save_session(session)
        self._write_summary(session)

    # ------------------------------------------------------------------
    # Prerequisites
    # ------------------------------------------------------------------

    def _check_prerequisites(self) -> List[str]:
        """Return list of problems. Empty = all good."""
        problems: List[str] = []

        if not self._op_dir.is_dir():
            problems.append("No .optimusprime/ directory found")
            return problems  # early return, others need op_dir

        contract_path = self._op_dir / "contract.json"
        if not contract_path.is_file():
            problems.append(
                "No scope contract — run a Claude Code session first "
                "or create .optimusprime/contract.json"
            )

        if not shutil.which("claude"):
            problems.append("claude command not found — install Claude Code CLI")

        return problems

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def _build_context_package(self, subtask: SubTask) -> str:
        """Assemble intelligence context for subtask prompt. Under 500 tokens."""
        parts: List[str] = []

        # Self-model warnings
        sm = self._get_self_model()
        if sm:
            try:
                warnings = sm.get_warnings_for_task(subtask.description)[:2]
                if warnings:
                    parts.append("WARNINGS:\n" + "\n".join(f"  • {w}" for w in warnings))
            except Exception:
                pass

        # Relevant past decisions
        engine = self._get_engine()
        if engine:
            try:
                results = engine.predict_context_needs(
                    tool_name="conductor",
                    tool_input={"prompt": subtask.description[:200]},
                    top_k=3,
                )
                relevant = [r for r in results if r.get("score", 0) > 0.3]
                if relevant:
                    snippets = [r["content"][:80] for r in relevant[:3]]
                    parts.append("PAST DECISIONS:\n" + "\n".join(f"  • {s}" for s in snippets))
            except Exception:
                pass

        # Codebase map utilities
        cm = self._get_codebase_map()
        if cm and subtask.file_scope:
            try:
                relevant_utils = cm.get_relevant_for_file(subtask.file_scope[0])
                if relevant_utils:
                    util_lines = []
                    for name, entry in list(relevant_utils.items())[:3]:
                        util_lines.append(f"  • {name} in {entry.get('file', '?')}")
                    parts.append("EXISTING UTILITIES:\n" + "\n".join(util_lines))
            except Exception:
                pass

        pkg = "\n\n".join(parts)
        # Keep under 500 tokens (~2000 chars)
        if len(pkg) > 2000:
            pkg = pkg[:1997] + "..."
        return pkg

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_subtask_prompt(
        self,
        subtask: SubTask,
        session: ConductorSession,
        context_pkg: str,
        contract: Dict,
    ) -> str:
        total = len(session.subtasks)
        idx = int(subtask.id.split("-")[-1])
        out_of_scope = contract.get("out_of_scope", contract.get("out_of_scope_files", []))
        budget = contract.get("complexity_budget", "full")

        lines = [
            f"You are working on subtask {idx} of {total}.",
            f"Overall goal: {session.goal}",
            f"This subtask: {subtask.description}",
            f"Files in scope for this subtask: {', '.join(subtask.file_scope) or 'as needed'}",
            f"Files out of scope: {', '.join(str(p) for p in out_of_scope[:5])}",
            f"Complexity budget: {budget}",
            "",
        ]
        if context_pkg:
            lines.append("Context from OptimusPrime:")
            lines.append(context_pkg)
            lines.append("")

        lines.extend([
            "Complete ONLY this subtask. Do not work ahead.",
            f"When done, output exactly: SUBTASK COMPLETE: {subtask.description}",
        ])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute_subtask(self, prompt: str) -> tuple[str, int]:
        """Run Claude Code headlessly. Returns (output, exit_code)."""
        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "json",
            "--max-turns", "10",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,   # 5 minutes per subtask
                cwd=str(self._root),
            )
            output = result.stdout or result.stderr or ""
            return output, result.returncode
        except subprocess.TimeoutExpired:
            return "TIMEOUT: subtask exceeded 5 minute limit", 1
        except FileNotFoundError:
            return "ERROR: claude command not found", 1
        except Exception as e:
            return f"ERROR: {e}", 1

    # ------------------------------------------------------------------
    # Escalation logic
    # ------------------------------------------------------------------

    def _check_escalation(
        self,
        subtask: SubTask,
        output: str,
        complete_found: bool,
        refused: bool,
    ) -> Optional[str]:
        """Return escalation reason string or None."""
        # Explicit refusal
        if refused:
            return EscalationReason.LOW_CONFIDENCE

        # Loop detection: check loop-state.json
        ls = self._load_json_safe(self._op_dir / "loop-state.json")
        if ls:
            consecutive = ls.get("consecutive_failures", 0)
            if consecutive >= 3:
                return EscalationReason.LOOP_DETECTED

        # Scope violation: new entries in scope-guard-log since subtask started
        sg = self._load_json_safe_list(self._op_dir / "scope-guard-log.json")
        if sg and subtask.started_at:
            recent_blocks = [
                e for e in sg
                if e.get("timestamp", "") >= subtask.started_at
            ]
            if recent_blocks:
                return EscalationReason.SCOPE_VIOLATION

        # Self-model low confidence
        sm = self._get_self_model()
        if sm:
            try:
                sm_data = self._load_json_safe(self._op_dir / "self-model.json")
                conf_map = sm_data.get("confidence_map", {})
                for bucket, data in conf_map.items():
                    if bucket.lower() in subtask.description.lower():
                        conf = data.get("confidence", 1.0) if isinstance(data, dict) else float(data)
                        if conf < 0.3:
                            return EscalationReason.LOW_CONFIDENCE
            except Exception:
                pass

        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_session(self, session: ConductorSession) -> None:
        """Write conductor-session.json atomically."""
        data = {
            "session_id": session.session_id,
            "goal": session.goal,
            "status": session.status,
            "created_at": session.created_at,
            "total_tokens": session.total_tokens,
            "total_cost_estimate": session.total_cost_estimate,
            "escalation_count": session.escalation_count,
            "human_interventions": session.human_interventions,
            "subtasks": [asdict(st) for st in session.subtasks],
        }
        write_json_safe(self._session_path, data)

    def _load_session(self) -> ConductorSession:
        """Load ConductorSession from conductor-session.json."""
        data = self._load_json_safe(self._session_path)
        if not data:
            raise RuntimeError("conductor-session.json is missing or malformed.")
        subtasks = [
            SubTask(**{k: v for k, v in st.items() if k in SubTask.__dataclass_fields__})
            for st in data.get("subtasks", [])
        ]
        return ConductorSession(
            session_id=data.get("session_id", ""),
            goal=data.get("goal", ""),
            subtasks=subtasks,
            status=data.get("status", "planning"),
            created_at=data.get("created_at", ""),
            total_tokens=data.get("total_tokens", 0),
            total_cost_estimate=data.get("total_cost_estimate", 0.0),
            escalation_count=data.get("escalation_count", 0),
            human_interventions=data.get("human_interventions", []),
        )

    # ------------------------------------------------------------------
    # Logging & reporting
    # ------------------------------------------------------------------

    def _log_to_file(self, path: Path, message: str) -> None:
        """Append timestamped message to a log file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            ts = _NOW()
            line = f"[{ts}] {message}\n"
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def _log_escalation(
        self, subtask: SubTask, reason: str, context: str
    ) -> None:
        """Write escalation details to conductor-escalations.md."""
        suggestions = {
            EscalationReason.LOOP_DETECTED: "Check loop-state.json, clear loop counter, then resume",
            EscalationReason.LOW_CONFIDENCE: "Review subtask description or provide more context via resume",
            EscalationReason.SCOPE_VIOLATION: "Review contract.json — Claude tried to write out-of-scope files",
            EscalationReason.DONE_CHECK_FAILED: "Review subtask output, clarify requirements, then resume",
            EscalationReason.MAX_ATTEMPTS: "Simplify the subtask or break it into smaller pieces",
            EscalationReason.CONTRADICTION: "Resolve contradicting decisions in decisions.md, then resume",
        }
        suggestion = suggestions.get(reason, "Review the escalation context and resume manually")
        lines = [
            f"\n[{_NOW()}] ESCALATED: {subtask.id}",
            f"REASON: {reason}",
            f"SUBTASK: {subtask.description}",
            f"CONTEXT: {context[:200]}",
            f"SUGGESTED ACTION: {suggestion}",
            "─" * 60,
        ]
        try:
            self._esc_path.parent.mkdir(parents=True, exist_ok=True)
            with self._esc_path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass

    def _write_plan_md(
        self,
        goal: str,
        subtasks: List[SubTask],
        warnings: List[str],
        contradictions: List[str],
        budget_tokens: int,
        budget_cost: float,
        contract: Dict,
    ) -> None:
        lines = [
            "# CONDUCTOR PLAN",
            f"Generated: {_NOW()}",
            "",
            f"## Goal",
            goal,
            "",
            f"## Subtasks ({len(subtasks)})",
            "",
        ]
        for i, st in enumerate(subtasks, 1):
            complexity = "low" if i <= 1 else "medium" if i <= 5 else "high"
            lines.append(f"### {i}. [{st.id}] {st.description}")
            lines.append(f"Files: {', '.join(st.file_scope) or '(inferred from goal)'}")
            lines.append(f"Est. complexity: {complexity}")
            lines.append("")

        lines.extend([
            "## Intelligence Pre-flight",
            "",
        ])
        if warnings:
            for w in warnings:
                lines.append(f"⚠ {w}")
        else:
            lines.append("✓ No self-model warnings")

        if contradictions:
            for c in contradictions:
                lines.append(f"⚠ CONTRADICTION: {c}")
        else:
            lines.append("✓ No contradictions detected")

        lines.extend([
            "",
            f"## Budget Estimate",
            f"~{budget_tokens:,} tokens (~${budget_cost:.4f})",
        ])
        try:
            self._plan_path.parent.mkdir(parents=True, exist_ok=True)
            self._plan_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _write_summary(self, session: ConductorSession) -> None:
        done = [s for s in session.subtasks if s.status == "done"]
        esc = [s for s in session.subtasks if s.status == "escalated"]
        failed = [s for s in session.subtasks if s.status == "failed"]
        lines = [
            "# CONDUCTOR SUMMARY",
            f"Session: {session.session_id}",
            f"Status: {session.status}",
            f"Goal: {session.goal}",
            "",
            f"Subtasks completed: {len(done)}/{len(session.subtasks)}",
            f"Escalations: {len(esc)}",
            f"Failures: {len(failed)}",
            "",
            f"Total tokens: ~{session.total_tokens:,}",
            f"Total cost: ~${session.total_cost_estimate:.4f}",
            "",
            "## Subtask Results",
        ]
        for st in session.subtasks:
            icon = {"done": "✓", "escalated": "⚠", "failed": "✗", "pending": "○", "skipped": "—"}.get(st.status, "?")
            lines.append(f"  {icon} [{st.id}] {st.description[:60]} ({st.status})")
        try:
            self._summary_path.parent.mkdir(parents=True, exist_ok=True)
            self._summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_json_safe(self, path: Path) -> Dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_json_safe_list(self, path: Path) -> List:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _count_decisions(self) -> int:
        path = self._op_dir / "decisions.md"
        if not path.is_file():
            return 0
        try:
            return sum(1 for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
        except Exception:
            return 0
