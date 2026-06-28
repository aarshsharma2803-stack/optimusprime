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


@intel.command("learned")
@click.pass_obj
def learned(obj: dict) -> None:
    """Show accumulated learned patterns from patterns.json.

    Displays skill activation thresholds, library preferences, failure patterns,
    user profile, and unstable areas learned across all analyzed sessions.
    """
    from optimusprime.cli.common import get_op_dir
    from optimusprime.utils import load_json

    op_dir = get_op_dir(obj)
    p = load_json(op_dir / "patterns.json")

    if not p or p.get("sessions_analyzed", 0) == 0:
        click.echo("No learned patterns yet. Run at least one session with OptimusPrime installed.")
        return

    n = p.get("sessions_analyzed", 0)
    click.echo(click.style(f"LEARNED PATTERNS ({n} session{'s' if n != 1 else ''} analyzed)\n", bold=True))

    # Skill activation
    sa = p.get("skill_activation", {})
    if sa:
        click.echo(click.style("Skill Activation:", bold=True))
        for skill, entry in sa.items():
            conf = entry.get("confidence", "default")
            learned_t = entry.get("user_threshold_tokens", 0)
            default_t = entry.get("default_threshold_tokens", 60000)
            if conf == "learned":
                diff = f"(default was {default_t:,})"
                click.echo(
                    f"  {skill}: threshold {learned_t:,} tokens "
                    + click.style("[learned]", fg="green")
                    + f" {diff}"
                )
            else:
                click.echo(f"  {skill}: threshold {learned_t:,} tokens [default]")
        click.echo()

    # Library preferences
    prefs = p.get("user_preferences", {})
    preferred = prefs.get("preferred_libraries", {})
    avoided = prefs.get("avoided_libraries", {})
    if preferred or avoided:
        click.echo(click.style("Preferred Libraries:", bold=True))
        if preferred:
            top_preferred = sorted(preferred.items(), key=lambda x: -x[1])[:5]
            for lib, count in top_preferred:
                click.echo(f"  {lib} (decided {count}x)")
        if avoided:
            top_avoided = sorted(avoided.items(), key=lambda x: -x[1])[:3]
            avoided_str = ", ".join(f"{lib} rejected {count}x" for lib, count in top_avoided)
            click.echo(f"  avoided: {avoided_str}")
        click.echo()

    # Failure patterns
    fp = p.get("failure_patterns", {})
    active_fp = {k: v for k, v in fp.items() if not v.get("resolved")}
    if active_fp:
        click.echo(click.style("Failure Patterns:", bold=True))
        for file_key, entry in list(active_fp.items())[:5]:
            errs = ", ".join(entry.get("errors", [])[:2])
            count = entry.get("occurrence_count", 0)
            click.echo(f"  {file_key}: {count} failure(s) — {errs or 'no error detail'}")
        click.echo()

    # User profile
    click.echo(click.style("User Profile:", bold=True))
    depth = prefs.get("explanation_depth", "unknown")
    avg_dec = prefs.get("avg_decisions_per_session", 0.0)
    avg_att = prefs.get("avg_failed_attempts_per_session", 0.0)
    dist = prefs.get("complexity_distribution", {})
    dominant = max(dist.items(), key=lambda x: x[1])[0] if dist and any(dist.values()) else "unknown"
    total_c = sum(dist.values()) or 1
    dominant_pct = int(dist.get(dominant, 0) / total_c * n) if total_c else 0
    click.echo(f"  Explanation depth: {depth}")
    click.echo(f"  Avg decisions/session: {avg_dec:.1f}")
    click.echo(f"  Avg failed attempts/session: {avg_att:.1f}")
    click.echo(f"  Complexity: mostly {dominant} ({dominant_pct}/{n} sessions)")
    click.echo()

    # Unstable areas
    unstable = p.get("unstable_areas", [])
    if unstable:
        click.echo(
            click.style("Unstable Areas: ", bold=True)
            + click.style(", ".join(unstable), fg="red")
        )
    else:
        click.echo(click.style("Unstable Areas: ", bold=True) + "(none)")


@intel.command("session-history")
@click.option("--all", "show_all", is_flag=True, help="Show full history (default: last 10)")
@click.pass_obj
def session_history(obj: dict, show_all: bool) -> None:
    """Show session history from patterns.json.

    Displays date, goal, decisions made, failures, and topics for each session.
    """
    from optimusprime.cli.common import get_op_dir
    from optimusprime.utils import load_json

    op_dir = get_op_dir(obj)
    p = load_json(op_dir / "patterns.json")

    history = p.get("session_history", [])
    if not history:
        click.echo("No session history yet. Sessions are recorded as the learner runs.")
        return

    shown = history if show_all else history[-10:]
    click.echo(
        click.style(
            f"Session History ({len(shown)} of {len(history)} sessions shown)\n",
            bold=True,
        )
    )

    # Header
    col_w = [10, 36, 9, 8, 20]
    header = (
        f"{'Date':<{col_w[0]}}  {'Goal':<{col_w[1]}}  "
        f"{'Decisions':>{col_w[2]}}  {'Failures':>{col_w[3]}}  {'Topics':<{col_w[4]}}"
    )
    click.echo(click.style(header, bold=True))
    click.echo("─" * sum(col_w + [len(col_w) * 2]))

    for entry in shown:
        ts = entry.get("captured_at", "")
        date = ts[:10] if len(ts) >= 10 else entry.get("session_id", "")[:8]
        goal = entry.get("goal", "")[:col_w[1]]
        decisions = entry.get("decisions_made", 0)
        failures = entry.get("attempts_failed", 0)
        topics = ", ".join(entry.get("topics", []))[:col_w[4]]

        fail_str = str(failures)
        if failures > 0:
            fail_str = click.style(fail_str, fg="yellow")

        click.echo(
            f"{date:<{col_w[0]}}  {goal:<{col_w[1]}}  "
            f"{decisions:>{col_w[2]}}  {fail_str:>{col_w[3]}}  {topics:<{col_w[4]}}"
        )


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
