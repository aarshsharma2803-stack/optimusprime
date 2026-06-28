"""op autopilot — pre-session briefing command.

Run before opening Claude Code every morning.
Reads all .optimusprime/ data + git state and renders
a session brief: what was done, what's left, risks, suggested first message.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click

from optimusprime.cli.common import fmt_ts, get_op_dir, load_json_safe

# ---------------------------------------------------------------------------
# Snapshot parser
# ---------------------------------------------------------------------------

def _parse_snapshot(path: Path) -> Dict[str, Any]:
    """Parse session-snapshot.md into structured dict."""
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    result: Dict[str, Any] = {}

    # Generated: ts | Session: id | Agent: name
    m = re.search(r"Generated:\s*([^\s|]+)", text)
    if m:
        result["captured_at"] = m.group(1)

    m = re.search(r"Session:\s*([^\s|]+)", text)
    if m:
        result["session_id"] = m.group(1)

    # ## Goal
    m = re.search(r"## Goal\n+(.+?)(?=\n## |\Z)", text, re.DOTALL)
    if m:
        result["goal"] = m.group(1).strip()

    # ## Changed (N files)
    m = re.search(r"## Changed \((\d+) files?\)", text)
    if m:
        result["changed_count"] = int(m.group(1))
    changed_block = re.search(r"## Changed[^\n]*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if changed_block:
        lines = [l.strip() for l in changed_block.group(1).splitlines() if l.strip()]
        result["changed_files"] = lines

    # ## Decisions (N total)
    m = re.search(r"## Decisions \((\d+) total\)", text)
    if m:
        result["decision_count"] = int(m.group(1))

    # ## Failed Attempts (N total)
    m = re.search(r"## Failed Attempts \((\d+) total\)", text)
    if m:
        result["attempt_count"] = int(m.group(1))

    # ## Open TODOs (N)
    m = re.search(r"## Open TODOs \((\d+)\)", text)
    if m:
        result["open_todo_count"] = int(m.group(1))

    # ## Next Action
    m = re.search(r"## Next Action\n+(.+?)(?=\n## |\Z)", text, re.DOTALL)
    if m:
        result["next_action"] = m.group(1).strip()

    return result


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_todos(op_dir: Path) -> Tuple[int, List[str]]:
    """Return (count, first_3_lines) from todos.md."""
    path = op_dir / "todos.md"
    if not path.is_file():
        return 0, []
    try:
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return len(lines), lines[:3]
    except Exception:
        return 0, []


def _load_decisions_tail(op_dir: Path, n: int = 3) -> Tuple[int, List[str]]:
    """Return (total_count, last_n_entries) from decisions.md."""
    path = op_dir / "decisions.md"
    if not path.is_file():
        return 0, []
    try:
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return len(lines), lines[-n:]
    except Exception:
        return 0, []


def _load_attempts_info(op_dir: Path) -> Tuple[int, int]:
    """Return (total_failures, unresolved_count)."""
    path = op_dir / "attempts.md"
    if not path.is_file():
        return 0, 0
    try:
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        total = len(lines)
        # unresolved = entries not mentioned in decisions as resolved
        return total, total  # conservative: assume all unresolved without detailed cross-ref
    except Exception:
        return 0, 0


def _load_self_model_info(
    op_dir: Path, task_type: str
) -> Tuple[List[str], float]:
    """Return (top_2_warnings, confidence_pct)."""
    sm = load_json_safe(op_dir / "self-model.json")
    if not sm:
        return [], 0.0

    warnings: List[str] = []
    try:
        from optimusprime.self_model import SelfModel
        model = SelfModel(op_dir)
        warnings = model.get_warnings_for_task(task_description=task_type)[:2]
    except Exception:
        pass

    confidence = 1.0
    conf_map = sm.get("confidence_map", {})
    for bucket, data in conf_map.items():
        if bucket.lower() in task_type.lower():
            if isinstance(data, dict):
                confidence = data.get("confidence", 1.0)
            elif isinstance(data, (int, float)):
                confidence = float(data)
            break

    return warnings, round(confidence * 100, 0)


def _load_patterns_info(op_dir: Path) -> Tuple[int, List[str]]:
    """Return (sessions_analyzed, unstable_areas)."""
    p = load_json_safe(op_dir / "patterns.json")
    if not p:
        return 0, []
    sessions_analyzed = p.get("sessions_analyzed", 0)
    unstable = [
        k for k, v in p.get("decision_topics", {}).items()
        if isinstance(v, dict) and v.get("unstable", False)
    ]
    return sessions_analyzed, unstable[:3]


# ---------------------------------------------------------------------------
# Git analysis
# ---------------------------------------------------------------------------

def _run_git(cmd: str, cwd: Path) -> str:
    """Run git command, return stdout. Returns '' on any error."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(cwd),
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _git_analysis(
    project_root: Path,
    captured_at: str,
    out_of_scope: List[str],
    op_dir: Path,
) -> Dict[str, Any]:
    """Run git analysis. Returns empty dict if git not available."""
    result: Dict[str, Any] = {
        "available": False,
        "commit_count": 0,
        "changed_files": [],
        "uncommitted": [],
        "oos_changes": [],
        "rejected_readded": [],
    }

    # Check if git is available
    test = _run_git("git rev-parse --git-dir", project_root)
    if not test:
        return result

    result["available"] = True

    # Commits since last session
    if captured_at:
        since_date = captured_at[:10]
        log = _run_git(f'git log --oneline --since="{since_date}"', project_root)
        result["commit_count"] = len([l for l in log.splitlines() if l.strip()])

    # Files changed since last snapshot
    if captured_at and result["commit_count"] > 0:
        n = result["commit_count"]
        diff = _run_git(f"git diff --name-only HEAD~{n} HEAD", project_root)
        result["changed_files"] = [l.strip() for l in diff.splitlines() if l.strip()]
    else:
        diff = _run_git("git diff --name-only", project_root)
        result["changed_files"] = [l.strip() for l in diff.splitlines() if l.strip()]

    # Uncommitted changes
    status = _run_git("git status --short", project_root)
    result["uncommitted"] = [l.strip() for l in status.splitlines() if l.strip()]

    # Cross-reference against out_of_scope
    oos_set = set(out_of_scope)
    for f in result["changed_files"]:
        for oos in oos_set:
            # Simple prefix/suffix match
            oos_clean = oos.rstrip("/**")
            if f.startswith(oos_clean) or f == oos_clean:
                result["oos_changes"].append(f"⚠ OUT OF SCOPE change: {f}")
                break

    # Cross-reference against REJECTED decisions
    rejected_terms = _load_rejected_terms(op_dir)
    if rejected_terms:
        dep_files = {"requirements.txt", "package.json", "Cargo.toml", "pyproject.toml"}
        for f in result["changed_files"]:
            fname = Path(f).name
            if fname in dep_files:
                fpath = project_root / f
                if fpath.is_file():
                    content = fpath.read_text(encoding="utf-8", errors="ignore").lower()
                    for term, when in rejected_terms.items():
                        if term in content:
                            result["rejected_readded"].append(
                                f"⚠ REJECTED dep re-added: '{term}' in {f} (rejected {when})"
                            )

    return result


