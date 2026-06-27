"""op snapshot / op resume — session bridge files."""

from __future__ import annotations

import click

from optimusprime.cli.common import fmt_ts, get_op_dir, load_json_safe, require_file


@click.group(invoke_without_command=True, name="snapshot")
@click.pass_context
def snapshot(ctx: click.Context) -> None:
    """View current session snapshot."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(show_cmd)


@snapshot.command("show")
@click.pass_obj
def show_cmd(obj: dict) -> None:
    """Print current session-snapshot.md."""
    op_dir = get_op_dir(obj)
    path = require_file(
        op_dir / "session-snapshot.md",
        hint="No snapshot yet. It's written automatically when a Claude Code session ends.",
    )
    click.echo(path.read_text(encoding="utf-8"))


@snapshot.command("history")
@click.pass_obj
def history_cmd(obj: dict) -> None:
    """List archived snapshots by date."""
    op_dir = get_op_dir(obj)
    archives = sorted(op_dir.glob("snapshots/*.md"), reverse=True)
    current = op_dir / "session-snapshot.md"

    if not archives and not current.exists():
        click.echo("No snapshots found.")
        return

    click.echo("Snapshots (newest first):\n")
    if current.exists():
        import os
        mtime = current.stat().st_mtime
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        click.echo(f"  {click.style(dt, fg='cyan')}  session-snapshot.md  (current)")

    for arc in archives:
        click.echo(f"  {arc.stem}  {arc.name}")

    if not archives:
        click.echo("\n  No archived snapshots. Archives are written by session-logger (Session 9).")


@click.command("resume")
@click.pass_obj
def resume_cmd(obj: dict) -> None:
    """Print resume.json in human-readable format."""
    op_dir = get_op_dir(obj)
    path = require_file(
        op_dir / "resume.json",
        hint="No resume state yet. It's written when a Claude Code session ends.",
    )
    r = load_json_safe(path)
    if not r:
        click.echo("resume.json is empty or malformed.")
        return

    click.echo(f"Session:    {r.get('session_id', 'N/A')}")
    click.echo(f"Agent:      {r.get('agent_id', 'N/A')}")
    click.echo(f"Captured:   {fmt_ts(r.get('captured_at', ''))}")
    click.echo(f"Goal:       {r.get('goal', '(no goal)')}")
    click.echo(f"Changed:    {len(r.get('changed_files', []))} file(s)")
    click.echo(f"Decisions:  {r.get('decision_count', 0)}")
    click.echo(f"Attempts:   {r.get('attempt_count', 0)}")
    todos = r.get("open_todos", [])
    click.echo(f"Open TODOs: {len(todos)}")
    if todos:
        for t in todos[:3]:
            click.echo(f"  - {t}")
        if len(todos) > 3:
            click.echo(f"  … and {len(todos) - 3} more")

    next_action = r.get("next_action", "")
    if next_action:
        click.echo(f"\n{click.style('► NEXT:', fg='green', bold=True)} {next_action}")
