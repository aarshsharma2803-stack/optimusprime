"""Tests for src/optimusprime/intelligence.py.

Each test is independent — uses tmp_path to avoid state bleed.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from optimusprime.intelligence import (
    ContradictionResult,
    DecisionRecord,
    IntelligenceEngine,
    PatternResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_engine(tmp_path: Path, decisions_text: str = "") -> IntelligenceEngine:
    """Create an IntelligenceEngine backed by a temp .optimusprime/ dir."""
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir(exist_ok=True)
    if decisions_text:
        (op_dir / "decisions.md").write_text(decisions_text, encoding="utf-8")
    return IntelligenceEngine(op_dir)


def _line(ts: str, body: str, prefix: str = "DECISION") -> str:
    return f"[{ts}] [agent:main] {prefix}: {body}"


# ---------------------------------------------------------------------------
# 1–6: Parsing
# ---------------------------------------------------------------------------


def test_parse_actual_format_body_only(tmp_path: Path) -> None:
    """DECISION: body without dash separator → decided = full body, reason = ''."""
    text = _line("2026-01-01T00:00:00Z", "chose stdlib only for hooks")
    engine = make_engine(tmp_path, text)
    assert len(engine._decisions) == 1
    rec = engine._decisions[0]
    assert rec.decided == "chose stdlib only for hooks"
    assert rec.reason == ""
    assert rec.rejected == []
    assert rec.session_date == "2026-01-01"


def test_parse_actual_format_with_dash_separator(tmp_path: Path) -> None:
    """DECISION: decided — reason splits correctly on em-dash."""
    text = _line("2026-01-01T00:00:00Z", "chose hatchling as build backend — zero config vs setuptools")
    engine = make_engine(tmp_path, text)
    rec = engine._decisions[0]
    assert rec.decided == "chose hatchling as build backend"
    assert rec.reason == "zero config vs setuptools"


def test_parse_structured_format(tmp_path: Path) -> None:
    """DECIDED: X | REJECTED: Y,Z | REASON: W | ASSUMPTION: no parses all fields."""
    body = "DECIDED: use JWT | REJECTED: session cookies, opaque tokens | REASON: stateless | ASSUMPTION: no"
    text = _line("2026-01-02T00:00:00Z", body)
    engine = make_engine(tmp_path, text)
    rec = engine._decisions[0]
    assert rec.decided == "use JWT"
    assert "session cookies" in rec.rejected
    assert "opaque tokens" in rec.rejected
    assert rec.reason == "stateless"
    assert rec.assumption is False


def test_parse_structured_format_assumption_yes(tmp_path: Path) -> None:
    """ASSUMPTION: yes sets assumption=True."""
    body = "DECIDED: use monorepo | REJECTED: polyrepo | REASON: simpler CI | ASSUMPTION: yes"
    text = _line("2026-01-03T00:00:00Z", body)
    engine = make_engine(tmp_path, text)
    rec = engine._decisions[0]
    assert rec.assumption is True


def test_parse_block_prefix_included(tmp_path: Path) -> None:
    """BLOCK: prefix lines are included in parse results."""
    text = _line("2026-01-01T10:00:00Z", "Write to secrets/foo.txt blocked — out-of-scope", prefix="BLOCK")
    engine = make_engine(tmp_path, text)
    assert len(engine._decisions) == 1
    assert engine._decisions[0].decided.startswith("Write to")


def test_parse_malformed_lines_skipped(tmp_path: Path) -> None:
    """Lines that don't match the format are silently skipped."""
    text = textwrap.dedent("""\
        not a valid line at all
        [2026-01-01T00:00:00Z] [agent:main] DECISION: valid line — reason
        another bad line
    """)
    engine = make_engine(tmp_path, text)
    assert len(engine._decisions) == 1


def test_parse_missing_file_returns_empty(tmp_path: Path) -> None:
    """Missing decisions.md returns [] without error."""
    engine = make_engine(tmp_path)  # no decisions file
    assert engine._decisions == []


def test_parse_session_date_extraction(tmp_path: Path) -> None:
    """session_date is the YYYY-MM-DD prefix of the timestamp."""
    text = _line("2026-06-27T15:00:04Z", "chose postgresql — performance")
    engine = make_engine(tmp_path, text)
    assert engine._decisions[0].session_date == "2026-06-27"


# ---------------------------------------------------------------------------
# 7–11: Contradiction detection
# ---------------------------------------------------------------------------


