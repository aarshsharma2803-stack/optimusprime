"""op claude-md — generate and maintain CLAUDE.md."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import click

from optimusprime.cli.common import fmt_ts, get_op_dir, parse_decisions, require_file
from optimusprime.utils import find_project_root


@click.group(name="claude-md")
def claude_md() -> None:
    """Generate and maintain CLAUDE.md."""


@claude_md.command("generate")
@click.pass_obj
def generate_cmd(obj: dict) -> None:
    """Print instructions to trigger the claude-md-generator skill in Claude Code."""
    op_dir = get_op_dir(obj)
    decisions_path = op_dir / "decisions.md"
    n_decisions = 0
    if decisions_path.exists():
        entries = parse_decisions(decisions_path.read_text(encoding="utf-8"))
        n_decisions = sum(1 for e in entries if e["prefix"] == "DECISION")

    project_root = find_project_root() or Path.cwd()
    claude_md_path = project_root / "CLAUDE.md"

    click.echo(click.style("CLAUDE.md Generator", bold=True))
    click.echo()
    click.echo(f"Project root: {project_root}")
    click.echo(f"CLAUDE.md:    {'exists' if claude_md_path.exists() else 'missing'}")
    click.echo(f"Decisions:    {n_decisions} logged in decisions.md")
    click.echo()
    click.echo("To generate CLAUDE.md, say this to Claude Code:")
    click.echo()
    click.echo(click.style('  "generate CLAUDE.md"', fg="cyan"))
    click.echo()
    click.echo("The claude-md-generator skill will analyze the codebase and")
    click.echo(f"incorporate {n_decisions} decision(s) from .optimusprime/decisions.md.")


@claude_md.command("status")
@click.pass_obj
def status_cmd(obj: dict) -> None:
    """Check CLAUDE.md freshness vs decisions.md."""
    op_dir = get_op_dir(obj)
    project_root = find_project_root() or Path.cwd()
    claude_md_path = project_root / "CLAUDE.md"

    if not claude_md_path.exists():
        click.echo(click.style("MISSING", fg="red", bold=True) + " — CLAUDE.md not found")
        click.echo(f"Expected at: {claude_md_path}")
        click.echo("Run: op claude-md generate (then follow the instructions)")
        return

    mtime = claude_md_path.stat().st_mtime
    mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    age_days = (datetime.now(timezone.utc) - mtime_dt).days

    click.echo(f"CLAUDE.md:    {claude_md_path}")
    click.echo(f"Last updated: {mtime_dt.strftime('%Y-%m-%d %H:%M UTC')} ({age_days}d ago)")

    decisions_path = op_dir / "decisions.md"
    if not decisions_path.exists():
        click.echo("decisions.md: not found — no staleness data")
        return

    entries = parse_decisions(decisions_path.read_text(encoding="utf-8"))
    decisions = [e for e in entries if e["prefix"] == "DECISION"]

    newer = []
    for d in decisions:
        try:
            ts = datetime.fromisoformat(d["ts"].rstrip("Z")).replace(tzinfo=timezone.utc)
            if ts > mtime_dt:
                newer.append(d)
        except Exception:
            pass

    if newer:
        click.echo(
            click.style(f"\n{len(newer)} decision(s) made AFTER CLAUDE.md was last written:", fg="yellow")
        )
        for d in newer[-5:]:
            click.echo(f"  [{fmt_ts(d['ts'])}] {d['body'][:80]}")
        if len(newer) > 5:
            click.echo(f"  … and {len(newer) - 5} more")
        click.echo("\nRun: op claude-md generate  (then ask Claude to regenerate)")
    else:
        click.echo(click.style("\nFRESH", fg="green") + f" — CLAUDE.md is up to date with all {len(decisions)} decisions.")


@claude_md.command("sync")
@click.pass_obj
def sync_cmd(obj: dict) -> None:
    """Show decisions not yet reflected in CLAUDE.md."""
    op_dir = get_op_dir(obj)
    project_root = find_project_root() or Path.cwd()
    claude_md_path = project_root / "CLAUDE.md"

    if not claude_md_path.exists():
        click.echo("CLAUDE.md not found. Run: op claude-md generate")
        return

    claude_text = claude_md_path.read_text(encoding="utf-8").lower()
    decisions_path = op_dir / "decisions.md"
    if not decisions_path.exists():
        click.echo("No decisions.md — nothing to sync.")
        return

    entries = parse_decisions(decisions_path.read_text(encoding="utf-8"))
    decisions = [e for e in entries if e["prefix"] == "DECISION"]

    unsynced = []
    for d in decisions:
        # Simple heuristic: check if key words from decision body appear in CLAUDE.md
        words = re.findall(r"\b\w{5,}\b", d["body"].lower())
        significant = [w for w in words if w not in {"chose", "using", "because", "decision", "decided", "build"}]
        if significant and not any(w in claude_text for w in significant[:3]):
            unsynced.append(d)

    if not unsynced:
        click.echo(f"All {len(decisions)} decisions appear reflected in CLAUDE.md.")
        return

    click.echo(f"{len(unsynced)} decision(s) may not be reflected in CLAUDE.md:\n")
    for d in unsynced:
        click.echo(f"  [{fmt_ts(d['ts'])}] {d['body'][:90]}")
    click.echo(f"\nRun: op claude-md generate  (ask Claude to regenerate with --sync)")
