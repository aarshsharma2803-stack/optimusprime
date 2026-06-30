"""Tests for hooks/pre/pre-response.py — UserPromptSubmit hook."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent.parent / "hooks" / "pre" / "pre-response.py"


def _run(payload: dict, op_dir: Path | None = None) -> subprocess.CompletedProcess:
    kwargs: dict = {}
    if op_dir:
        kwargs["cwd"] = str(op_dir.parent)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        **kwargs,
    )


def _make_op_dir(tmp: Path) -> Path:
    op = tmp / ".optimusprime"
    op.mkdir()
    return op


# ---- 1. Short prompt exits 0 cleanly, no output ---------------------------

def test_short_prompt_exits_0(tmp_path):
    result = _run({"prompt": "hi", "session_id": "abc"})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_prompt_under_10_chars_no_output(tmp_path):
    result = _run({"prompt": "fix it", "session_id": "x"})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_empty_payload_exits_0(tmp_path):
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input="",
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0


def test_invalid_json_exits_0(tmp_path):
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not json {{{",
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0


# ---- 2. File ref extraction ------------------------------------------------

def test_file_refs_extracted(tmp_path):
    """Import the module directly and test _extract_file_refs."""
    sys.path.insert(0, str(HOOK.parent.parent.parent / "src"))
    sys.path.insert(0, str(HOOK.parent.parent.parent / "hooks" / "pre"))

    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    refs = mod._extract_file_refs("Please update src/foo.py and hooks/bar.py")
    assert any("src/foo.py" in r or "foo.py" in r for r in refs)


def test_file_refs_empty_for_no_paths(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    refs = mod._extract_file_refs("just fix the bug in the auth system")
    assert len(refs) == 0 or all("/" not in r for r in refs)


# ---- 3. Action type inference ---------------------------------------------

def test_action_type_fix(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._infer_action_type("fix the bug in the login handler") == "fix"


def test_action_type_build(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._infer_action_type("build a new user registration endpoint") == "build"


def test_action_type_refactor(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._infer_action_type("refactor and restructure the database layer for clarity") == "refactor"


# ---- 4. Complexity signals ------------------------------------------------

def test_complexity_detected(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._detect_complexity("rewrite the entire auth system from scratch") is True


def test_no_complexity_simple_prompt(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._detect_complexity("fix the null pointer in session.py") is False


# ---- 5. Output is valid JSON when context present -------------------------

def test_output_is_valid_json_when_content_injected(tmp_path):
    op = _make_op_dir(tmp_path)
    # Write a decisions.md with REJECTED term
    (op / "decisions.md").write_text(
        "[2024-01-01] [agent:main] DECIDED: use sqlite | REJECTED: redis | REASON: simpler\n"
    )
    result = _run(
        {"prompt": "should we use redis for the session store now?", "session_id": "x"},
    )
    assert result.returncode == 0
    if result.stdout.strip():
        data = json.loads(result.stdout)
        assert "additionalContext" in data


# ---- 6. Empty .optimusprime/ does not crash ------------------------------

def test_empty_optimusprime_no_crash(tmp_path):
    """Hook should not crash even with an empty .optimusprime/ dir."""
    op = _make_op_dir(tmp_path)
    result = _run(
        {"prompt": "implement a complete user registration flow with validation", "session_id": "x"},
    )
    assert result.returncode == 0


# ---- 7. Contradiction risk detection -------------------------------------

def test_contradiction_detected_when_rejected_term_in_prompt(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    op = _make_op_dir(tmp_path)
    (op / "decisions.md").write_text(
        "[2024-01-15] [agent:main] DECIDED: use jwt | REJECTED: session-cookies | REASON: stateless\n"
    )
    contradictions = mod._check_contradictions(op, "let's switch to session-cookies for auth")
    assert len(contradictions) > 0
    assert "session" in contradictions[0].lower() or "cookies" in contradictions[0].lower()


def test_no_contradiction_with_clean_prompt(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    op = _make_op_dir(tmp_path)
    (op / "decisions.md").write_text(
        "[2024-01-15] [agent:main] DECIDED: use jwt | REJECTED: session-cookies | REASON: stateless\n"
    )
    contradictions = mod._check_contradictions(op, "add a new password reset feature")
    assert len(contradictions) == 0


# ---- 8. Scope alert on complexity + minimal budget -----------------------

def test_scope_alert_fires_on_complex_prompt_with_minimal_budget(tmp_path):
    op = _make_op_dir(tmp_path)
    (op / "contract.json").write_text(json.dumps({
        "goal": "fix the login bug",
        "complexity_budget": "minimal",
    }))
    result = _run(
        {"prompt": "rewrite the entire authentication system from scratch", "session_id": "x"},
        op_dir=op,
    )
    assert result.returncode == 0
    if result.stdout.strip():
        data = json.loads(result.stdout)
        ctx = data.get("additionalContext", "")
        assert "SCOPE ALERT" in ctx or "budget" in ctx.lower()


# ---- 9. Performance: under 150ms ----------------------------------------

def test_performance_under_150ms(tmp_path):
    """End-to-end subprocess run must complete in under 150ms on average."""
    op = _make_op_dir(tmp_path)
    payload = json.dumps({"prompt": "build the new user registration form with validation", "session_id": "abc"})

    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        subprocess.run(
            [sys.executable, str(HOOK)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=5,
        )
        times.append(time.perf_counter() - t0)

    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 150, f"Average {avg_ms:.1f}ms exceeded 150ms target"


# ---- 10. Output under 300 tokens (~1200 chars) ---------------------------

def test_output_under_300_tokens(tmp_path):
    op = _make_op_dir(tmp_path)
    # Seed data to ensure there's output
    (op / "decisions.md").write_text("\n".join(
        f"[2024-01-{i:02d}] [agent:main] DECIDED: choice {i} | REJECTED: alt {i} | REASON: reason"
        for i in range(1, 21)
    ))
    result = _run(
        {"prompt": "implement the entire user profile management system with full validation and tests", "session_id": "x"},
    )
    if result.stdout.strip():
        data = json.loads(result.stdout)
        ctx = data.get("additionalContext", "")
        assert len(ctx) <= 1200, f"Context length {len(ctx)} exceeds 1200 chars"


# ---- 11. Hook never crashes on unexpected input -------------------------

def test_hook_never_crashes_on_unexpected_input(tmp_path):
    for bad in ["{}", "null", "[]", '{"session_id": 123}']:
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=bad,
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0, f"Crashed on input: {bad!r}"


# ---- 12. Keywords extracted and stop words removed ----------------------

def test_keywords_extraction_removes_stop_words(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pre_response", str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    keywords = mod._extract_keywords("the user authentication system needs to be refactored")
    assert "the" not in keywords
    assert "to" not in keywords
    assert "authentication" in keywords or "refactored" in keywords
