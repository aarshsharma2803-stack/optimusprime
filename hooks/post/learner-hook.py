#!/usr/bin/env python3
"""Stop / SubagentStop hook: runs the cross-session Learner after session-logger.

Reads session artifacts, updates .optimusprime/patterns.json, writes a one-line
summary to .optimusprime/learn-log.md if anything was learned.

Never crashes Claude Code — all errors exit 0.
Fires AFTER session-logger so session-snapshot.md and resume.json are ready.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload: dict = {}
        if raw.strip():
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                pass

        event = payload.get("hook_event_name", "Stop")
        if event not in ("Stop", "SubagentStop"):
            sys.exit(0)

        from optimusprime.utils import find_optimusprime_dir, utcnow_iso
        op_dir = find_optimusprime_dir()
        if op_dir is None:
            sys.exit(0)

        from optimusprime.learner import Learner
        learner = Learner(op_dir)
        session = learner._extract_session_delta()
        result = learner.learn(session)

        # Build a one-line summary of what changed
        learned_items = []

        thresholds = result.get("skill_thresholds", {})
        if thresholds:
            names = ", ".join(thresholds.keys())
            learned_items.append(f"skill thresholds updated ({names})")

        failures = result.get("failure_patterns", {})
        if failures:
            learned_items.append(f"{len(failures)} failure pattern(s) indexed")

        topic_result = result.get("topic_patterns", {})
        if isinstance(topic_result, dict):
            n_topics = topic_result.get("topics", 0)
            if n_topics:
                learned_items.append(f"{n_topics} topic(s) analyzed")
            unstable = topic_result.get("unstable", [])
            if unstable:
                learned_items.append(f"unstable areas: {', '.join(unstable)}")

        scope = result.get("scope_suggestions", {})
        if scope:
            learned_items.append(f"{len(scope)} scope suggestion(s) added")

        if learned_items:
            try:
                ts = utcnow_iso()
                log_path = op_dir / "learn-log.md"
                summary = "; ".join(learned_items)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] LEARNED: {summary}\n")
            except Exception:
                pass

        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
