"""Shared helpers for all CLI commands."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import click

from optimusprime.utils import find_optimusprime_dir

_DECISION_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+(?P<prefix>\w+)[:\s]+(?P<body>.+)$"
)


def get_op_dir(obj: dict) -> Path:
    """Resolve .optimusprime/ from CLI context object. Raises ClickException if not found."""
    override = (obj or {}).get("op_dir_override")
    if override:
        p = Path(override)
        if p.is_dir():
            return p
        raise click.ClickException(f"Directory not found: {override}")
    p = find_optimusprime_dir()
    if p is None:
        raise click.ClickException(
            "No .optimusprime/ directory found.\n\n"
            "Run from inside a project that uses OptimusPrime, or use --dir to specify the path.\n"
            "To initialize: create a .optimusprime/ directory and start a Claude Code session."
        )
    return p


def require_file(path: Path, hint: str = "") -> Path:
    """Return path if it exists, else raise a helpful ClickException."""
    if not path.exists():
        msg = f"{path.name} not found in {path.parent}"
        if hint:
            msg += f"\n{hint}"
        raise click.ClickException(msg)
    return path


def parse_decisions(text: str) -> list[dict[str, str]]:
    """Parse decisions.md lines into list of dicts with ts/tag/prefix/body."""
    entries = []
    for line in text.splitlines():
        m = _DECISION_RE.match(line.strip())
        if m:
            entries.append({
                "ts": m.group("ts"),
                "tag": m.group("tag"),
                "prefix": m.group("prefix"),
                "body": m.group("body").strip(),
            })
    return entries


def load_json_safe(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fmt_table(headers: list[str], rows: list[list[str]], sep: str = "  ") -> str:
    """Minimal table formatter — no external deps."""
    all_rows = [headers] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in all_rows) for i in range(len(headers))]
    divider = "─" * (sum(widths) + len(sep) * (len(widths) - 1))

    def fmt_row(row: list[str]) -> str:
        return sep.join(c.ljust(w) for c, w in zip(row, widths))

    lines = [fmt_row(headers), divider]
    for row in rows:
        lines.append(fmt_row([str(c) for c in row]))
    return "\n".join(lines)


def fmt_ts(iso: str) -> str:
    """Format ISO timestamp to readable form."""
    try:
        dt = datetime.fromisoformat(iso.rstrip("Z")).replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]