def _load_rejected_terms(op_dir: Path) -> Dict[str, str]:
    """Build {term: timestamp} dict from REJECTED fields in decisions.md."""
    path = op_dir / "decisions.md"
    if not path.is_file():
        return {}
    rejected: Dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            ts_m = re.match(r"^\[([^\]]+)\]", line)
            ts = ts_m.group(1)[:10] if ts_m else "?"
            rej_m = re.search(r"REJECTED[:\s]+([^|]+)", line, re.IGNORECASE)
            if rej_m:
                for term in rej_m.group(1).split(","):
                    t = term.strip().lower()
                    if t and len(t) > 2:
                        rejected[t] = ts
    except Exception:
        pass
    return rejected


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------

_ACTION_RE = re.compile(r"\b(fix|build|refactor|test|implement|add|review|update)\b", re.IGNORECASE)

def _infer_task_type(next_action: str, goal: str) -> str:
    combined = (next_action + " " + goal).lower()
    if re.search(r"\b(auth|login|jwt|session|oauth)\b", combined):
        return "auth"
    if re.search(r"\b(api|endpoint|route|rest|http)\b", combined):
        return "api"
    if re.search(r"\b(test|spec|coverage|pytest|jest)\b", combined):
        return "testing"
    if re.search(r"\b(ui|frontend|component|react|vue|css)\b", combined):
        return "frontend"
    if re.search(r"\b(db|database|sql|migration|model)\b", combined):
        return "database"
    m = _ACTION_RE.search(combined)
    return m.group(1).lower() if m else "general"


