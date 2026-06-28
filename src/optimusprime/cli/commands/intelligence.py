"""op intel — reasoning and pattern analysis over decisions.md."""

from __future__ import annotations

import click

from optimusprime.cli.common import fmt_ts, get_op_dir, require_file


@click.group(invoke_without_command=True, name="intel")
@click.pass_context
def intel(ctx: click.Context) -> None:
    """Reason about and detect patterns in the decision history."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(summary)


@intel.command("ask")
@click.argument("question")
@click.pass_obj
def ask(obj: dict, question: str) -> None:
    """Answer QUESTION using structured analysis of decisions.md.

    Example: op intel ask "why did we choose TF-IDF over embeddings"
    """
    from optimusprime.intelligence import IntelligenceEngine

    op_dir = get_op_dir(obj)
    require_file(
        op_dir / "decisions.md",
        hint="No decisions logged yet. They're written automatically during Claude Code sessions.",
    )
    engine = IntelligenceEngine(op_dir)
    click.echo(engine.reason_about(question))


@intel.command("contradictions")
@click.option("--all", "show_all", is_flag=True, help="Include soft contradictions (default: hard only)")
@click.pass_obj
def contradictions(obj: dict, show_all: bool) -> None:
    """Scan decisions.md for contradictions.

    By default shows only hard contradictions (explicit REJECTED list conflicts).
    Use --all to include soft contradictions (same topic, different choices).
    """
    from optimusprime.intelligence import IntelligenceEngine

    op_dir = get_op_dir(obj)
    require_file(op_dir / "decisions.md", hint="No decisions logged yet.")
    engine = IntelligenceEngine(op_dir)

    recs = engine._decisions
    if not recs:
        click.echo("No decisions to analyze.")
        return

    found: list = []
    seen: set = set()

    for i, rec in enumerate(recs):
        past = recs[:i]
        if not past:
            continue
        results = engine.detect_contradictions(rec, past_decisions=past)
        for r in results:
            if not show_all and r.severity != "hard":
                continue
            key = (r.past.raw[:60], r.current.raw[:60])
            if key in seen:
                continue
            seen.add(key)
            found.append(r)

    if not found:
        severity_label = "hard or soft" if show_all else "hard"
        click.echo(f"No {severity_label} contradictions detected in {len(recs)} decisions.")
        return

    sev_label = "hard and soft" if show_all else "hard"
    click.echo(f"{len(found)} {sev_label} contradiction(s) found:\n")
    for c in found:
        color = "red" if c.severity == "hard" else "yellow"
        badge = click.style(f"[{c.severity.upper()}]", fg=color, bold=True)
        click.echo(f"  {badge} score={c.similarity_score:.2f}")
        click.echo(f"    Past:    [{fmt_ts(c.past.timestamp)}] {c.past.decided[:80]}")
        click.echo(f"    Current: [{fmt_ts(c.current.timestamp)}] {c.current.decided[:80]}")
        click.echo(f"    {c.explanation}")
        click.echo()


@intel.command("patterns")
@click.pass_obj
def patterns(obj: dict) -> None:
    """Show decision patterns clustered by topic with velocity metrics."""
    from optimusprime.intelligence import IntelligenceEngine

    op_dir = get_op_dir(obj)
    require_file(op_dir / "decisions.md", hint="No decisions logged yet.")
    engine = IntelligenceEngine(op_dir)

    results = engine.find_patterns()
    if not results:
        click.echo("No patterns yet. Decisions are logged during Claude Code sessions.")
        return

    click.echo(f"Decision patterns ({len(engine._decisions)} total decisions):\n")
    for p in results:
        instab = click.style(" [UNSTABLE]", fg="red") if p.unstable else ""
        click.echo(
            f"  {click.style(p.topic.upper(), bold=True)}{instab}  "
            f"{p.decision_count} decisions  velocity={p.velocity:.1f}/session"
            + (f"  {p.rejected_count} rejected alternatives" if p.rejected_count else "")
        )
        for rec in p.decisions[:3]:
            click.echo(f"    • {rec.decided[:80]}")
        if len(p.decisions) > 3:
            click.echo(f"    … {len(p.decisions) - 3} more")
        click.echo()


@intel.command("summary")
@click.pass_obj
def summary(obj: dict) -> None:
    """Summarize intelligence across all decisions: topics, velocity, contradictions."""
    from optimusprime.intelligence import IntelligenceEngine

    op_dir = get_op_dir(obj)
    path = op_dir / "decisions.md"
    if not path.exists():
        click.echo("No decisions logged yet.")
        return

    engine = IntelligenceEngine(op_dir)
    recs = engine._decisions
    if not recs:
        click.echo("No decisions to summarize.")
        return

    pat_list = engine.find_patterns()
    topics_str = ", ".join(p.topic for p in pat_list[:5]) or "none"
    unstable = [p for p in pat_list if p.unstable]
    sessions = sorted({r.session_date for r in recs if r.session_date})

    click.echo(f"Intelligence summary — {len(recs)} decisions across {len(sessions)} session(s)\n")
    click.echo(f"  Topics:    {topics_str}")
    click.echo(f"  Sessions:  {', '.join(sessions[-3:])}")
    if unstable:
        click.echo(
            f"  Unstable:  {click.style(', '.join(p.topic for p in unstable), fg='red')}"
        )
    else:
        click.echo("  Stability: all topics stable")

    # Quick contradiction scan (hard only)
    hard_count = 0
    seen: set = set()
    for i, rec in enumerate(recs):
        for c in engine.detect_contradictions(rec, past_decisions=recs[:i]):
            if c.severity == "hard":
                key = (c.past.raw[:60], c.current.raw[:60])
                if key not in seen:
                    seen.add(key)
                    hard_count += 1
    if hard_count:
        click.echo(
            f"  Contradictions: {click.style(str(hard_count) + ' hard', fg='red')} "
            "(run `op intel contradictions` for details)"
        )
    else:
        click.echo("  Contradictions: none detected")
