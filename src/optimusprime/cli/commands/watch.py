"""op watch — live session dashboard.

Updates every 3 seconds. Shows tokens/cost, scope, intelligence,
self-model, decisions, skills, loops, task state.

--compact flag: single-line summary mode.
Requires: rich>=13.0
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import click


def _find_op_dir(start: Optional[Path] = None) -> Optional[Path]:
    current = (start or Path.cwd()).resolve()
    for _ in range(10):
        candidate = current / ".optimusprime"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_tail(path: Path, n: int = 5) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = [l.rstrip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return lines[-n:]
    except Exception:
        return []


def _read_task_state(op_dir: Path) -> dict:
    """Parse task-state.md frontmatter."""
    path = op_dir / "task-state.md"
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        state: dict = {}
        fm_match = re.search(r"^---\n(.*?)\n---", text, re.DOTALL)
        if fm_match:
            for line in fm_match.group(1).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    state[k.strip()] = v.strip()
        # Current step
        m = re.search(r"## Current Step\n(.+)", text)
        if m:
            state["current_step"] = m.group(1).strip()
        # What was just done
        m = re.search(r"## What Was Just Done\n(.+)", text)
        if m:
            state["what_done"] = m.group(1).strip()
        return state
    except Exception:
        return {}


def _build_compact_line(op_dir: Path) -> str:
    """Single-line summary: goal | calls | last decision."""
    task = _read_task_state(op_dir)
    goal = task.get("goal", "no goal")[:40]
    calls = task.get("tool_call_count", "?")
    decisions = _read_tail(op_dir / "decisions.md", n=1)
    last_d = decisions[-1][:60] if decisions else "none"
    return f"op | {goal} | calls={calls} | last: {last_d}"


def _dashboard(op_dir: Path, console: Any) -> None:
    """Render full dashboard to rich console."""
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich import box

    # ---- Load data ----------------------------------------------------------
    contract = _load_json(op_dir / "contract.json")
    cost = _load_json(op_dir / "cost-log.json")
    loop_state = _load_json(op_dir / "loop-state.json")
    sm = _load_json(op_dir / "self-model.json")
    skills_data = _load_json(op_dir / "skills.json")
    task = _read_task_state(op_dir)
    decisions = _read_tail(op_dir / "decisions.md", n=5)
    attempts = _read_tail(op_dir / "attempts.md", n=3)
    todos = _read_tail(op_dir / "todos.md", n=3)

    # ---- Panel 1: Session / Cost / Scope -----------------------------------
    goal = contract.get("goal", "[no contract]")[:60]
    budget = contract.get("complexity_budget", "—")
    agent_id = contract.get("agent_id", "—")[:20]
    in_scope = contract.get("in_scope_files", [])[:3]
    out_scope = contract.get("out_of_scope_files", [])[:3]

    # Cost
    sessions = cost.get("sessions", [])
    total_tokens = sum(s.get("tokens", 0) for s in sessions)
    total_cost_usd = sum(s.get("cost_usd", 0.0) for s in sessions)
    current_session = sessions[-1] if sessions else {}
    sess_tokens = current_session.get("tokens", 0)
    sess_cost = current_session.get("cost_usd", 0.0)

    session_lines = [
        f"[bold]Goal:[/] {goal}",
        f"[bold]Agent:[/] {agent_id}  Budget: {budget}",
        f"[bold]Step:[/] {task.get('current_step', '—')}",
        f"[bold]Calls:[/] {task.get('tool_call_count', '—')}",
        f"[bold]Tokens (session/total):[/] {sess_tokens:,} / {total_tokens:,}",
        f"[bold]Cost (session/total):[/] ${sess_cost:.4f} / ${total_cost_usd:.4f}",
    ]
    if in_scope:
        session_lines.append(f"[bold]In scope:[/] {', '.join(str(p) for p in in_scope)}")
    if out_scope:
        session_lines.append(f"[dim]Out of scope: {', '.join(str(p) for p in out_scope)}[/]")

    session_panel = Panel(
        "\n".join(session_lines),
        title="[cyan]Session & Scope[/]",
        border_style="cyan",
    )

    # ---- Panel 2: Self-model / Intelligence ---------------------------------
    failure_count = sm.get("total_failures", 0)
    pattern_count = len(sm.get("failure_patterns", {}))
    confidence_map = sm.get("confidence_map", {})
    low_confidence = [k for k, v in confidence_map.items() if isinstance(v, (int, float)) and v < 0.5]

    loops = loop_state.get("loops", {})
    active_loops = [k for k, v in loops.items() if isinstance(v, dict) and v.get("count", 0) >= 2]

    intel_lines = [
        f"[bold]Total failures (all sessions):[/] {failure_count}",
        f"[bold]Failure patterns:[/] {pattern_count}",
    ]
    if low_confidence:
        intel_lines.append(f"[yellow]Low confidence areas:[/] {', '.join(low_confidence[:3])}")
    if active_loops:
        intel_lines.append(f"[red]Active loops:[/] {', '.join(active_loops[:3])}")
    else:
        intel_lines.append("[green]No active loops[/]")

    if attempts:
        intel_lines.append("[bold]Recent attempts:[/]")
        for a in attempts[-2:]:
            intel_lines.append(f"  [dim]{a[:70]}[/]")

    intel_panel = Panel(
        "\n".join(intel_lines),
        title="[yellow]Intelligence & Loops[/]",
        border_style="yellow",
    )

    # ---- Panel 3: Decisions ------------------------------------------------
    dec_lines = ["[bold]Last 5 decisions:[/]"]
    if decisions:
        for d in decisions:
            line = d[:80]
            dec_lines.append(f"  [dim]{line}[/]")
    else:
        dec_lines.append("  [dim](none recorded)[/]")

    dec_panel = Panel(
        "\n".join(dec_lines),
        title="[green]Decisions[/]",
        border_style="green",
    )

    # ---- Panel 4: Task State & TODOs ---------------------------------------
    task_lines = [
        f"[bold]Just did:[/] {task.get('what_done', '—')[:60]}",
    ]
    if todos:
        task_lines.append("[bold]Open TODOs:[/]")
        for t in todos:
            task_lines.append(f"  [dim]• {t[:70]}[/]")
    else:
        task_lines.append("[dim]No open TODOs[/]")

    # Skills
    installed_skills = list(skills_data.get("installed", {}).keys()) if skills_data else []
    if installed_skills:
        task_lines.append(f"[bold]Active skills:[/] {', '.join(installed_skills[:4])}")

    task_panel = Panel(
        "\n".join(task_lines),
        title="[magenta]Task State[/]",
        border_style="magenta",
    )

    console.clear()
    console.print(Columns([session_panel, intel_panel], equal=True, expand=True))
    console.print(Columns([dec_panel, task_panel], equal=True, expand=True))
    console.print(
        f"[dim]OptimusPrime watch | {op_dir} | Press Ctrl+C to exit[/]",
        justify="center",
    )


@click.command("watch")
@click.option("--interval", "-i", default=3, show_default=True, help="Refresh interval in seconds.")
@click.option("--compact", "-c", is_flag=True, default=False, help="Single-line summary mode.")
def watch(interval: int, compact: bool) -> None:
    """Live session dashboard. Updates every N seconds."""
    try:
        from rich.console import Console
    except ImportError:
        click.echo("ERROR: 'rich' is required for op watch. Install it: pip install rich", err=True)
        sys.exit(1)

    op_dir = _find_op_dir()
    if op_dir is None:
        click.echo("ERROR: No .optimusprime/ directory found. Run `op contract init` first.", err=True)
        sys.exit(1)

    console = Console()

    if compact:
        # Compact mode: print single-line every N seconds
        click.echo(f"op watch (compact) — refreshing every {interval}s — Ctrl+C to exit")
        try:
            while True:
                line = _build_compact_line(op_dir)
                click.echo(f"\r{line}", nl=False)
                time.sleep(interval)
        except KeyboardInterrupt:
            click.echo()
            return
    else:
        # Full dashboard mode
        click.echo(f"op watch — refreshing every {interval}s — Ctrl+C to exit")
        try:
            while True:
                _dashboard(op_dir, console)
                time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[dim]Watch stopped.[/]")
            return
