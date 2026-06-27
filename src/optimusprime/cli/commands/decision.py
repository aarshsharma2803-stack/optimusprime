"""op decision — search and inspect the decisions log."""

from __future__ import annotations

import click

from optimusprime.cli.common import fmt_ts, get_op_dir, parse_decisions, require_file


@click.group(invoke_without_command=True, name="decision")
@click.pass_context
def decision(ctx: click.Context) -> None:
    """Search and inspect the decisions log."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_cmd)


@decision.command("search")
@click.argument("query")
@click.option("--last", "-n", default=20, show_default=True, help="Max results to show")
@click.pass_obj
def search(obj: dict, query: str, last: int) -> None:
    """Search decisions.md for QUERY (substring, newest first)."""
    op_dir = get_op_dir(obj)
    path = require_file(
        op_dir / "decisions.md",
        hint="No decisions logged yet. They're written automatically during Claude Code sessions.",
    )
    entries = parse_decisions(path.read_text(encoding="utf-8"))
    q = query.lower()
    hits = [e for e in reversed(entries) if q in e["body"].lower() or q in e["prefix"].lower()]

    if not hits:
        click.echo(f'No decisions matching "{query}"')
        return

    click.echo(f'Searching "{query}" — {len(hits)} result(s), newest first:\n')
    for e in hits[:last]:
        prefix_color = "yellow" if e["prefix"] == "BLOCK" else "green"
        click.echo(
            f"  {click.style(fmt_ts(e['ts']), fg='cyan')}  "
            f"{click.style(e['prefix'], fg=prefix_color, bold=True)}: {e['body']}"
        )

    if len(hits) > last:
        click.echo(f"\n  … and {len(hits) - last} more (use --last to see more)")


@decision.command("list")
@click.option("--last", "-n", default=10, show_default=True, help="Number of decisions to show")
@click.option("--all", "show_all", is_flag=True, help="Show all decisions")
@click.pass_obj
def list_cmd(obj: dict, last: int, show_all: bool) -> None:
    """Show recent decisions, newest first."""
    op_dir = get_op_dir(obj)
    path = require_file(
        op_dir / "decisions.md",
        hint="No decisions logged yet.",
    )
    entries = list(reversed(parse_decisions(path.read_text(encoding="utf-8"))))

    if not entries:
        click.echo("No decisions logged yet.")
        return

    visible = entries if show_all else entries[:last]
    label = f"All {len(entries)}" if show_all else f"Last {min(last, len(entries))} of {len(entries)}"
    click.echo(f"{label} decisions (newest first):\n")

    for e in visible:
        prefix_color = {"DECISION": "green", "BLOCK": "yellow", "FAIL": "red"}.get(e["prefix"], "white")
        click.echo(
            f"  {click.style(fmt_ts(e['ts']), fg='cyan')}  "
            f"[{click.style(e['prefix'], fg=prefix_color)}] {e['body']}"
        )

    if not show_all and len(entries) > last:
        click.echo(f"\n  … {len(entries) - last} older decisions hidden. Use --all or --last N.")


@decision.command("count")
@click.pass_obj
def count(obj: dict) -> None:
    """Print total number of decisions logged."""
    op_dir = get_op_dir(obj)
    path = op_dir / "decisions.md"
    if not path.exists():
        click.echo("0 decisions (decisions.md not found)")
        return
    entries = parse_decisions(path.read_text(encoding="utf-8"))
    by_prefix: dict[str, int] = {}
    for e in entries:
        by_prefix[e["prefix"]] = by_prefix.get(e["prefix"], 0) + 1

    click.echo(f"{len(entries)} total entries in decisions.md")
    for prefix, n in sorted(by_prefix.items()):
        click.echo(f"  {prefix}: {n}")
