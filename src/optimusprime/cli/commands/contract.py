"""op contract — view and manage the scope contract."""

from __future__ import annotations

import json
import os
import subprocess

import click

from optimusprime.cli.common import fmt_ts, get_op_dir, load_json_safe, require_file


@click.group(invoke_without_command=True, name="contract")
@click.pass_context
def contract(ctx: click.Context) -> None:
    """View and manage the scope contract."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(show_cmd)


@contract.command("show")
@click.pass_obj
def show_cmd(obj: dict) -> None:
    """Pretty-print the current contract.json."""
    op_dir = get_op_dir(obj)
    path = require_file(
        op_dir / "contract.json",
        hint="No scope contract yet. It's written by the scope-guard skill at session start.",
    )
    c = load_json_safe(path)
    if not c:
        click.echo("contract.json is empty or malformed.")
        return

    click.echo(click.style("Scope Contract", bold=True))
    click.echo(f"  Goal:     {c.get('goal', '(no goal)')}")
    click.echo(f"  Agent:    {c.get('agent_id', 'main')}")
    click.echo(f"  Session:  {c.get('session_id', 'N/A')}")
    click.echo(f"  Budget:   {c.get('complexity_budget', 'N/A')}")
    click.echo(f"  Created:  {fmt_ts(c.get('created_at', ''))}")

    in_scope = c.get("in_scope", [])
    out_of_scope = c.get("out_of_scope", [])
    click.echo(f"\n  In scope ({len(in_scope)}):")
    for p in in_scope:
        click.echo(f"    + {p}")
    click.echo(f"\n  Out of scope ({len(out_of_scope)}):")
    for p in out_of_scope:
        click.echo(f"    - {p}")


@contract.command("edit")
@click.pass_obj
def edit_cmd(obj: dict) -> None:
    """Open contract.json in $EDITOR."""
    op_dir = get_op_dir(obj)
    path = require_file(op_dir / "contract.json")
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "nano"))
    click.echo(f"Opening {path} in {editor}…")
    subprocess.run([editor, str(path)])


@contract.command("reset")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_obj
def reset_cmd(obj: dict, yes: bool) -> None:
    """Delete contract.json (clears scope enforcement)."""
    op_dir = get_op_dir(obj)
    path = op_dir / "contract.json"
    if not path.exists():
        click.echo("No contract.json to reset.")
        return
    if not yes:
        click.confirm(
            "Delete contract.json? Scope enforcement will be disabled until a new contract is written.",
            abort=True,
        )
    path.unlink()
    click.echo("contract.json deleted. Scope enforcement disabled.")


@contract.command("show-scope")
@click.pass_obj
def show_scope_cmd(obj: dict) -> None:
    """Show in-scope and out-of-scope file patterns as two clear lists."""
    op_dir = get_op_dir(obj)
    path = require_file(op_dir / "contract.json")
    c = load_json_safe(path)

    in_scope = c.get("in_scope", [])
    out_scope = c.get("out_of_scope", [])

    click.echo(click.style("IN SCOPE", fg="green", bold=True))
    if in_scope:
        for p in in_scope:
            click.echo(f"  ✓  {p}")
    else:
        click.echo("  (none specified — all files in scope)")

    click.echo()
    click.echo(click.style("OUT OF SCOPE", fg="red", bold=True))
    if out_scope:
        for p in out_scope:
            click.echo(f"  ✗  {p}")
    else:
        click.echo("  (none specified)")