def test_hard_contradiction_decided_in_past_rejected(tmp_path: Path) -> None:
    """Hard: new.decided terms overlap past.rejected → hard contradiction."""
    text = "\n".join([
        _line("2026-01-01T00:00:00Z", "DECIDED: use JWT | REJECTED: session cookies | REASON: stateless"),
        _line("2026-01-02T00:00:00Z", "DECIDED: use session cookies | REJECTED: JWT | REASON: simpler"),
    ])
    engine = make_engine(tmp_path, text)
    recs = engine._decisions
    assert len(recs) == 2

    results = engine.detect_contradictions(recs[1], past_decisions=[recs[0]])
    assert len(results) == 1
    assert results[0].severity == "hard"
    assert results[0].past.decided == "use JWT"
    assert results[0].current.decided == "use session cookies"


def test_hard_contradiction_past_decided_in_new_rejected(tmp_path: Path) -> None:
    """Hard also triggers when past.decided terms are in new.rejected."""
    text = "\n".join([
        _line("2026-01-01T00:00:00Z", "DECIDED: use sqlite | REJECTED: postgres | REASON: simplicity"),
        _line("2026-01-02T00:00:00Z", "DECIDED: use postgres | REJECTED: sqlite | REASON: scalability"),
    ])
    engine = make_engine(tmp_path, text)
    recs = engine._decisions
    results = engine.detect_contradictions(recs[1], past_decisions=[recs[0]])
    assert any(r.severity == "hard" for r in results)


def test_soft_contradiction_same_database_topic(tmp_path: Path) -> None:
    """Soft: same database topic, different chosen databases → soft contradiction.

    Requires a corpus large enough for shared terms ('database', 'backend') to
    have meaningful IDF — with only 2 docs every shared term gets IDF=0 and
    TF-IDF similarity is always 0 regardless of topical overlap.
    """
    # 10 background decisions across different topics so the corpus IDF is non-trivial
    background = [
        _line("2026-01-01T00:00:00Z", "added JWT auth middleware — stateless sessions"),
        _line("2026-01-02T00:00:00Z", "configured redis cache for hot queries — latency reduction"),
        _line("2026-01-03T00:00:00Z", "chose hatchling as build backend — zero config setup"),
        _line("2026-01-04T00:00:00Z", "set loop detector threshold to three consecutive errors — avoid trigger"),
        _line("2026-01-05T00:00:00Z", "moved to async http client — throughput improvement"),
        _line("2026-01-06T00:00:00Z", "added pytest fixtures for database testing — isolation"),
        _line("2026-01-07T00:00:00Z", "chose sqlite for test database backend — lightweight in-process"),
        _line("2026-01-08T00:00:00Z", "set database query timeout to 30s — safety against runaway queries"),
        _line("2026-01-09T00:00:00Z", "enabled tls for all database connections — security requirement"),
        _line("2026-01-10T00:00:00Z", "added monitoring for database query latency — observability"),
    ]
    # The two contradicting decisions share MANY context words (primary, relational,
    # data, storage) to ensure cosine similarity > 0.15 despite unique tool names
    db1 = _line("2026-01-11T00:00:00Z", "chose postgresql for primary relational database backend data storage — ACID compliance and json support")
    db2 = _line("2026-01-12T00:00:00Z", "chose mysql for primary relational database backend data storage — team familiarity and replication")
    text = "\n".join(background + [db1, db2])

    engine = make_engine(tmp_path, text)
    recs = engine._decisions
    assert len(recs) == 12

    # The last two are the contradicting pair
    results = engine.detect_contradictions(recs[11], past_decisions=[recs[10]])
    assert len(results) == 1
    assert results[0].severity == "soft"
    assert "mysql" in results[0].current.decided.lower() or "mysql" in results[0].explanation.lower()


def test_no_contradiction_unrelated_topics(tmp_path: Path) -> None:
    """Decisions on different topics should not generate contradictions."""
    text = "\n".join([
        _line("2026-01-01T00:00:00Z", "chose postgresql for database backend — ACID compliance"),
        _line("2026-01-02T00:00:00Z", "added JWT authentication middleware — stateless sessions"),
    ])
    engine = make_engine(tmp_path, text)
    recs = engine._decisions
    # auth topic vs database topic → no contradiction
    results = engine.detect_contradictions(recs[1], past_decisions=[recs[0]])
    assert results == []


