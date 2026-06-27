"""op history — session timeline."""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import click

from optimusprime.cli.common import fmt_ts, get_op_dir, load_json_safe, parse_decisions


def _decisions_by_date(entries: list[dict]) -> dict[str, int]:
    """Count DECISION entries per date (YYYY-MM-DD)."""
    counts: dict[str, int] = {}
    for e in entries:
        if e["prefix"] != "DECISION":
            continue
        try:
            dt = datetime.fromisoformat(e["ts"].rstrip("Z")).replace(tzinfo=timezone.utc)
            day = dt.strftime("%Y-%m-%d")
        except Exception:
            day = e["ts"][:10]
        counts[day] = counts.get(day, 0) + 1
    return counts


@click.command("history")
@click.option("--last", "-n", default=None, type=int, help="Show only last N days")
@click.pass_obj
def history(obj: dict, last: int | None) -> None:
    """Show session timeline: date | goal | decisions | files changed."""
    op_dir = get_op_dir(obj)
    decisions_path = op_dir / "decisions.md"
    resume_path = op_dir / "resume.json"

    if not decisions_path.exists() and not resume_path.exists():
        click.echo("No session history found.")
        click.echo("History is built from decisions.md and resume.json during Claude Code sessions.")
        return

    # Most recent session from resume.json
    resume = load_json_safe(resume_path) if resume_path.exists() else {}

    # Decision counts by date
    entries: list[dict] = []
    if decisions_path.exists():
        entries = parse_decisions(decisions_path.read_text(encoding="utf-8"))

    by_date = _decisions_by_date(entries)

    # Filter by --last N days
    cutoff = None
    if last is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=last)).strftime("%Y-%m-%d")

    dates = sorted(by_date.keys(), reverse=True)
    if cutoff:
        dates = [d for d in dates if d >= cutoff]

    if not dates:
        click.echo(f"No sessions in the last {last} day(s)." if last else "No sessions found.")
        return

    click.echo(click.style("Session History", bold=True) + "\n")

    # Header
    click.echo(f"  {'Date':<12} {'Goal':<45} {'Decisions':>9}")
    click.echo("  " + "─" * 70)

    for day in dates:
        # Get goal for this day from resume (only for most recent)
        goal = ""
        if resume and resume.get("captured_at", "").startswith(day):
            goal = resume.get("goal", "")[:45]
        elif day == dates[0] and resume:
            goal = resume.get("goal", "")[:45]

        n_decisions = by_date[day]
        goal_display = goal if goal else click.style("(no goal recorded)", fg="bright_black")
        click.echo(f"  {day:<12} {goal_display:<45} {n_decisions:>9}")

    click.echo()
    total = sum(by_date.values())
    click.echo(f"  Total: {len(dates)} day(s), {total} decisions")

    # Note about limited history
    if not (op_dir / "snapshots").exists():
        click.echo()
        click.echo(
            click.style("  Note:", fg="yellow")
            + " Full history archive coming in Session 9. "
            "Currently showing decisions.md data only."
        )
