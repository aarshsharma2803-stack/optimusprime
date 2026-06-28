"""op replay — session timeline debugger.

Steps through any past session like a debugger,
reconstructing the event timeline from .optimusprime/ data.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click

from optimusprime.cli.common import fmt_ts, get_op_dir, load_json_safe, parse_decisions

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

DECISION = "DECISION"
FAILURE  = "FAILURE"
BLOCKED  = "BLOCKED"
LOOP     = "LOOP"
START    = "START"
END      = "END"

_ICONS = {
    DECISION: ("📝", "blue"),
    FAILURE:  ("✗",  "yellow"),
    BLOCKED:  ("🚫", "red"),
    LOOP:     ("🔁", "red"),
    START:    ("🟢", "dim"),
    END:      ("🏁", "dim"),
}

_ATTEMPT_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\].*?(?:FAIL(?:ED)?)[:\s]+(?:tool=)?(?P<body>.+)$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _filter_by_date(lines: List[str], date_prefix: str) -> List[str]:
    """Return lines whose leading timestamp starts with date_prefix."""
    result = []
    for line in lines:
        m = re.match(r"^\[(\d{4}-\d{2}-\d{2})", line)
        if m and m.group(1).startswith(date_prefix):
            result.append(line)
        elif not date_prefix:
            result.append(line)
    return result


def _extract_ts(line: str) -> str:
    """Extract ISO timestamp from the start of a log line."""
    m = re.match(r"^\[([^\]]+)\]", line)
    return m.group(1) if m else "0000-00-00T00:00:00Z"


def _parse_decision_line(line: str) -> Dict[str, str]:
    """Parse a decisions.md line into fields."""
    ts = _extract_ts(line)
    decided = ""
    rejected = ""
    reason = ""
    # DECIDED: X | REJECTED: Y | REASON: Z
    m = re.search(r"DECIDED?[:\s]+([^|]+)", line, re.IGNORECASE)
    if m:
        decided = m.group(1).strip()
    m = re.search(r"REJECTED[:\s]+([^|]+)", line, re.IGNORECASE)
    if m:
        rejected = m.group(1).strip()
    m = re.search(r"REASON[:\s]+([^|]+)", line, re.IGNORECASE)
    if m:
        reason = m.group(1).strip()
    # Fallback: old "DECISION: body" format
    if not decided:
        m = re.search(r"DECISION:\s+(.+)$", line)
        if m:
            decided = m.group(1).strip()
    return {"ts": ts, "decided": decided, "rejected": rejected, "reason": reason, "raw": line}


def _parse_attempt_line(line: str) -> Dict[str, str]:
    """Parse an attempts.md line."""
    ts = _extract_ts(line)
    # Try multiple formats
    tool = ""
    target = ""
    error = ""

    # Format 1: ATTEMPT Tool: X → FAILED: Y
    m = re.search(r"ATTEMPT\s+(\w+):\s*([^\s→]+).*?FAILED[:\s]+(.+)$", line, re.IGNORECASE)
    if m:
        tool, target, error = m.group(1), m.group(2), m.group(3)
    # Format 2: FAIL TOOL: X | TARGET: Y | ERROR: Z
    if not tool:
        m = re.search(r"FAIL\s+TOOL[:\s]+(\w+)", line, re.IGNORECASE)
        if m:
            tool = m.group(1)
        m = re.search(r"TARGET[:\s]+([^|]+)", line, re.IGNORECASE)
        if m:
            target = m.group(1).strip()
        m = re.search(r"ERROR[:\s]+(.+)$", line, re.IGNORECASE)
        if m:
            error = m.group(1).strip()
    # Format 3: FAILED: tool=X target=Y error=Z
    if not tool:
        m = re.search(r"tool=(\w+)", line, re.IGNORECASE)
        if m:
            tool = m.group(1)
        m = re.search(r"target=([^\s]+)", line, re.IGNORECASE)
        if m:
            target = m.group(1)
        m = re.search(r"error=(.+)$", line, re.IGNORECASE)
        if m:
            error = m.group(1).strip()

    return {"ts": ts, "tool": tool, "target": target, "error": error[:80], "raw": line}


def _parse_scope_guard_entry(entry: Dict[str, Any]) -> Dict[str, str]:
    """Parse scope-guard-log.json entry."""
    return {
        "ts": entry.get("timestamp", "0000-00-00T00:00:00Z"),
        "file_path": entry.get("file_path", ""),
        "tool_name": entry.get("tool_name", ""),
    }


def _load_events_for_date(op_dir: Path, date: str) -> List[Dict[str, Any]]:
    """Load and merge all events for a given date prefix."""
    events: List[Dict[str, Any]] = []

    # Decisions
    dec_path = op_dir / "decisions.md"
    if dec_path.is_file():
        try:
            lines = dec_path.read_text(encoding="utf-8").splitlines()
            for line in _filter_by_date([l for l in lines if l.strip()], date):
                d = _parse_decision_line(line)
                events.append({"type": DECISION, "ts": d["ts"], "data": d})
        except Exception:
            pass

    # Failures
    att_path = op_dir / "attempts.md"
    if att_path.is_file():
        try:
            lines = att_path.read_text(encoding="utf-8").splitlines()
            for line in _filter_by_date([l for l in lines if l.strip()], date):
                a = _parse_attempt_line(line)
                events.append({"type": FAILURE, "ts": a["ts"], "data": a})
        except Exception:
            pass

    # Blocks (scope-guard-log.json)
    sg_path = op_dir / "scope-guard-log.json"
    if sg_path.is_file():
        try:
            entries = json.loads(sg_path.read_text(encoding="utf-8"))
            if isinstance(entries, list):
                for entry in entries:
                    ts = entry.get("timestamp", "")
                    if not date or ts.startswith(date):
                        b = _parse_scope_guard_entry(entry)
                        events.append({"type": BLOCKED, "ts": b["ts"], "data": b})
        except Exception:
            pass

    # Loop events
    ls_path = op_dir / "loop-state.json"
    if ls_path.is_file():
        try:
            ls = json.loads(ls_path.read_text(encoding="utf-8"))
            loops = ls.get("loops", {})
            if isinstance(loops, dict):
                for sig, info in loops.items():
                    if isinstance(info, dict) and info.get("count", 0) >= 3:
                        loop_ts = info.get("last_seen", "")
                        if not date or loop_ts.startswith(date):
                            events.append({
                                "type": LOOP,
                                "ts": loop_ts or f"{date}T00:00:00Z",
                                "data": {"signature": sig[:60], "count": info.get("count", 0)},
                            })
        except Exception:
            pass

    # Sort by timestamp
    events.sort(key=lambda e: e["ts"])
    return events


def _parse_snapshot_for_session(op_dir: Path) -> Dict[str, Any]:
    """Parse session-snapshot.md for session summary."""
    path = op_dir / "session-snapshot.md"
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        result: Dict[str, Any] = {}
        m = re.search(r"Generated:\s*([^\s|]+)", text)
        if m:
            result["captured_at"] = m.group(1)
        m = re.search(r"## Goal\n+(.+?)(?=\n## |\Z)", text, re.DOTALL)
        if m:
            result["goal"] = m.group(1).strip()
        m = re.search(r"## Decisions \((\d+) total\)", text)
        if m:
            result["decision_count"] = int(m.group(1))
        m = re.search(r"## Failed Attempts \((\d+) total\)", text)
        if m:
            result["attempt_count"] = int(m.group(1))
        m = re.search(r"## Changed[^\n]*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if m:
            lines = [l.strip() for l in m.group(1).splitlines() if l.strip()]
            result["changed_files"] = lines
        return result
    except Exception:
        return {}


def _get_available_sessions(op_dir: Path) -> List[Dict[str, Any]]:
    """Get list of replayable sessions from resume.json + decisions.md dates."""
    sessions: List[Dict[str, Any]] = []

    # Current session from resume.json
    resume = load_json_safe(op_dir / "resume.json")
    if resume:
        sessions.append({
            "date": (resume.get("captured_at") or "")[:10],
            "session_id": resume.get("session_id", "unknown"),
            "goal": resume.get("goal", ""),
            "decision_count": resume.get("decision_count", 0),
            "attempt_count": resume.get("attempt_count", 0),
        })

    # Extract unique dates from decisions.md
    dec_path = op_dir / "decisions.md"
    if dec_path.is_file():
        try:
            dates_seen = {s["date"] for s in sessions}
            lines = dec_path.read_text(encoding="utf-8").splitlines()
            date_counts: Dict[str, int] = {}
            for line in lines:
                m = re.match(r"^\[(\d{4}-\d{2}-\d{2})", line)
                if m:
                    date_counts[m.group(1)] = date_counts.get(m.group(1), 0) + 1
            for date, count in sorted(date_counts.items(), reverse=True):
                if date not in dates_seen:
                    sessions.append({
                        "date": date,
                        "session_id": date,
                        "goal": "(derived from decisions.md)",
                        "decision_count": count,
                        "attempt_count": 0,
                    })
                    dates_seen.add(date)
        except Exception:
            pass

    return sorted(sessions, key=lambda s: s["date"], reverse=True)


def _resolve_session_date(op_dir: Path, session_spec: Optional[str]) -> str:
    """Resolve a session spec (date prefix or session_id) to a date prefix."""
    if not session_spec:
        # Default: most recent
        resume = load_json_safe(op_dir / "resume.json")
        if resume:
            cap = resume.get("captured_at", "")
            if cap:
                return cap[:10]
        # Fall back to today
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # If it matches YYYY-MM-DD format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", session_spec):
        return session_spec

    # Try to match session_id from resume.json
    resume = load_json_safe(op_dir / "resume.json")
    if resume and resume.get("session_id") == session_spec:
        cap = resume.get("captured_at", "")
        if cap:
            return cap[:10]

    # Treat as date prefix
    return session_spec[:10]


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_event_plain(event: Dict[str, Any], index: int) -> str:
    """Render a single event as plain text."""
    t = event["type"]
    ts = event["ts"][11:16] if len(event["ts"]) >= 16 else event["ts"]
    d = event["data"]
    icon, _ = _ICONS.get(t, ("?", "dim"))

    if t == DECISION:
        line = f"[{ts}] {icon}  DECIDED: {d.get('decided', '')[:70]}"
        if d.get("rejected"):
            line += f"\n           REJECTED: {d['rejected'][:60]}"
        if d.get("reason"):
            line += f"\n           REASON: {d['reason'][:60]}"
    elif t == FAILURE:
        tool = d.get("tool", "?")
        err = d.get("error", "")[:60]
        target = d.get("target", "")
        line = f"[{ts}] {icon}  FAILED: {tool} on {target} — {err}"
    elif t == BLOCKED:
        line = f"[{ts}] {icon}  BLOCKED: {d.get('file_path', '')} write — out of scope"
    elif t == LOOP:
        line = f"[{ts}] {icon}  LOOP DETECTED — {d.get('count', 0)}x: {d.get('signature', '')[:50]}"
    elif t in (START, END):
        label = "SESSION START" if t == START else "SESSION END"
        line = f"[{ts}] {icon}  {label}"
    else:
        line = f"[{ts}] {icon}  {t}"

    return line


def _render_timeline(
    events: List[Dict[str, Any]],
    snapshot: Dict[str, Any],
    session_date: str,
    cost_info: Dict[str, Any],
    step_mode: bool,
) -> None:
    """Render the timeline, optionally in step mode."""
    try:
        from rich.console import Console
        from rich.rule import Rule
        console = Console()
        use_rich = True
    except ImportError:
        use_rich = False
        console = None

    goal = snapshot.get("goal", "(unknown)")
    captured = snapshot.get("captured_at", session_date)
    dec_count = snapshot.get("decision_count", sum(1 for e in events if e["type"] == DECISION))
    att_count = snapshot.get("attempt_count", sum(1 for e in events if e["type"] == FAILURE))
    block_count = sum(1 for e in events if e["type"] == BLOCKED)
    loop_count = sum(1 for e in events if e["type"] == LOOP)
    touched = list({
        e["data"].get("file_path") or e["data"].get("target") or ""
        for e in events if e["type"] in (BLOCKED, FAILURE)
        if e["data"].get("file_path") or e["data"].get("target")
    })

    # Header
    if use_rich:
        console.print()
        console.print(Rule("OPTIMUSPRIME SESSION REPLAY", style="cyan bold"))
        console.print(f"  [dim]📅 Session: {session_date}[/]")
        console.print(f"  [dim]🎯 Goal: {goal}[/]")
        tokens = cost_info.get("token_estimate", cost_info.get("tokens", 0))
        cost = cost_info.get("cost_estimate", cost_info.get("cost_usd", 0.0))
        if tokens:
            console.print(f"  [dim]💰 Cost: ~${cost:.4f} (~{tokens:,} tokens)[/]")
        console.print(Rule(style="dim"))
        console.print("[bold]TIMELINE:[/]")
        console.print()
    else:
        click.echo(f"\nOPTIMUSPRIME SESSION REPLAY")
        click.echo("━" * 47)
        click.echo(f"📅 Session: {session_date}")
        click.echo(f"🎯 Goal: {goal}")
        click.echo("━" * 47)
        click.echo("TIMELINE:\n")

    # Timeline events
    color_map = {DECISION: "blue", FAILURE: "yellow", BLOCKED: "red", LOOP: "red", START: "dim", END: "dim"}
    for i, event in enumerate(events):
        line = _render_event_plain(event, i)
        if use_rich:
            color = color_map.get(event["type"], "white")
            console.print(f"[{color}]{line}[/]")
        else:
            click.echo(line)

        if step_mode:
            try:
                key = input("  ↵ next / q quit: ").strip().lower()
                if key == "q":
                    break
            except (EOFError, KeyboardInterrupt):
                break

    # Summary
    if use_rich:
        console.print()
        console.print(Rule(style="dim"))
        console.print("[bold]SUMMARY:[/]")
        console.print(f"  Decisions:    {dec_count}")
        console.print(f"  Failures:     {att_count}")
        console.print(f"  Loops caught: {loop_count}")
        console.print(f"  Blocks:       {block_count}")
        if touched:
            console.print(f"  Files touched: {', '.join(touched[:5])}")
        console.print(Rule(style="dim"))
        console.print()
    else:
        click.echo("\n" + "━" * 47)
        click.echo("SUMMARY:")
        click.echo(f"  Decisions:    {dec_count}")
        click.echo(f"  Failures:     {att_count}")
        click.echo(f"  Loops caught: {loop_count}")
        click.echo(f"  Blocks:       {block_count}")
        click.echo("━" * 47)


def _render_summary_only(
    events: List[Dict[str, Any]],
    snapshot: Dict[str, Any],
    session_date: str,
) -> None:
    dec_count = sum(1 for e in events if e["type"] == DECISION)
    att_count = sum(1 for e in events if e["type"] == FAILURE)
    block_count = sum(1 for e in events if e["type"] == BLOCKED)
    loop_count = sum(1 for e in events if e["type"] == LOOP)
    goal = snapshot.get("goal", "(unknown)")

    click.echo(f"\nSession: {session_date}  |  Goal: {goal}")
    click.echo(f"  Decisions: {dec_count}  Failures: {att_count}  Blocks: {block_count}  Loops: {loop_count}")


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

@click.command("replay")
@click.option("--session", "-s", default=None, help="Session date (YYYY-MM-DD) or session ID.")
@click.option("--step", "step_mode", is_flag=True, default=False, help="Interactive step-through mode.")
@click.option("--summary", "summary_only", is_flag=True, default=False, help="Summary only, no timeline.")
@click.option("--list", "list_sessions", is_flag=True, default=False, help="List all replayable sessions.")
@click.pass_obj
def replay(
    obj: dict,
    session: Optional[str],
    step_mode: bool,
    summary_only: bool,
    list_sessions: bool,
) -> None:
    """Replay any past session as a timeline debugger.

    \b
    Examples:
      op replay                          # replay most recent session
      op replay --session 2026-06-28     # replay specific date
      op replay --step                   # step through event by event
      op replay --summary                # summary only
      op replay --list                   # list all sessions
    """
    op_dir = get_op_dir(obj)

    # List mode
    if list_sessions:
        sessions = _get_available_sessions(op_dir)
        if not sessions:
            click.echo("No replayable sessions found.")
            return
        click.echo(f"\n{'Date':<12}  {'Goal':<40}  {'Decisions':>9}  {'Failures':>8}")
        click.echo("─" * 76)
        for s in sessions:
            goal_short = s.get("goal", "")[:40]
            click.echo(
                f"{s['date']:<12}  {goal_short:<40}  "
                f"{s['decision_count']:>9}  {s['attempt_count']:>8}"
            )
        click.echo()
        return

    # Resolve target session
    session_date = _resolve_session_date(op_dir, session)

    # Load events
    events = _load_events_for_date(op_dir, session_date)

    if not events and not summary_only:
        # Try without date filter if nothing found
        all_events = _load_events_for_date(op_dir, "")
        if all_events:
            click.echo(
                f"\nNo events found for {session_date}. "
                f"Found {len(all_events)} events total.\n"
                f"Use 'op replay --list' to see available sessions."
            )
        else:
            click.echo(f"\nNo events found for {session_date}. The session has no recorded data.")
        return

    # Add synthetic START and END events
    snapshot = _parse_snapshot_for_session(op_dir)
    if events:
        first_ts = events[0]["ts"]
        last_ts = snapshot.get("captured_at") or events[-1]["ts"]
        events = [{"type": START, "ts": first_ts, "data": {}}] + events
        events.append({"type": END, "ts": last_ts, "data": {}})

    # Cost info
    cost_info: Dict[str, Any] = {}
    clog = load_json_safe(op_dir / "cost-log.json")
    if clog:
        for s in clog.get("sessions", []):
            cap = s.get("captured_at", s.get("session_id", ""))
            if cap.startswith(session_date):
                cost_info = s
                break

    # Summary mode
    if summary_only:
        _render_summary_only(events, snapshot, session_date)
        return

    # Full timeline
    _render_timeline(events, snapshot, session_date, cost_info, step_mode)