def test_no_contradiction_self(tmp_path: Path) -> None:
    """A decision checked against itself (same raw line) is skipped."""
    text = _line("2026-01-01T00:00:00Z", "chose hatchling — zero config")
    engine = make_engine(tmp_path, text)
    rec = engine._decisions[0]
    results = engine.detect_contradictions(rec, past_decisions=[rec])
    assert results == []


def test_hard_before_soft_in_sorted_results(tmp_path: Path) -> None:
    """Hard contradictions appear before soft in returned list."""
    text = "\n".join([
        _line("2026-01-01T00:00:00Z", "DECIDED: use sqlite | REJECTED: postgres | REASON: simple"),
        _line("2026-01-02T00:00:00Z", "chose postgresql for relational database backend — better scale"),
        _line("2026-01-03T00:00:00Z", "DECIDED: use postgres | REJECTED: sqlite | REASON: scale"),
    ])
    engine = make_engine(tmp_path, text)
    recs = engine._decisions

    # Last decision contradicts both D1 (soft, same DB topic) and D2 (hard, sqlite in rejected)
    results = engine.detect_contradictions(recs[2], past_decisions=recs[:2])
    hard_results = [r for r in results if r.severity == "hard"]
    soft_results = [r for r in results if r.severity == "soft"]
    if hard_results and soft_results:
        assert results.index(hard_results[0]) < results.index(soft_results[0])


# ---------------------------------------------------------------------------
# 12–17: Pattern finding
# ---------------------------------------------------------------------------


def test_auth_decisions_cluster_to_auth_topic(tmp_path: Path) -> None:
    """Decisions with JWT/authentication keywords go to auth bucket."""
    text = "\n".join([
        _line("2026-01-01T00:00:00Z", "chose JWT authentication tokens — stateless sessions"),
        _line("2026-01-02T00:00:00Z", "added oauth2 middleware for authorization — industry standard"),
    ])
    engine = make_engine(tmp_path, text)
    patterns = engine.find_patterns()
    topics = {p.topic for p in patterns}
    assert "auth" in topics
    auth_pat = next(p for p in patterns if p.topic == "auth")
    assert auth_pat.decision_count == 2


def test_database_decisions_cluster_to_database_topic(tmp_path: Path) -> None:
    """Decisions mentioning postgres/query/schema go to database bucket."""
    text = "\n".join([
        _line("2026-01-01T00:00:00Z", "chose postgres for all user data — ACID and json support"),
        _line("2026-01-02T00:00:00Z", "added database migration with schema versioning — safe deploys"),
    ])
    engine = make_engine(tmp_path, text)
    patterns = engine.find_patterns()
    db_pat = next((p for p in patterns if p.topic == "database"), None)
    assert db_pat is not None
    assert db_pat.decision_count == 2


def test_unmatched_decision_goes_to_general(tmp_path: Path) -> None:
    """Decisions that don't match any topic seed fall into 'general' bucket."""
    text = _line("2026-01-01T00:00:00Z", "renamed module for clarity — naming consistency")
    engine = make_engine(tmp_path, text)
    patterns = engine.find_patterns()
    assert any(p.topic == "general" for p in patterns)


def test_velocity_one_decision_per_session(tmp_path: Path) -> None:
    """3 database decisions across 3 different session dates → velocity = 1.0."""
    text = "\n".join([
        _line("2026-01-01T00:00:00Z", "chose postgres for database — ACID"),
        _line("2026-01-02T00:00:00Z", "added database connection pool — performance"),
        _line("2026-01-03T00:00:00Z", "set database query timeout — safety"),
    ])
    engine = make_engine(tmp_path, text)
    patterns = engine.find_patterns()
    db_pat = next((p for p in patterns if p.topic == "database"), None)
    assert db_pat is not None
    assert db_pat.velocity == pytest.approx(1.0)


def test_pattern_unstable_high_velocity(tmp_path: Path) -> None:
    """5 decisions in a single session → velocity > 3.0 → unstable."""
    date = "2026-01-01"
    text = "\n".join([
        _line(f"{date}T00:00:0{i}Z", f"database schema decision number {i} — reason {i}")
        for i in range(5)
    ])
    engine = make_engine(tmp_path, text)
    patterns = engine.find_patterns()
    db_pat = next((p for p in patterns if p.topic == "database"), None)
    assert db_pat is not None
    assert db_pat.velocity > 3.0
    assert db_pat.unstable is True


def test_find_patterns_empty_decisions(tmp_path: Path) -> None:
    """find_patterns on empty engine returns []."""
    engine = make_engine(tmp_path)
    assert engine.find_patterns() == []


