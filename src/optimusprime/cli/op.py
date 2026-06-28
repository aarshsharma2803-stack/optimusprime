"""op — OptimusPrime CLI entry point.

Registered in pyproject.toml as: op = "optimusprime.cli.op:main"
"""

from __future__ import annotations

import click

from optimusprime import __version__
from optimusprime.cli.commands.claude_md import claude_md
from optimusprime.cli.commands.contract import contract
from optimusprime.cli.commands.cost import cost
from optimusprime.cli.commands.decision import decision
from optimusprime.cli.commands.history import history
from optimusprime.cli.commands.intelligence import intel
from optimusprime.cli.commands.skills import skills
from optimusprime.cli.commands.snapshot import resume_cmd, snapshot
from optimusprime.cli.commands.todos import todos
from optimusprime.cli.commands.watch import watch


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="op")
@click.option(
    "--dir",
    "op_dir_override",
    default=None,
    envvar="OP_DIR",
    metavar="PATH",
    help="Path to .optimusprime/ directory (default: auto-detect by walking up from cwd).",
)
@click.pass_context
def cli(ctx: click.Context, op_dir_override: str | None) -> None:
    """OptimusPrime — session state protocol for AI coding.

    Inspect and manage .optimusprime/ data outside of a Claude Code session.
    All data is written automatically during sessions — this CLI lets you read,
    search, and manage it.

    \b
    Quick start:
      op decision list          # see recent decisions
      op snapshot               # view current session snapshot
      op resume                 # what to do next session
      op contract               # current scope contract
      op history                # session timeline
    """
    ctx.ensure_object(dict)
    ctx.obj["op_dir_override"] = op_dir_override


# Register all subcommands
cli.add_command(decision)
cli.add_command(snapshot)
cli.add_command(resume_cmd, name="resume")
cli.add_command(contract)
cli.add_command(todos)
cli.add_command(cost)
cli.add_command(claude_md)
cli.add_command(history)
cli.add_command(intel)
cli.add_command(skills)
cli.add_command(watch)


def main() -> None:
    """Entry point for the installed `op` command."""
    cli()


if __name__ == "__main__":
    main()
