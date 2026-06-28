"""op skills — ecosystem skills hub CLI."""

from __future__ import annotations

from pathlib import Path

import click

from optimusprime.cli.common import get_op_dir, load_json_safe

_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "ecosystem" / "registry.json"


def _load_registry() -> dict:
    try:
        import json
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"skills": {}}


@click.group(name="skills")
def skills() -> None:
    """Manage ecosystem skills."""


@skills.command("list")
@click.pass_obj
def list_cmd(obj: dict) -> None:
    """List available registry skills and installed status."""
    op_dir = get_op_dir(obj)
    skills_path = op_dir / "skills.json"
    installed_data = load_json_safe(skills_path) if skills_path.exists() else {}
    installed = installed_data.get("installed", {})

    registry = _load_registry()
    skill_defs = registry.get("skills", {})

    if not skill_defs:
        click.echo("Registry not found at ecosystem/registry.json")
        return

    click.echo(f"Skills Registry ({len(skill_defs)} available)\n")
    header = f"  {'Name':<20} {'Source':<40} {'Stars':<8} Status"
    click.echo(click.style(header, bold=True))
    click.echo("  " + "─" * 76)
    for name, info in skill_defs.items():
        source = info.get("source", "")
        stars = info.get("stars", "")
        is_installed = name in installed
        status = click.style("installed", fg="green") if is_installed else "available"
        click.echo(f"  {name:<20} {source:<40} {stars!s:<8} {status}")

    if installed:
        click.echo(f"\n{len(installed)} installed. Run `op skills status` for details.")
    else:
        click.echo("\nNone installed. Run: op skills install <name>")


@skills.command("status")
@click.pass_obj
def status_cmd(obj: dict) -> None:
    """Show update status for installed skills."""
    op_dir = get_op_dir(obj)
    skills_path = op_dir / "skills.json"
    if not skills_path.exists():
        click.echo("No skills installed yet.")
        click.echo("Run: op skills install <name>")
        return

    data = load_json_safe(skills_path)
    installed = data.get("installed", {})
    if not installed:
        click.echo("No skills installed yet.")
        return

    last = data.get("last_checked", "never")
    click.echo(f"Installed skills (last checked: {last})\n")
    for name, info in installed.items():
        ver = info.get("installed_version", "?")
        policy = info.get("update_policy", "auto")
        installed_at = info.get("installed_at", "")[:10]
        click.echo(f"  {name:<20} v{ver:<12} [{policy}]  installed {installed_at}")


@skills.command("install")
@click.argument("name")
@click.option("--pin", "pin_version", help="Pin to a specific version (e.g. 1.2.3)")
@click.pass_obj
def install_cmd(obj: dict, name: str, pin_version: str | None) -> None:
    """Install a skill from the registry. NAME is the skill name (e.g. caveman)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "ecosystem"))
    try:
        from installer import SkillInstaller
        op_dir = get_op_dir(obj)
        installer = SkillInstaller(_REGISTRY_PATH, op_dir)
        ok, msg = installer.install(name, pin_version=pin_version)
        if ok:
            click.echo(click.style(f"✓ {msg}", fg="green"))
        else:
            click.echo(click.style(f"✗ {msg}", fg="red"))
    except ImportError as e:
        click.echo(f"Ecosystem layer not available: {e}")


@skills.command("update")
@click.argument("name", required=False)
@click.pass_obj
def update_cmd(obj: dict, name: str | None) -> None:
    """Update installed skills (or a specific SKILL)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "ecosystem"))
    try:
        from updater import SkillUpdater
        op_dir = get_op_dir(obj)
        updater = SkillUpdater(_REGISTRY_PATH)
        results = updater.update_all(op_dir / "skills.json", skill_name=name)
        if not results:
            click.echo("Nothing to update.")
            return
        for r in results:
            icon = click.style("✓", fg="green") if r.get("updated") else "·"
            click.echo(f"  {icon} {r.get('name','?')}: {r.get('message','')}")
    except ImportError as e:
        click.echo(f"Ecosystem layer not available: {e}")
