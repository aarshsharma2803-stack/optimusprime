"""op diff-intel — between-session git diff intelligence.

Reads git diff since last snapshot and cross-references against
.optimusprime/ data to catch scope violations, rejected deps
re-added, and test count drops.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click

from optimusprime.cli.common import get_op_dir, load_json_safe

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(cmd: str, cwd: Path) -> str:
    """Run git command; return stdout or '' on error."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(cwd),
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _is_git_repo(project_root: Path) -> bool:
    out = _run_git("git rev-parse --git-dir", project_root)
    return bool(out)


def _get_changed_files(project_root: Path, since: str) -> List[str]:
    """Get files changed since baseline date."""
    # Try date-based diff first
    out = _run_git(f'git log --name-only --since="{since}" --format="" --', project_root)
    files = [l.strip() for l in out.splitlines() if l.strip()]
    if files:
        return list(dict.fromkeys(files))  # deduplicate, preserve order

    # Fallback: staged+unstaged diff
    out = _run_git("git diff --name-only", project_root)
    staged = _run_git("git diff --cached --name-only", project_root)
    combined = out + "\n" + staged
    return [l.strip() for l in combined.splitlines() if l.strip()]


def _get_diff_stats(project_root: Path, since: str) -> List[str]:
    """Get diff stat lines showing +/- per file."""
    out = _run_git(f'git diff --stat HEAD "$(git log --since="{since}" --format=%H | tail -1)^" 2>/dev/null || git diff --stat', project_root)
    return [l.strip() for l in out.splitlines() if l.strip()]


def _get_commits(project_root: Path, since: str) -> List[str]:
    """Get commit log since baseline."""
    out = _run_git(f'git log --oneline --since="{since}"', project_root)
    return [l.strip() for l in out.splitlines() if l.strip()]


def _get_new_files(project_root: Path) -> List[str]:
    """Get untracked new files from git status."""
    out = _run_git("git status --short", project_root)
    new_files = []
    for line in out.splitlines():
        if line.startswith("??"):
            new_files.append(line[3:].strip())
    return new_files


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def _load_out_of_scope(op_dir: Path) -> List[str]:
    """Load out_of_scope list from contract.json."""
    contract = load_json_safe(op_dir / "contract.json")
    return contract.get("out_of_scope", contract.get("out_of_scope_files", []))


def _load_rejected_terms(op_dir: Path) -> Dict[str, str]:
    """Build {term_lower: timestamp} from REJECTED fields in decisions.md."""
    path = op_dir / "decisions.md"
    if not path.is_file():
        return {}
    rejected: Dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            ts_m = re.match(r"^\[([^\]]+)\]", line)
            ts = ts_m.group(1)[:10] if ts_m else "?"
            rej_m = re.search(r"REJECTED[:\s]+([^|]+)", line, re.IGNORECASE)
            if rej_m:
                for term in rej_m.group(1).split(","):
                    t = term.strip().lower()
                    if t and len(t) > 2:
                        rejected[t] = ts
    except Exception:
        pass
    return rejected


def _check_scope_violations(
    changed_files: List[str], out_of_scope: List[str]
) -> List[str]:
    """Return list of files that match out_of_scope patterns."""
    violations = []
    for f in changed_files:
        for oos in out_of_scope:
            oos_clean = oos.rstrip("/**")
            if f.startswith(oos_clean) or f == oos_clean or Path(f).match(oos):
                violations.append(f)
                break
    return violations


def _check_rejected_deps(
    changed_files: List[str],
    project_root: Path,
    rejected_terms: Dict[str, str],
) -> List[Tuple[str, str, str]]:
    """Return list of (file, dep_name, rejected_when) for re-added rejected deps."""
    dep_files = {"requirements.txt", "package.json", "Cargo.toml", "pyproject.toml"}
    findings: List[Tuple[str, str, str]] = []

    for f in changed_files:
        fname = Path(f).name
        if fname not in dep_files:
            continue
        fpath = project_root / f
        if not fpath.is_file():
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore").lower()
            for term, when in rejected_terms.items():
                if re.search(r"\b" + re.escape(term) + r"\b", content):
                    findings.append((f, term, when))
        except Exception:
            pass

    return findings


