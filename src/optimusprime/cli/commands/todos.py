"""op todos — view and manage open TODOs."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import click

from optimusprime.cli.common import get_op_dir, parse_decisions


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


_TODO_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+(?P<prefix>TODO|FIXME|HACK|XXX)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_DEFERRED_RE = re.compile(r"\[deferred", re.IGNORECASE)


def _parse_todos(text: str) -> list[dict]:
    todos = []
    for line in text.splitlines():
        m = _TODO_LINE_RE.match(line.strip())
        if m:
            todos.append({
                "ts": m.group("ts"),
                "prefix": m.group("prefix").upper(),
                "body": m.group("body").strip(),
                "deferred": bool(_DEFERRED_RE.search(m.group("body"))),
                "raw": line,
            })
    return todos


@click.group(invoke_without_command=True, name="todos")
@click.pass_context
def todos(ctx: click.Context) -> None:
    """View and manage open TODOs."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_cmd)


@todos.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include deferred TODOs")
@click.pass_obj
def list_cmd(obj: dict, show_all: bool) -> None:
    """Print todos.md grouped by file."""
    op_dir = get_op_dir(obj)
    path = op_dir / "todos.md"
    if not path.exists():
        click.echo("No todos.md — no TODOs tracked this session.")
        return

    all_todos = _parse_todos(path.read_text(encoding="utf-8"))
    visible = all_todos if show_all else [t for t in all_todos if not t["deferred"]]

    if not visible:
        if all_todos:
            click.echo(f"All {len(all_todos)} TODOs are deferred. Use --all to view.")
        else:
            click.echo("No TODOs logged.")
        return

    # Group by file (extract filepath from body "filepath:lineno ...")
    by_file: dict[str, list[dict]] = defaultdict(list)
    for t in visible:
        # Body format: "filepath:lineno \"description\""
        m = re.match(r"^(\S+:\d+)", t["body"])
        file_key = m.group(1).split(":")[0] if m else "unknown"
        by_file[file_key].append(t)

    unresolved = sum(1 for t in all_todos if not t["deferred"])
    deferred = sum(1 for t in all_todos if t["deferred"])
    click.echo(f"{unresolved} unresolved, {deferred} deferred\n")

    for filepath, items in sorted(by_file.items()):
        click.echo(click.style(filepath, bold=True))
        for t in items:
            tag_color = {"FIXME": "red", "TODO": "yellow", "HACK": "magenta"}.get(t["prefix"], "white")
            click.echo(
                f"  [{click.style(t['prefix'], fg=tag_color)}] {t['body']}"
            )
        click.echo()


@todos.command("count")
@click.pass_obj
def count_cmd(obj: dict) -> None:
    """Print count of unresolved TODOs."""
    op_dir = get_op_dir(obj)
    path = op_dir / "todos.md"
    if not path.exists():
        click.echo("0 unresolved (todos.md not found)")
        return
    all_todos = _parse_todos(path.read_text(encoding="utf-8"))
    unresolved = sum(1 for t in all_todos if not t["deferred"])
    deferred = sum(1 for t in all_todos if t["deferred"])
    click.echo(f"{unresolved} unresolved, {deferred} deferred ({len(all_todos)} total)")


@todos.command("clear")
@click.option("--yes", is_flag=True, help="Skip confirmation")
@click.pass_obj
def clear_cmd(obj: dict, yes: bool) -> None:
    """Archive todos.md with timestamp (marks all as reviewed)."""
    op_dir = get_op_dir(obj)
    path = op_dir / "todos.md"
    if not path.exists():
        click.echo("No todos.md to clear.")
        return

    all_todos = _parse_todos(path.read_text(encoding="utf-8"))
    unresolved = sum(1 for t in all_todos if not t["deferred"])

    if not yes:
        click.confirm(
            f"Archive todos.md ({unresolved} unresolved, {len(all_todos)} total)?",
            abort=True,
        )

    ts = _utcnow()
    archive = op_dir / f"todos-{ts}.md"
    path.rename(archive)
    click.echo(f"Archived to {archive.name}")
