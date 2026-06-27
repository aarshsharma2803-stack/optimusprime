"""op cost — session cost and token usage report."""

from __future__ import annotations

import click

from optimusprime.cli.common import fmt_table, fmt_ts, get_op_dir, load_json_safe


def _load_sessions(op_dir) -> list[dict]:
    path = op_dir / "cost-log.json"
    if not path.exists():
        return []
    data = load_json_safe(path)
    return data.get("sessions", [])


def _fmt_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _fmt_cost(usd: float) -> str:
    return f"${usd:.4f}"


@click.group(invoke_without_command=True, name="cost")
@click.pass_context
def cost(ctx: click.Context) -> None:
    """Session cost and token usage report."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(table_cmd)


@cost.command("show")
@click.pass_obj
def table_cmd(obj: dict) -> None:
    """Print all sessions as a table."""
    op_dir = get_op_dir(obj)
    sessions = _load_sessions(op_dir)
    if not sessions:
        click.echo("No cost data yet. It's written by the cost-awareness skill during sessions.")
        return

    headers = ["Date", "Session", "In (tokens)", "Out (tokens)", "Est. USD"]
    rows = []
    for s in sessions:
        rows.append([
            fmt_ts(s.get("recorded_at", s.get("started_at", ""))),
            s.get("session_id", "N/A")[:8],
            _fmt_tokens(s.get("estimated_input_tokens", s.get("input_tokens", 0))),
            _fmt_tokens(s.get("estimated_output_tokens", s.get("output_tokens", 0))),
            _fmt_cost(s.get("estimated_cost_usd", 0.0)),
        ])

    click.echo(fmt_table(headers, rows))


@cost.command("total")
@click.pass_obj
def total_cmd(obj: dict) -> None:
    """Print cumulative totals across all sessions."""
    op_dir = get_op_dir(obj)
    sessions = _load_sessions(op_dir)
    if not sessions:
        click.echo("No cost data yet.")
        return

    total_in = sum(s.get("estimated_input_tokens", s.get("input_tokens", 0)) for s in sessions)
    total_out = sum(s.get("estimated_output_tokens", s.get("output_tokens", 0)) for s in sessions)
    total_cost = sum(s.get("estimated_cost_usd", 0.0) for s in sessions)

    click.echo(f"Sessions: {len(sessions)}")
    click.echo(f"Total in:  {_fmt_tokens(total_in)} tokens")
    click.echo(f"Total out: {_fmt_tokens(total_out)} tokens")
    click.echo(f"Total:     {_fmt_cost(total_cost)}")


@cost.command("last")
@click.pass_obj
def last_cmd(obj: dict) -> None:
    """Print most recent session only."""
    op_dir = get_op_dir(obj)
    sessions = _load_sessions(op_dir)
    if not sessions:
        click.echo("No cost data yet.")
        return

    s = sessions[-1]
    click.echo(f"Session:   {s.get('session_id', 'N/A')[:8]}")
    click.echo(f"Date:      {fmt_ts(s.get('recorded_at', s.get('started_at', '?')))}")
    click.echo(f"In:        {_fmt_tokens(s.get('estimated_input_tokens', s.get('input_tokens', 0)))} tokens")
    click.echo(f"Out:       {_fmt_tokens(s.get('estimated_output_tokens', s.get('output_tokens', 0)))} tokens")
    click.echo(f"Est. cost: {_fmt_cost(s.get('estimated_cost_usd', 0.0))}")