def _build_suggested_message(
    next_action: str,
    recent_decisions: List[str],
    contract: Dict[str, Any],
    goal: str,
) -> str:
    """Build a ready-to-paste Claude Code first message."""
    parts: List[str] = []

    if next_action:
        parts.append(next_action[:120])

    if recent_decisions:
        dec_snippet = recent_decisions[-1][:80] if recent_decisions else ""
        if dec_snippet:
            parts.append(f"(last decision: {dec_snippet})")

    budget = contract.get("complexity_budget", "")
    if budget and budget != "full":
        parts.append(f"Budget: {budget}.")

    in_scope = contract.get("in_scope", contract.get("in_scope_files", []))
    if in_scope and len(in_scope) <= 3:
        scope_str = ", ".join(str(p) for p in in_scope[:3])
        parts.append(f"Work in: {scope_str}.")

    msg = " ".join(parts)
    if not msg:
        msg = goal or "Continue from last session."

    # Truncate to 100 words
    words = msg.split()
    if len(words) > 100:
        msg = " ".join(words[:100]) + "…"
    return msg


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_rich(data: Dict[str, Any]) -> None:
    """Render full session brief with rich."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.rule import Rule
        from rich.text import Text
        console = Console()
    except ImportError:
        _render_plain(data)
        return

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    console.print()
    console.print(Rule("⚡ OPTIMUSPRIME AUTOPILOT BRIEF", style="cyan bold"))
    console.print(f"  [dim]📅 {now}[/]")
    cap = data.get("captured_at", "unknown")
    console.print(f"  [dim]🎯 Last session: {cap}[/]")
    console.print()

    # What was done
    console.print("[bold cyan]WHAT WAS DONE:[/]")
    goal = data.get("goal", "(unknown goal)")
    console.print(f"  Goal: {goal}")
    changed = data.get("changed_files", [])
    ch_count = data.get("changed_count", len(changed))
    console.print(f"  Files changed: {ch_count}")
    dec_count = data.get("decision_count", 0)
    console.print(f"  Decisions made: {dec_count}")
    console.print()

    # Where you left off
    console.print("[bold cyan]WHERE YOU LEFT OFF:[/]")
    next_action = data.get("next_action", "(no next action recorded)")
    console.print(f"  {next_action}")
    console.print()

    # Open todos
    todo_count = data.get("todo_count", 0)
    todos = data.get("todo_list", [])
    console.print(f"[bold cyan]OPEN TODOS:[/] {todo_count}")
    for t in todos[:3]:
        console.print(f"  • {t[:90]}")
    if not todos and todo_count == 0:
        console.print("  [dim](none)[/]")
    console.print()

    # Git
    git = data.get("git", {})
    if git.get("available"):
        commits = git.get("commit_count", 0)
        changed_git = git.get("changed_files", [])
        console.print(f"[bold cyan]GIT SINCE LAST SESSION:[/]")
        console.print(f"  {commits} commits · {len(changed_git)} files changed")
        for oos in git.get("oos_changes", [])[:3]:
            console.print(f"  [yellow]{oos}[/]")
        for rej in git.get("rejected_readded", [])[:3]:
            console.print(f"  [yellow]{rej}[/]")
        uncom = git.get("uncommitted", [])
        if uncom:
            console.print(f"  [dim]{len(uncom)} uncommitted change(s)[/]")
        if not git.get("oos_changes") and not git.get("rejected_readded"):
            console.print("  [green]✓ No scope or rejection violations[/]")
    else:
        console.print("[bold cyan]GIT:[/] [dim]not available[/]")
    console.print()

    # Risks
    warnings = data.get("warnings", [])
    unstable = data.get("unstable_areas", [])
    console.print("[bold cyan]KNOWN RISKS TODAY:[/]")
    if warnings:
        for w in warnings[:2]:
            console.print(f"  ⚠ {w}")
    if unstable:
        console.print(f"  ⚠ Unstable areas: {', '.join(unstable[:3])}")
    if not warnings and not unstable:
        console.print("  [green]✓ No known risks[/]")
    console.print()

    # Intelligence
    total_failures = data.get("total_failures", 0)
    sessions_analyzed = data.get("sessions_analyzed", 0)
    task_type = data.get("task_type", "general")
    confidence = data.get("confidence", 100.0)
    console.print("[bold cyan]INTELLIGENCE:[/]")
    console.print(
        f"  {dec_count} decisions · {total_failures} failures"
        f" · {sessions_analyzed} sessions learned"
        f" · Confidence for this task: {confidence:.0f}% ({task_type})"
    )
    console.print()

    # Scope
    contract = data.get("contract", {})
    in_scope = contract.get("in_scope", contract.get("in_scope_files", []))
    out_scope = contract.get("out_of_scope", contract.get("out_of_scope_files", []))
    console.print("[bold cyan]RECOMMENDED SCOPE:[/]")
    if in_scope:
        console.print(f"  IN:  {', '.join(str(p) for p in in_scope[:4])}")
    if out_scope:
        console.print(f"  OUT: {', '.join(str(p) for p in out_scope[:4])}")
    if not in_scope and not out_scope:
        console.print("  [dim](no contract found)[/]")
    console.print()

    # Suggested message
    msg = data.get("suggested_message", "")
    console.print("[bold cyan]SUGGESTED FIRST MESSAGE:[/]")
    console.print(Panel(msg, border_style="green", expand=False))
    console.print()
    console.print(Rule(style="dim"))
    console.print(
        "  [dim]Tip: paste the suggested message above to start instantly.[/]"
    )
    console.print()


def _render_plain(data: Dict[str, Any]) -> None:
    """Plain text fallback (no rich)."""
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    click.echo(f"\n⚡ OPTIMUSPRIME AUTOPILOT BRIEF")
    click.echo("━" * 47)
    click.echo(f"📅 {now}")
    click.echo(f"🎯 Last session: {data.get('captured_at', 'unknown')}")
    click.echo()
    click.echo("WHAT WAS DONE:")
    click.echo(f"  Goal: {data.get('goal', '(unknown)')}")
    click.echo(f"  Files changed: {data.get('changed_count', 0)}")
    click.echo(f"  Decisions made: {data.get('decision_count', 0)}")
    click.echo()
    click.echo("WHERE YOU LEFT OFF:")
    click.echo(f"  {data.get('next_action', '(none)')}")
    click.echo()
    click.echo(f"OPEN TODOS: {data.get('todo_count', 0)}")
    for t in data.get("todo_list", [])[:3]:
        click.echo(f"  • {t[:90]}")
    click.echo()
    click.echo("SUGGESTED FIRST MESSAGE:")
    click.echo(f"  {data.get('suggested_message', '')}")
    click.echo("━" * 47)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

@click.command("autopilot")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.option("--message-only", "message_only", is_flag=True, default=False,
              help="Print only the suggested first message (for piping).")
@click.pass_obj
def autopilot(obj: dict, as_json: bool, message_only: bool) -> None:
    """Pre-session briefing. Run before opening Claude Code.

    Reads .optimusprime/ + git state and shows what was done,
    what's left, known risks, and a suggested first message.

    \b
    Examples:
      op autopilot                    # full brief
      op autopilot --message-only     # just the message (pipe to clipboard)
      op autopilot --message-only | pbcopy
      op autopilot --json             # machine-readable
    """
    op_dir = get_op_dir(obj)

    # ---- Step 2: Load all data sources ------------------------------------
    snapshot = _parse_snapshot(op_dir / "session-snapshot.md")
    resume = load_json_safe(op_dir / "resume.json")
    contract = load_json_safe(op_dir / "contract.json")

    # Merge snapshot + resume (snapshot takes priority)
    goal = snapshot.get("goal") or resume.get("goal") or "(unknown goal)"
    captured_at = snapshot.get("captured_at") or resume.get("captured_at") or ""
    next_action = snapshot.get("next_action") or resume.get("next_action") or ""
    decision_count = snapshot.get("decision_count") or resume.get("decision_count") or 0
    changed_count = snapshot.get("changed_count") or len(resume.get("changed_files", []))
    changed_files = snapshot.get("changed_files") or resume.get("changed_files") or []

    todo_count, todo_list = _load_todos(op_dir)
    total_decisions, recent_decisions = _load_decisions_tail(op_dir, n=3)
    total_failures, _ = _load_attempts_info(op_dir)

    task_type = _infer_task_type(next_action, goal)
    warnings, confidence = _load_self_model_info(op_dir, task_type)
    sessions_analyzed, unstable_areas = _load_patterns_info(op_dir)

    # ---- Step 3 & 4: Git analysis ----------------------------------------
    out_of_scope = contract.get("out_of_scope", contract.get("out_of_scope_files", []))
    project_root = op_dir.parent
    git_info = _git_analysis(project_root, captured_at, out_of_scope, op_dir)

    # ---- Step 5: Build suggested message ----------------------------------
    msg = _build_suggested_message(next_action, recent_decisions, contract, goal)

    # ---- Assemble data dict -----------------------------------------------
    data: Dict[str, Any] = {
        "captured_at": fmt_ts(captured_at) if captured_at else "unknown",
        "goal": goal,
        "changed_count": changed_count,
        "changed_files": changed_files,
        "decision_count": decision_count or total_decisions,
        "next_action": next_action,
        "todo_count": todo_count,
        "todo_list": todo_list,
        "total_failures": total_failures,
        "sessions_analyzed": sessions_analyzed,
        "task_type": task_type,
        "confidence": confidence,
        "warnings": warnings,
        "unstable_areas": unstable_areas,
        "contract": contract,
        "git": git_info,
        "suggested_message": msg,
        "recent_decisions": recent_decisions,
    }

    # ---- Step 6: Render ---------------------------------------------------
    if message_only:
        click.echo(msg)
        return

    if as_json:
        # Remove non-serializable items
        out = {k: v for k, v in data.items() if k != "contract" or isinstance(v, dict)}
        click.echo(json.dumps(out, indent=2, default=str))
        return

    _render_rich(data)
