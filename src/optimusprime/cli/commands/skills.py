"""op skills — ecosystem skills hub (stub for Session 7)."""

from __future__ import annotations

import click

from optimusprime.cli.common import get_op_dir, load_json_safe


@click.group(name="skills")
def skills() -> None:
    """Manage ecosystem skills (full implementation in Session 7)."""


@skills.command("list")
@click.pass_obj
def list_cmd(obj: dict) -> None:
    """List installed ecosystem skills."""
    try:
        op_dir = get_op_dir(obj)
        skills_path = op_dir / "skills.json"
        if skills_path.exists():
            data = load_json_safe(skills_path)
            installed = data.get("installed", {})
            if installed:
                click.echo(f"{len(installed)} skill(s) installed:\n")
                for name, info in installed.items():
                    ver = info.get("installed_version", "?")
                    policy = info.get("update_policy", "auto")
                    click.echo(f"  {name:<20} v{ver:<10} [{policy}]")
                return
    except Exception:
        pass
    click.echo(click.style("Skills Hub coming in Session 7.", fg="yellow"))
    click.echo()
    click.echo("Planned skills registry:")
    click.echo("  superpowers   obra/superpowers — workflow methodology")
    click.echo("  gstack        garrytan/gstack  — engineering team toolkit")
    click.echo("  ui-ux-pro-max nextlevelbuilder  — design intelligence")
    click.echo("  caveman       JuliusBrussee    — output compression")
    click.echo("  ponytail      DietrichGebert   — code minimalism")
    click.echo()
    click.echo("Commands coming: op skills install <name>")
    click.echo("                 op skills update [name]")
    click.echo("                 op skills rollback <name>")
    click.echo("                 op skills pin <name>@<version>")


@skills.command("status")
@click.pass_obj
def status_cmd(obj: dict) -> None:
    """Show update status for installed skills."""
    try:
        op_dir = get_op_dir(obj)
        skills_path = op_dir / "skills.json"
        if skills_path.exists():
            data = load_json_safe(skills_path)
            installed = data.get("installed", {})
            if installed:
                click.echo(f"Last checked: {data.get('last_checked', 'never')}")
                for name, info in installed.items():
                    click.echo(f"  {name}: v{info.get('installed_version', '?')} — {info.get('update_policy', 'auto')}")
                return
    except Exception:
        pass
    click.echo(click.style("Skills Hub coming in Session 7.", fg="yellow"))
    click.echo("No skills installed yet.")
