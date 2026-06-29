"""op conductor — agentic orchestration CLI.

Sub-commands:
  start        Plan and run a conductor session
  plan         Plan only (dry-run)
  status       Show current session state
  resume       Resume a paused session
  pause        Pause between subtasks
  abort        Abort the current session
  log          Print conductor-log.md
  escalations  Print conductor-escalations.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from optimusprime.cli.common import get_op_dir

try:
    from rich.console import Console
    from rich.rule import Rule
    from rich.table import Table
    _RICH = True
except ImportError:
    _RICH = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_session(op_dir: Path) -> Optional[dict]:
    path = op_dir / "conductor-session.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _get_conductor(op_dir: Path):
    from optimusprime.conductor import Conductor
    return Conductor(op_dir, op_dir.parent)


def _print_plan_text(session) -> None:
    """Plain-text plan display."""
    click.echo("CONDUCTOR PLAN")
    click.echo("━" * 60)
    click.echo(f"Goal: {session.goal}")
    click.echo(f"Subtasks: {len(session.subtasks)}\n")
    for i, st in enumerate(session.subtasks, 1):
        complexity = "low" if i <= 2 else "medium" if i <= 5 else "high"
        click.echo(f"  {i}. [{st.id}] {st.description}")
        if st.file_scope:
            click.echo(f"     Files: {', '.join(st.file_scope[:3])}")
        click.echo(f"     Est. complexity: {complexity}")
    click.echo("━" * 60)


def _print_status_text(data: dict) -> None:
    """Plain-text session status."""
    subtasks = data.get("subtasks", [])
    status_icons = {
        "done": "✓", "escalated": "⚠", "failed": "✗",
        "pending": "○", "running": "⟳", "skipped": "—",
    }
    done_count = sum(1 for s in subtasks if s.get("status") == "done")
    click.echo("CONDUCTOR STATUS")
    click.echo(f"Session:     {data.get('session_id', 'unknown')}")
    click.echo(f"Status:      {data.get('status', 'unknown')}")
    click.echo(f"Progress:    {done_count}/{len(subtasks)} subtasks")
    click.echo(f"Escalations: {data.get('escalation_count', 0)}")
    click.echo(f"Tokens:      ~{data.get('total_tokens', 0):,}")
    click.echo(f"Cost:        ~${data.get('total_cost_estimate', 0):.4f}")
    if subtasks:
        click.echo("")
        click.echo(f"{'ID':<14}  {'Description':<36}  {'Status':<12}  {'Attempts':>8}")
        click.echo("─" * 76)
        for st in subtasks:
            icon = status_icons.get(st.get("status", ""), "?")
            click.echo(
                f"{st.get('id', ''):<14}  "
                f"{st.get('description', '')[:35]:<36}  "
                f"{icon} {st.get('status', ''):<10}  "
                f"{st.get('attempts', 0):>8}"
            )


# ---------------------------------------------------------------------------
# conductor group
# ---------------------------------------------------------------------------

@click.group("conductor")
@click.pass_context
def conductor(ctx: click.Context) -> None:
    """Agentic orchestration — define a goal, Conductor does the rest.

    \b
    Examples:
      op conductor start --goal "build the auth system"
      op conductor status
      op conductor resume
      op conductor abort
    """
    ctx.ensure_object(dict)


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

@conductor.command("start")
@click.option("--goal", "-g", required=True, help="Goal for this conductor session.")
@click.option("--dry-run", is_flag=True, default=False, help="Plan only, do not execute.")
@click.pass_context
def conductor_start(ctx: click.Context, goal: str, dry_run: bool) -> None:
    """Plan and run a conductor session."""
    op_dir = get_op_dir(ctx.obj)
    c = _get_conductor(op_dir)

    # Prerequisite check
    problems = c._check_prerequisites()
    if problems:
        for p in problems:
            click.echo(f"Error: {p}", err=True)
        sys.exit(1)

    try:
        session = c.plan(goal)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    _print_plan_text(session)

    tokens = len(session.subtasks) * 2000
    cost = tokens * 0.003 / 1000

    # Show intelligence pre-flight warnings from conductor-plan.md
    plan_path = op_dir / "conductor-plan.md"
    if plan_path.is_file():
        try:
            content = plan_path.read_text(encoding="utf-8")
            in_pf = False
            pf_lines = []
            for line in content.splitlines():
                if "Intelligence Pre-flight" in line:
                    in_pf = True
                    continue
                if in_pf and line.startswith("## "):
                    in_pf = False
                if in_pf and line.strip():
                    pf_lines.append(line.strip())
            if pf_lines:
                click.echo("\nIntelligence pre-flight:")
                for l in pf_lines[:5]:
                    click.echo(f"  {l}")
        except Exception:
            pass

    click.echo(f"\nBudget estimate: ~{tokens:,} tokens (~${cost:.4f})")

    if dry_run:
        click.echo("(dry-run: no execution)")
        return

    click.echo("")
    if not click.confirm("Proceed?", default=False):
        click.echo("Aborted.")
        return

    click.echo("")
    total = len(session.subtasks)
    for i, st in enumerate(session.subtasks, 1):
        click.echo(f"[{i}/{total}] ⟳ Running: {st.description[:55]}...")

    try:
        session = c.run(session, dry_run=False)
    except Exception as e:
        click.echo(f"\nError during execution: {e}", err=True)
        sys.exit(1)

    click.echo("")
    for i, st in enumerate(session.subtasks, 1):
        icon = {"done": "✓", "escalated": "⚠", "failed": "✗", "skipped": "—"}.get(st.status, "?")
        tok = f"({st.token_estimate} tokens)" if st.token_estimate else ""
        if st.status == "escalated":
            click.echo(f"[{i}/{total}] {icon} ESCALATED: {st.description[:50]}")
        else:
            click.echo(f"[{i}/{total}] {icon} Done: {st.description[:50]} {tok}")

    click.echo(
        f"\nSession {session.session_id}: {session.status} | "
        f"~{session.total_tokens:,} tokens | ~${session.total_cost_estimate:.4f}"
    )


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

@conductor.command("plan")
@click.option("--goal", "-g", required=True, help="Goal to decompose into subtasks.")
@click.pass_context
def conductor_plan(ctx: click.Context, goal: str) -> None:
    """Plan only — show subtask breakdown without running."""
    op_dir = get_op_dir(ctx.obj)
    c = _get_conductor(op_dir)

    problems = c._check_prerequisites()
    if problems:
        for p in problems:
            click.echo(f"Error: {p}", err=True)
        sys.exit(1)

    try:
        session = c.plan(goal)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    _print_plan_text(session)
    tokens = len(session.subtasks) * 2000
    cost = tokens * 0.003 / 1000
    click.echo(f"\nBudget estimate: ~{tokens:,} tokens (~${cost:.4f})")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@conductor.command("status")
@click.pass_context
def conductor_status(ctx: click.Context) -> None:
    """Show current conductor session state."""
    op_dir = get_op_dir(ctx.obj)
    data = _load_session(op_dir)
    if not data:
        click.echo("No conductor session found.")
        click.echo("Run: op conductor start --goal '<your goal>'")
        return
    _print_status_text(data)


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------

@conductor.command("resume")
@click.option("--context", "-c", "context_msg", default="", help="Context to inject before continuing.")
@click.pass_context
def conductor_resume(ctx: click.Context, context_msg: str) -> None:
    """Resume a paused conductor session after human intervention."""
    op_dir = get_op_dir(ctx.obj)
    data = _load_session(op_dir)
    if not data:
        click.echo("No conductor session found. Nothing to resume.")
        return
    if data.get("status") not in ("paused", "planning"):
        click.echo(
            f"Session is '{data.get('status')}', not paused. Nothing to resume."
        )
        return

    if not context_msg:
        context_msg = click.prompt(
            "What should Claude know before continuing?\n"
            "(describe how you resolved the escalation, or press Enter to skip)",
            default="",
        )

    c = _get_conductor(op_dir)
    try:
        session = c.resume(context_msg)
        click.echo(f"Resumed. Session status: {session.status}")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# pause
# ---------------------------------------------------------------------------

@conductor.command("pause")
@click.pass_context
def conductor_pause(ctx: click.Context) -> None:
    """Mark session as paused (takes effect between subtasks)."""
    op_dir = get_op_dir(ctx.obj)
    data = _load_session(op_dir)
    if not data:
        click.echo("No conductor session found. Nothing to pause.")
        return
    data["status"] = "paused"
    path = op_dir / "conductor-session.json"
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        click.echo("Session marked as paused. Will stop after current subtask.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# abort
# ---------------------------------------------------------------------------

@conductor.command("abort")
@click.pass_context
def conductor_abort(ctx: click.Context) -> None:
    """Abort the current conductor session."""
    op_dir = get_op_dir(ctx.obj)
    data = _load_session(op_dir)
    if not data:
        click.echo("No conductor session found. Nothing to abort.")
        return

    click.confirm("Abort conductor session? This cannot be undone.", abort=True)

    c = _get_conductor(op_dir)
    try:
        c.abort()
        subtasks = data.get("subtasks", [])
        done = [s for s in subtasks if s.get("status") == "done"]
        click.echo(f"Session aborted. Completed {len(done)}/{len(subtasks)} subtasks.")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

@conductor.command("log")
@click.pass_context
def conductor_log(ctx: click.Context) -> None:
    """Print the conductor completion log."""
    op_dir = get_op_dir(ctx.obj)
    log_path = op_dir / "conductor-log.md"
    if not log_path.is_file():
        click.echo("No conductor log found. Run 'op conductor start' first.")
        return
    content = log_path.read_text(encoding="utf-8").strip()
    if not content:
        click.echo("Conductor log is empty.")
        return
    click.echo(content)


# ---------------------------------------------------------------------------
# escalations
# ---------------------------------------------------------------------------

@conductor.command("escalations")
@click.pass_context
def conductor_escalations(ctx: click.Context) -> None:
    """Print all escalations with reasons and suggested actions."""
    op_dir = get_op_dir(ctx.obj)
    esc_path = op_dir / "conductor-escalations.md"
    if not esc_path.is_file():
        click.echo("No escalations recorded. Everything completed successfully.")
        return
    content = esc_path.read_text(encoding="utf-8").strip()
    if not content:
        click.echo("No escalations recorded.")
        return
    click.echo(content)