def _count_tests(project_root: Path) -> int:
    """Count test functions in project."""
    try:
        result = subprocess.run(
            ["grep", "-r", "--include=test_*.py", "-l", "def test_", "tests/"],
            capture_output=True, text=True, timeout=10, cwd=str(project_root),
        )
        # Count actual test functions
        count_result = subprocess.run(
            ["grep", "-r", "--include=test_*.py", "-c", "def test_"],
            capture_output=True, text=True, timeout=10, cwd=str(project_root),
        )
        total = 0
        for line in count_result.stdout.splitlines():
            parts = line.rsplit(":", 1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                total += int(parts[1].strip())
        return total
    except Exception:
        # Fallback: count test files
        try:
            test_dir = project_root / "tests"
            if test_dir.is_dir():
                return len(list(test_dir.rglob("test_*.py")))
        except Exception:
            pass
        return 0


def _get_baseline_test_count(project_root: Path, since: str) -> int:
    """Estimate test count before baseline by checking git log."""
    try:
        # Get the oldest commit since our baseline
        out = _run_git(f'git log --since="{since}" --format=%H', project_root)
        commits = [l.strip() for l in out.splitlines() if l.strip()]
        if not commits:
            return 0
        oldest_commit = commits[-1]
        # Try to get test count at parent of oldest commit
        parent_out = _run_git(f"git show {oldest_commit}^:tests/ 2>/dev/null | grep -c 'test_'", project_root)
        if parent_out.isdigit():
            return int(parent_out)
    except Exception:
        pass
    return 0


def _get_baseline(op_dir: Path, since_override: Optional[str]) -> str:
    """Get baseline timestamp."""
    if since_override:
        return since_override

    # Read CAPTURED from session-snapshot.md
    snap_path = op_dir / "session-snapshot.md"
    if snap_path.is_file():
        try:
            text = snap_path.read_text(encoding="utf-8")
            m = re.search(r"Generated:\s*([^\s|]+)", text)
            if m:
                ts = m.group(1)
                return ts[:10]
        except Exception:
            pass

    # Fallback: 24 hours ago
    yesterday = datetime.now(tz=timezone.utc) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def _get_new_decision_count(op_dir: Path, since: str) -> int:
    """Count decisions added since baseline date."""
    path = op_dir / "decisions.md"
    if not path.is_file():
        return 0
    count = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                m = re.match(r"^\[(\d{4}-\d{2}-\d{2})", line)
                if m and m.group(1) >= since:
                    count += 1
    except Exception:
        pass
    return count


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def _render_diff_intel(
    baseline: str,
    commits: List[str],
    changed_files: List[str],
    in_scope: List[str],
    oos_violations: List[str],
    rejected_findings: List[Tuple[str, str, str]],
    test_before: int,
    test_after: int,
    new_decisions: int,
    recommendation: str,
    verbose: bool,
    project_root: Path,
) -> None:
    """Render output using rich if available, else plain text."""
    try:
        from rich.console import Console
        from rich.rule import Rule
        console = Console()
        use_rich = True
    except ImportError:
        use_rich = False
        console = None

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    has_issues = bool(oos_violations or rejected_findings or (test_before > 0 and test_after < test_before))

    def _out(line: str, style: str = "") -> None:
        if use_rich:
            if style:
                console.print(f"[{style}]{line}[/]")
            else:
                console.print(line)
        else:
            click.echo(line)

    _out("")
    if use_rich:
        console.print(Rule("⚡ OPTIMUSPRIME DIFF INTELLIGENCE", style="cyan bold"))
    else:
        click.echo("⚡ OPTIMUSPRIME DIFF INTELLIGENCE")
        click.echo("━" * 47)

    _out(f"  📅 Comparing: {now} vs {baseline}")
    _out(f"  📊 {len(commits)} commits · {len(changed_files)} files changed")
    _out("")

    # Files changed
    _out("[bold cyan]FILES CHANGED:[/]" if use_rich else "FILES CHANGED:")
    if changed_files:
        oos_set = set(oos_violations)
        for f in changed_files[:15]:
            if f in oos_set:
                _out(f"  [yellow]⚠ {f:<40} (OUT OF SCOPE)[/]" if use_rich else f"  ⚠ {f}  (OUT OF SCOPE)")
            else:
                _out(f"  [green]✓ {f}[/]" if use_rich else f"  ✓ {f}")
    else:
        _out("  [dim](no changes detected)[/]" if use_rich else "  (no changes detected)")
    _out("")

    # Dependency changes
    _out("[bold cyan]DEPENDENCY CHANGES:[/]" if use_rich else "DEPENDENCY CHANGES:")
    if rejected_findings:
        for (fname, term, when) in rejected_findings:
            _out(f"  [yellow]⚠ '{term}' added to {fname}[/]" if use_rich else f"  ⚠ '{term}' added to {fname}")
            _out(f"    [dim]Rejected in: [{when}][/]" if use_rich else f"    Rejected: {when}")
    else:
        _out("  [green]✓ No rejected deps re-added[/]" if use_rich else "  ✓ No rejected deps re-added")
    _out("")

    # Test coverage
    _out("[bold cyan]TEST COVERAGE:[/]" if use_rich else "TEST COVERAGE:")
    if test_after > 0 or test_before > 0:
        if test_before > 0 and test_after < test_before:
            _out(
                f"  [yellow]⚠ Test count: {test_before} → {test_after} (dropped)[/]"
                if use_rich else
                f"  ⚠ Test count: {test_before} → {test_after} (dropped)"
            )
        elif test_after > test_before:
            _out(
                f"  [green]✓ Test count: {test_before} → {test_after} (grew — good)[/]"
                if use_rich else
                f"  ✓ Test count: {test_before} → {test_after} (grew — good)"
            )
        else:
            _out(f"  [dim]Test count: {test_after} (unchanged)[/]" if use_rich else f"  Test count: {test_after} (unchanged)")
    else:
        _out(f"  [dim]Test count: {test_after}[/]" if use_rich else f"  Test count: {test_after}")
    _out("")

    # New decisions
    _out("[bold cyan]NEW DECISIONS SINCE LAST SESSION:[/]" if use_rich else "NEW DECISIONS:")
    _out(f"  • {new_decisions} new decisions added")
    _out("")

    # Recommendation
    _out("[bold cyan]RECOMMENDATION:[/]" if use_rich else "RECOMMENDATION:")
    if not has_issues:
        _out("  [green]✓ No issues detected since {baseline}[/]".format(baseline=baseline) if use_rich
             else f"  ✓ No issues detected since {baseline}")
        _out("  [green]Clean state — ready to start session.[/]" if use_rich else "  Clean state — ready to start session.")
    else:
        _out(f"  {recommendation}")
    _out("")

    if use_rich:
        console.print(Rule(style="dim"))
    else:
        click.echo("━" * 47)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

@click.command("diff-intel")
@click.option("--since", default=None, help="Baseline date (YYYY-MM-DD). Default: last snapshot.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show full diff for flagged files.")
@click.pass_obj
def diff_intel(obj: dict, since: Optional[str], verbose: bool) -> None:
    """Between-session git diff intelligence.

    Reads git diff since last session snapshot and flags scope violations,
    rejected deps re-added, and test count drops.

    \b
    Examples:
      op diff-intel                       # since last snapshot
      op diff-intel --since 2026-06-27    # since specific date
      op diff-intel --verbose             # show diffs for flagged files
    """
    op_dir = get_op_dir(obj)
    project_root = op_dir.parent

    # ---- Step 1: Baseline -----------------------------------------------
    baseline = _get_baseline(op_dir, since)

    # ---- Step 2: Git analysis -------------------------------------------
    if not _is_git_repo(project_root):
        click.echo(f"\nNo git repository found at {project_root}.")
        click.echo("Git analysis skipped — run 'git init' to enable diff intelligence.")
        return

    commits = _get_commits(project_root, baseline)
    changed_files = _get_changed_files(project_root, baseline)

    # ---- Step 3: Scope violations ----------------------------------------
    out_of_scope = _load_out_of_scope(op_dir)
    oos_violations = _check_scope_violations(changed_files, out_of_scope)

    # ---- Step 4: Rejected dep check -------------------------------------
    rejected_terms = _load_rejected_terms(op_dir)
    rejected_findings = _check_rejected_deps(changed_files, project_root, rejected_terms)

    # ---- Step 5: Test count analysis ------------------------------------
    test_after = _count_tests(project_root)
    test_before = _get_baseline_test_count(project_root, baseline)

    # ---- Step 6 & 7: Intelligence summary --------------------------------
    new_decisions = _get_new_decision_count(op_dir, baseline)

    # Build recommendation
    issues: List[str] = []
    if oos_violations:
        issues.append(f"Review {len(oos_violations)} out-of-scope change(s)")
    if rejected_findings:
        issues.append(f"Remove {len(rejected_findings)} rejected dep(s)")
    if test_before > 0 and test_after < test_before:
        issues.append(f"Restore {test_before - test_after} missing test(s)")
    recommendation = "; ".join(issues) if issues else "No issues to address."

    # ---- Step 8: Render -----------------------------------------------
    in_scope = load_json_safe(op_dir / "contract.json").get(
        "in_scope", load_json_safe(op_dir / "contract.json").get("in_scope_files", [])
    )

    _render_diff_intel(
        baseline=baseline,
        commits=commits,
        changed_files=changed_files,
        in_scope=in_scope,
        oos_violations=oos_violations,
        rejected_findings=rejected_findings,
        test_before=test_before,
        test_after=test_after,
        new_decisions=new_decisions,
        recommendation=recommendation,
        verbose=verbose,
        project_root=project_root,
    )