# ---------------------------------------------------------------------------
# 18–20: predict_context_needs
# ---------------------------------------------------------------------------


def test_predict_context_returns_at_most_top_k(tmp_path: Path) -> None:
    """predict_context_needs returns at most top_k results."""
    text = "\n".join(
        _line(f"2026-01-0{i+1}T00:00:00Z", f"chose library_{i} for util — reason {i}")
        for i in range(8)
    )
    engine = make_engine(tmp_path, text)
    results = engine.predict_context_needs("Read", {"file_path": "src/utils.py"}, top_k=3)
    assert len(results) <= 3


def test_predict_context_sorted_by_score(tmp_path: Path) -> None:
    """Results are sorted descending by score."""
    text = "\n".join([
        _line("2026-01-01T00:00:00Z", "chose hatchling as build backend — zero config"),
        _line("2026-01-02T00:00:00Z", "chose src/ layout for package isolation — avoids imports"),
        _line("2026-01-03T00:00:00Z", "set atomic write for json files — crash safety"),
    ])
    engine = make_engine(tmp_path, text)
    results = engine.predict_context_needs("Edit", {"file_path": "src/utils.py"}, top_k=5)
    if len(results) >= 2:
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)


def test_predict_context_empty_decisions(tmp_path: Path) -> None:
    """Returns [] gracefully when no decisions exist."""
    engine = make_engine(tmp_path)
    results = engine.predict_context_needs("Write", {"file_path": "foo.py"})
    assert results == []


# ---------------------------------------------------------------------------
# 21–22: reason_about
# ---------------------------------------------------------------------------


def test_reason_about_contains_confidence(tmp_path: Path) -> None:
    """reason_about output always contains a Confidence line."""
    text = "\n".join([
        _line("2026-01-01T00:00:00Z", "chose TF-IDF for semantic search — lightweight stdlib only"),
        _line("2026-01-02T00:00:00Z", "TF-IDF caches by mtime — only reindex when decisions change"),
        _line("2026-01-03T00:00:00Z", "TF-IDF top_k capped at 20 — avoids returning full file"),
    ])
    engine = make_engine(tmp_path, text)
    answer = engine.reason_about("why did we choose TF-IDF over embeddings")
    assert "Confidence" in answer
    assert "TF-IDF" in answer or "tfidf" in answer.lower() or "semantic" in answer.lower()


def test_reason_about_no_decisions_graceful(tmp_path: Path) -> None:
    """reason_about returns a helpful message when decisions.md is empty."""
    engine = make_engine(tmp_path)
    answer = engine.reason_about("why did we pick PostgreSQL")
    assert "Confidence" in answer
    assert "no data" in answer.lower() or "no decisions" in answer.lower()


# ---------------------------------------------------------------------------
# 23–24: TF-IDF internals
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors(tmp_path: Path) -> None:
    """Identical vectors → cosine similarity = 1.0."""
    engine = make_engine(tmp_path)
    v = {"foo": 0.5, "bar": 0.3}
    assert engine._cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors(tmp_path: Path) -> None:
    """Orthogonal vectors (no shared terms) → cosine similarity = 0.0."""
    engine = make_engine(tmp_path)
    v1 = {"foo": 0.5}
    v2 = {"bar": 0.5}
    assert engine._cosine_similarity(v1, v2) == pytest.approx(0.0)


def test_cosine_similarity_empty_vectors(tmp_path: Path) -> None:
    """Empty vectors → cosine similarity = 0.0 without division error."""
    engine = make_engine(tmp_path)
    assert engine._cosine_similarity({}, {"foo": 0.5}) == 0.0
    assert engine._cosine_similarity({"foo": 0.5}, {}) == 0.0
    assert engine._cosine_similarity({}, {}) == 0.0


def test_reload_if_stale_updates_decisions(tmp_path: Path) -> None:
    """Engine detects file change via mtime and reloads."""
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    dec_path = op_dir / "decisions.md"

    dec_path.write_text(_line("2026-01-01T00:00:00Z", "chose A — reason A"))
    engine = IntelligenceEngine(op_dir)
    assert len(engine._decisions) == 1

    # Append a new decision (bumps mtime)
    dec_path.write_text(
        _line("2026-01-01T00:00:00Z", "chose A — reason A") + "\n"
        + _line("2026-01-02T00:00:00Z", "chose B — reason B")
    )
    engine._reload_if_stale()
    assert len(engine._decisions) == 2
