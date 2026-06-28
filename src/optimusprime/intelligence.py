"""Core intelligence engine for OptimusPrime.

Provides contradiction detection, pattern clustering, context prediction,
and structured reasoning over decisions.md data.

Pure stdlib — no pip dependencies. Safe to import from hooks.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Stop words and framing verbs (excluded from key-term comparison)
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "it", "in", "of", "to", "and", "or", "for",
    "on", "at", "by", "with", "as", "be", "was", "are", "not", "we", "i",
    "via", "vs", "per", "its", "this", "that", "our", "all", "can", "has",
    "had", "have", "will", "from", "into", "over", "when", "than", "then",
    "so", "also", "more", "no", "up", "out", "if", "do", "use", "using",
})

_FRAMING_VERBS: frozenset[str] = frozenset({
    "chose", "choose", "selected", "select", "adopted", "adopt",
    "moved", "move", "added", "add", "kept", "keep", "replaced", "replace",
    "switched", "switch", "used", "decided", "chose", "prefer", "preferred",
    "built", "build", "written", "write", "implemented", "implement",
})

# ---------------------------------------------------------------------------
# Topic seed keywords for pattern clustering
# ---------------------------------------------------------------------------

_TOPIC_SEEDS: Dict[str, frozenset[str]] = {
    "auth": frozenset({
        "authentication", "jwt", "token", "session", "oauth",
        "login", "password", "credentials", "middleware", "bearer",
        "auth", "authorize", "authorization",
    }),
    "database": frozenset({
        "postgres", "postgresql", "sqlite", "mysql", "query", "schema",
        "migration", "orm", "redis", "cache", "index", "database",
        "db", "sql", "nosql", "table", "column",
    }),
    "api": frozenset({
        "endpoint", "route", "rest", "graphql", "http", "request",
        "response", "client", "server", "cors", "api", "webhook",
        "url", "path", "param",
    }),
    "testing": frozenset({
        "test", "mock", "fixture", "coverage", "pytest", "jest",
        "assertion", "stub", "integration", "unit", "tdd", "assert",
        "testing", "spec",
    }),
    "frontend": frozenset({
        "component", "react", "vue", "css", "tailwind", "render",
        "state", "props", "hook", "ui", "dom", "html", "frontend",
        "widget", "layout",
    }),
    "infrastructure": frozenset({
        "docker", "deploy", "ci", "github", "env", "config",
        "environment", "build", "pipeline", "kubernetes", "k8s",
        "infra", "cloud", "devops",
    }),
    "performance": frozenset({
        "latency", "cache", "optimize", "batch", "async", "concurrent",
        "timeout", "memory", "performance", "fast", "slow", "speed",
        "throughput", "benchmark",
    }),
    "security": frozenset({
        "encrypt", "hash", "sanitize", "validate", "xss", "csrf",
        "injection", "permission", "rbac", "security", "ssl", "tls",
        "secret", "vulnerable",
    }),
}

# ---------------------------------------------------------------------------
# Line format regexes
# ---------------------------------------------------------------------------

# Actual format: [ts] [agent:main] PREFIX: body text
_DECISION_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+(?P<prefix>\w+)[:\s]+(?P<body>.+)$"
)

# Structured body: DECIDED: X | REJECTED: Y,Z | REASON: W | ASSUMPTION: yes/no
_STRUCTURED_BODY_RE = re.compile(
    r"DECIDED:\s*(?P<decided>[^|]+?)"
    r"(?:\s*\|\s*REJECTED:\s*(?P<rejected>[^|]*))??"
    r"(?:\s*\|\s*REASON:\s*(?P<reason>[^|]*))??"
    r"(?:\s*\|\s*ASSUMPTION:\s*(?P<assumption>yes|no))?"
    r"\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DecisionRecord:
    timestamp: str
    decided: str          # main choice text (before "—" or from DECIDED: field)
    rejected: List[str]   # rejected alternatives (from REJECTED: field or empty list)
    reason: str           # why this was chosen (after "—" or from REASON: field)
    assumption: bool      # True if ASSUMPTION: yes
    raw: str              # original line
    session_date: str     # YYYY-MM-DD extracted from timestamp


@dataclass
class ContradictionResult:
    past: DecisionRecord
    current: DecisionRecord
    severity: str         # "hard" | "soft"
    similarity_score: float
    explanation: str


@dataclass
class PatternResult:
    topic: str
    decision_count: int
    rejected_count: int
    velocity: float       # decisions per session in this topic
    unstable: bool        # velocity > 3.0 or has contradictions
    decisions: List[DecisionRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# IntelligenceEngine
# ---------------------------------------------------------------------------


class IntelligenceEngine:
    """Core reasoning engine over OptimusPrime decision history."""

    DEFAULT_SIMILARITY_THRESHOLD = 0.75

    def __init__(self, optimusprime_dir: Path) -> None:
        self._op_dir = Path(optimusprime_dir)
        self._decisions_path = self._op_dir / "decisions.md"
        self._decisions: List[DecisionRecord] = []
        self._tfidf: Dict[str, Any] = {"idf": {}, "doc_vectors": [], "N": 0}
        self._patterns: Dict[str, Any] = {}
        self._topic_index: Dict[str, Any] = {}
        self._decisions_mtime: float = -1.0
        self._similarity_threshold = self.DEFAULT_SIMILARITY_THRESHOLD
        self._reload_if_stale()

    # ------------------------------------------------------------------
    # Public parsing
    # ------------------------------------------------------------------

    def parse_decisions(self, path: Path) -> List[DecisionRecord]:
        """Parse decisions.md into structured records.

        Handles both the actual OptimusPrime format:
            [ts] [agent:main] DECISION: body text — reason
        and the structured format:
            [ts] [tag] DECISION: DECIDED: X | REJECTED: Y | REASON: Z | ASSUMPTION: no
        """
        if not path.is_file():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []

        records: List[DecisionRecord] = []
        for line in lines:
            rec = self._parse_line(line)
            if rec is not None:
                records.append(rec)
        return records

    # ------------------------------------------------------------------
    # Contradiction detection
    # ------------------------------------------------------------------

    def detect_contradictions(
        self,
        new_decision: DecisionRecord,
        past_decisions: Optional[List[DecisionRecord]] = None,
    ) -> List[ContradictionResult]:
        """Detect contradictions between new_decision and past decisions.

        Hard: new.decided appears in past.rejected OR past.decided in new.rejected.
        Soft: TF-IDF similarity > threshold AND decided key-terms don't overlap.
        Returns list sorted by severity (hard first), then similarity_score desc.
        """
        past = past_decisions if past_decisions is not None else self._decisions

        if not past:
            return []

        results: List[ContradictionResult] = []

        new_decided_terms = self._key_terms(new_decision.decided)
        new_rejected_set = set()
        for r in new_decision.rejected:
            new_rejected_set |= self._key_terms(r)

        # Build TF-IDF vector for the new decision
        new_text = f"{new_decision.decided} {new_decision.reason}"
        new_vec = self._vectorize_text(new_text)

        for past_dec in past:
            if past_dec.raw == new_decision.raw:
                continue  # skip self

            past_decided_terms = self._key_terms(past_dec.decided)
            past_rejected_set = set()
            for r in past_dec.rejected:
                past_rejected_set |= self._key_terms(r)

            # ── Hard contradiction ─────────────────────────────────────────
            hard = False
            if past_rejected_set and (new_decided_terms & past_rejected_set):
                hard = True
            if new_rejected_set and (past_decided_terms & new_rejected_set):
                hard = True

            if hard:
                past_vec = self._get_doc_vector(past_dec)
                sim = self._cosine_similarity(new_vec, past_vec) if past_vec else 1.0
                results.append(ContradictionResult(
                    past=past_dec,
                    current=new_decision,
                    severity="hard",
                    similarity_score=min(1.0, max(0.0, sim)),
                    explanation=(
                        f"'{_trunc(new_decision.decided, 40)}' directly conflicts with "
                        f"past decision '{_trunc(past_dec.decided, 40)}'"
                    ),
                ))
                continue

            # ── Soft contradiction ─────────────────────────────────────────
            # Primary signal: high TF-IDF similarity (same vocabulary = same topic).
            # Secondary signal: same non-general topic bucket — catches small-corpus
            # cases where unique-choice terms dominate TF-IDF vectors even when the
            # decisions are clearly on the same topic.
            past_vec = self._get_doc_vector(past_dec)
            sim = self._cosine_similarity(new_vec, past_vec) if past_vec else 0.0

            new_topic = self._assign_topic(new_decision)
            past_topic = self._assign_topic(past_dec)
            same_nongeneral_topic = new_topic == past_topic and new_topic != "general"

            # Topic-match path still requires minimum TF-IDF similarity to avoid
            # flagging completely unrelated decisions that happen to share a bucket.
            _MIN_TOPIC_SIM = 0.15
            if sim < self._similarity_threshold and (
                not same_nongeneral_topic or sim < _MIN_TOPIC_SIM
            ):
                continue

            # Find unique key-terms on each side (shared context words like "database",
            # "backend" are expected overlap — only unique terms signal different choices).
            new_key = new_decided_terms - _FRAMING_VERBS
            past_key = past_decided_terms - _FRAMING_VERBS
            new_unique = new_key - past_key
            past_unique = past_key - new_key

            if new_unique and past_unique:
                effective_sim = max(sim, 0.5 if same_nongeneral_topic else 0.0)
                results.append(ContradictionResult(
                    past=past_dec,
                    current=new_decision,
                    severity="soft",
                    similarity_score=min(1.0, effective_sim),
                    explanation=(
                        f"Similar topic ({new_topic}, score={effective_sim:.2f}) but different"
                        f" choices: '{_trunc(new_decision.decided, 30)}' vs"
                        f" '{_trunc(past_dec.decided, 30)}'"
                    ),
                ))

        results.sort(key=lambda r: (0 if r.severity == "hard" else 1, -r.similarity_score))
        return results

    # ------------------------------------------------------------------
    # Pattern finding
    # ------------------------------------------------------------------

    def find_patterns(
        self,
        decisions: Optional[List[DecisionRecord]] = None,
    ) -> List[PatternResult]:
        """Cluster decisions by topic and compute stability metrics."""
        recs = decisions if decisions is not None else self._decisions
        if not recs:
            return []

        # Assign each decision to a topic bucket
        by_topic: Dict[str, List[DecisionRecord]] = {}
        for rec in recs:
            topic = self._assign_topic(rec)
            by_topic.setdefault(topic, []).append(rec)

        results: List[PatternResult] = []
        for topic, topic_recs in by_topic.items():
            # Count explicit rejected alternatives
            rejected_count = sum(len(r.rejected) for r in topic_recs)

            # Velocity: decisions / distinct session dates within this topic
            session_dates = sorted({r.session_date for r in topic_recs if r.session_date})
            n_sessions = len(session_dates) or 1
            velocity = len(topic_recs) / n_sessions

            # Unstable: velocity > 3.0 in last 5 sessions
            last_5_dates = set(session_dates[-5:])
            recent_count = sum(1 for r in topic_recs if r.session_date in last_5_dates)
            recent_velocity = recent_count / min(len(last_5_dates), 5) if last_5_dates else 0.0
            unstable = recent_velocity > 3.0

            results.append(PatternResult(
                topic=topic,
                decision_count=len(topic_recs),
                rejected_count=rejected_count,
                velocity=round(velocity, 2),
                unstable=unstable,
                decisions=topic_recs,
            ))

        results.sort(key=lambda p: -p.decision_count)
        return results

    # ------------------------------------------------------------------
    # Topic clustering (writes to .optimusprime/)
    # ------------------------------------------------------------------

    def cluster_by_topic(self) -> Dict[str, List[DecisionRecord]]:
        """Group all decisions by topic. Writes topic_index.json to .optimusprime/."""
        by_topic: Dict[str, List[DecisionRecord]] = {}
        for rec in self._decisions:
            topic = self._assign_topic(rec)
            by_topic.setdefault(topic, []).append(rec)

        # Persist to topic_index.json
        try:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            index_data: Dict[str, Any] = {"updated_at": ts}
            for topic, recs in by_topic.items():
                index_data[topic] = [r.raw for r in recs]
            out_path = self._op_dir / "topic_index.json"
            import json, os, tempfile
            tmp_fd, tmp = tempfile.mkstemp(dir=self._op_dir, prefix=".tmp_topic_", suffix=".json")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=2)
            os.rename(tmp, out_path)
        except Exception:
            pass

        return by_topic

    # ------------------------------------------------------------------
    # Context prediction
    # ------------------------------------------------------------------

    def predict_context_needs(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Predict relevant decisions/failures given a tool call context.

        Extracts signals from tool_input, builds a query, and returns
        top_k scored results sorted by relevance.
        """
        if not self._decisions:
            return []

        # Extract signals
        signals: List[str] = [tool_name]
        file_path: str = tool_input.get("file_path", "")
        if file_path:
            p = Path(file_path)
            signals.extend([p.name, p.suffix.lstrip("."), p.parent.name])

        for key in ("content", "old_string", "new_string", "command"):
            val = tool_input.get(key, "")
            if isinstance(val, str) and val:
                signals.extend(self._extract_functions(val)[:5])
                # Bash command file path tokens
                if key == "command":
                    signals.extend(re.findall(r'[\w./]+\.py', val)[:3])

        query = " ".join(s for s in signals if s)
        if not query.strip():
            return []

        query_vec = self._vectorize_text(query)
        if not query_vec:
            return []

        # Score each decision
        scored: List[Tuple[float, DecisionRecord]] = []
        for i, rec in enumerate(self._decisions):
            try:
                doc_vec = self._tfidf["doc_vectors"][i]
            except IndexError:
                continue
            if not doc_vec:
                continue
            base = self._cosine_similarity(query_vec, doc_vec)

            # Boost: file_path match in decision text
            if file_path and Path(file_path).name.lower() in rec.raw.lower():
                base += 0.15

            # Boost: function name in decision text
            for fn in self._extract_functions(query):
                if fn.lower() in rec.raw.lower():
                    base += 0.10
                    break

            scored.append((base, rec))

        # Include failure patterns
        failures = self._load_attempts()
        fail_results: List[Dict[str, Any]] = []
        for att in failures:
            body = att.get("body", "")
            att_vec = self._vectorize_text(body)
            sim = self._cosine_similarity(query_vec, att_vec)
            if sim > 0.2:
                fail_results.append({
                    "type": "failure",
                    "content": body,
                    "score": round(sim, 4),
                    "source": "attempts.md",
                })

        scored.sort(key=lambda x: -x[0])
        decision_results = [
            {
                "type": "decision",
                "content": rec.raw,
                "score": round(score, 4),
                "source": "decisions.md",
            }
            for score, rec in scored[:top_k]
            if score > 0
        ]

        combined = decision_results + fail_results
        combined.sort(key=lambda x: -x["score"])
        return combined[:top_k]

    # ------------------------------------------------------------------
    # Reasoning
    # ------------------------------------------------------------------

    def reason_about(self, question: str) -> str:
        """Answer a question about the project using structured decision analysis.

        Returns a structured multi-section response covering the current approach,
        why it was chosen, rejected alternatives, known failures, contradictions,
        and a confidence level.
        """
        if not self._decisions:
            return (
                "OPTIMUSPRIME REASONING\n"
                "─────────────────────\n"
                "No decisions logged yet. Start a Claude Code session to begin\n"
                "recording decisions to .optimusprime/decisions.md.\n"
                "\nConfidence: low (no data)"
            )

        # 1. Find relevant decisions
        q_vec = self._vectorize_text(question)
        scored: List[Tuple[float, DecisionRecord]] = []
        for i, rec in enumerate(self._decisions):
            try:
                doc_vec = self._tfidf["doc_vectors"][i]
            except IndexError:
                continue
            sim = self._cosine_similarity(q_vec, doc_vec)
            scored.append((sim, rec))
        scored.sort(key=lambda x: -x[0])
        top_recs = [r for s, r in scored[:10] if s > 0]

        if not top_recs:
            return (
                "OPTIMUSPRIME REASONING\n"
                "─────────────────────\n"
                f"No decisions found related to: '{question}'\n"
                "\nConfidence: low (no matching data)"
            )

        # 2. Topic patterns for context
        patterns = self.find_patterns(top_recs)
        top_topics = [p.topic for p in patterns[:3]]

        # 3. Contradictions across all decisions for relevant topic
        contradictions: List[ContradictionResult] = []
        if len(top_recs) >= 2:
            for rec in top_recs[:5]:
                cs = self.detect_contradictions(rec, top_recs)
                for c in cs:
                    if not any(
                        existing.past.raw == c.past.raw and existing.current.raw == c.current.raw
                        for existing in contradictions
                    ):
                        contradictions.append(c)

        # 4. Rejected alternatives (aggregate)
        rejected_seen: set[str] = set()
        all_rejected: List[str] = []
        for rec in top_recs:
            for r in rec.rejected:
                r_norm = r.strip().lower()
                if r_norm and r_norm not in rejected_seen:
                    rejected_seen.add(r_norm)
                    all_rejected.append(r.strip())

        # 5. Failures from attempts.md
        failures = self._load_attempts()

        # 6. Synthesize
        primary = top_recs[0]
        sessions = sorted({r.session_date for r in top_recs if r.session_date})
        n_sessions = len(sessions)

        # Confidence
        if contradictions:
            confidence = "low"
            conf_reason = f"{len(contradictions)} contradiction(s) detected"
        elif any(p.unstable for p in patterns if p.topic in top_topics):
            confidence = "medium"
            conf_reason = "high decision velocity in related topics"
        elif len(top_recs) >= 3 and not contradictions:
            confidence = "high"
            conf_reason = f"consistent across {n_sessions} session(s)"
        else:
            confidence = "medium"
            conf_reason = "limited decision history"

        lines: List[str] = [
            "OPTIMUSPRIME REASONING",
            "─────────────────────",
            f"Based on {len(top_recs)} decisions across {n_sessions} session(s):",
            "",
            f"Current approach: {primary.decided}",
            f"Why: {primary.reason or '(no reason recorded)'}",
            "",
        ]

        if all_rejected:
            lines.append("Rejected alternatives:")
            for r in all_rejected[:5]:
                lines.append(f"  • {r}")
            lines.append("")

        if failures:
            lines.append("Known failures:")
            for att in failures[:3]:
                body = att.get("body", "")
                lines.append(f"  • {body[:80]}")
            lines.append("")

        if contradictions:
            lines.append("Contradictions detected:")
            for c in contradictions[:3]:
                lines.append(
                    f"  [{c.severity.upper()}] {c.explanation}"
                )
            lines.append("")

        if top_topics:
            lines.append(f"Topics: {', '.join(top_topics)}")

        lines.append(f"\nConfidence: {confidence} ({conf_reason})")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _reload_if_stale(self) -> None:
        """Reload decisions and rebuild TF-IDF index if decisions.md has changed."""
        try:
            mtime = self._decisions_path.stat().st_mtime if self._decisions_path.exists() else -1.0
        except Exception:
            mtime = -1.0

        if mtime == self._decisions_mtime:
            return

        self._decisions = self.parse_decisions(self._decisions_path)
        self._decisions_mtime = mtime
        self._rebuild_tfidf()
        self._patterns = self._load_patterns()
        self._topic_index = self._load_topic_index()

    def _rebuild_tfidf(self) -> None:
        """Rebuild TF-IDF index from current decisions."""
        docs = [f"{d.decided} {d.reason} {' '.join(d.rejected)}" for d in self._decisions]
        self._tfidf = self._build_tfidf(docs)

    def _build_tfidf(self, docs: List[str]) -> Dict[str, Any]:
        """Build TF-IDF index from a list of document strings."""
        N = len(docs)
        if N == 0:
            return {"idf": {}, "doc_vectors": [], "N": 0}

        tokenized = [self._tokenize(doc) for doc in docs]

        # Document frequency
        df: Counter[str] = Counter()
        for tokens in tokenized:
            for term in set(tokens):
                df[term] += 1

        # IDF: log(N / df) — higher for rare terms
        idf = {term: math.log(N / freq) for term, freq in df.items() if freq > 0}

        # TF-IDF vectors (sparse dicts)
        doc_vectors: List[Dict[str, float]] = []
        for tokens in tokenized:
            if not tokens:
                doc_vectors.append({})
                continue
            tf: Counter[str] = Counter(tokens)
            total = len(tokens)
            vec = {
                term: (count / total) * idf.get(term, 0.0)
                for term, count in tf.items()
            }
            doc_vectors.append(vec)

        return {"idf": idf, "doc_vectors": doc_vectors, "N": N}

    def _cosine_similarity(self, vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
        """Compute cosine similarity between two sparse TF-IDF vectors."""
        if not vec1 or not vec2:
            return 0.0
        dot = sum(vec1.get(k, 0.0) * v for k, v in vec2.items())
        mag1 = math.sqrt(sum(v * v for v in vec1.values()))
        mag2 = math.sqrt(sum(v * v for v in vec2.values()))
        if mag1 == 0.0 or mag2 == 0.0:
            return 0.0
        return dot / (mag1 * mag2)

    def _vectorize_text(self, text: str) -> Dict[str, float]:
        """Build TF-IDF vector for arbitrary text using the current IDF table."""
        idf = self._tfidf.get("idf", {})
        tokens = self._tokenize(text)
        if not tokens or not idf:
            return {}
        tf: Counter[str] = Counter(tokens)
        total = len(tokens)
        return {
            term: (count / total) * idf[term]
            for term, count in tf.items()
            if term in idf
        }

    def _get_doc_vector(self, rec: DecisionRecord) -> Dict[str, float]:
        """Retrieve the cached TF-IDF vector for a DecisionRecord."""
        try:
            idx = next(
                i for i, d in enumerate(self._decisions) if d.raw == rec.raw
            )
            return self._tfidf["doc_vectors"][idx]
        except (StopIteration, IndexError):
            return {}

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize to lowercase words, removing stop words and short terms."""
        words = re.findall(r"[a-z0-9][a-z0-9_-]*", text.lower())
        return [w for w in words if len(w) > 2 and w not in _STOP_WORDS]

    def _key_terms(self, text: str) -> frozenset[str]:
        """Return significant terms (no stop words, no framing verbs)."""
        return frozenset(
            w for w in self._tokenize(text)
            if w not in _FRAMING_VERBS
        )

    def _extract_functions(self, content: str) -> List[str]:
        """Extract function/method names from code content using regex."""
        return re.findall(r"(?:def |function |class )([a-zA-Z_]\w+)", content)

    def _assign_topic(self, rec: DecisionRecord) -> str:
        """Assign a decision to the best-matching topic bucket."""
        text_tokens = set(self._tokenize(rec.raw))
        best_topic = "general"
        best_score = 0
        for topic, seeds in _TOPIC_SEEDS.items():
            score = len(text_tokens & seeds)
            if score > best_score:
                best_score = score
                best_topic = topic
        return best_topic

    def _load_patterns(self) -> Dict[str, Any]:
        """Load patterns.json from .optimusprime/ if it exists."""
        import json
        p = self._op_dir / "patterns.json"
        try:
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _load_topic_index(self) -> Dict[str, Any]:
        """Load topic_index.json from .optimusprime/ if it exists."""
        import json
        p = self._op_dir / "topic_index.json"
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _load_attempts(self) -> List[Dict[str, str]]:
        """Load failed attempts from attempts.md."""
        attempts_path = self._op_dir / "attempts.md"
        if not attempts_path.is_file():
            return []
        _RE = re.compile(
            r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+FAILED[:\s]+(?P<body>.+)$"
        )
        results: List[Dict[str, str]] = []
        try:
            for line in attempts_path.read_text(encoding="utf-8").splitlines():
                m = _RE.match(line.strip())
                if m:
                    results.append({
                        "timestamp": m.group("ts"),
                        "body": m.group("body").strip(),
                    })
        except Exception:
            pass
        return results

    def _parse_line(self, line: str) -> Optional[DecisionRecord]:
        """Parse one decisions.md line into a DecisionRecord."""
        m = _DECISION_LINE_RE.match(line.strip())
        if not m:
            return None

        ts = m.group("ts").strip()
        body = m.group("body").strip()

        # Extract session_date from timestamp (first 10 chars)
        session_date = ts[:10] if len(ts) >= 10 else ts

        # Try structured format first: DECIDED: X | REJECTED: Y | REASON: Z
        sm = _STRUCTURED_BODY_RE.match(body)
        if sm and sm.group("decided"):
            decided = sm.group("decided").strip()
            raw_rejected = sm.group("rejected") or ""
            rejected = [r.strip() for r in raw_rejected.split(",") if r.strip()]
            reason = (sm.group("reason") or "").strip()
            assumption = (sm.group("assumption") or "").lower() == "yes"
        else:
            # Actual format: "chose X — reason text"
            if " — " in body:
                parts = body.split(" — ", 1)
                decided = parts[0].strip()
                reason = parts[1].strip()
            elif " - " in body and not body.startswith("BLOCK"):
                parts = body.split(" - ", 1)
                decided = parts[0].strip()
                reason = parts[1].strip()
            else:
                decided = body
                reason = ""
            rejected = []
            assumption = False

        return DecisionRecord(
            timestamp=ts,
            decided=decided,
            rejected=rejected,
            reason=reason,
            assumption=assumption,
            raw=line.strip(),
            session_date=session_date,
        )


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


def get_engine(op_dir: Optional[Path] = None) -> IntelligenceEngine:
    """Create or return an IntelligenceEngine for op_dir.

    If op_dir is None, auto-detects from cwd.
    """
    if op_dir is None:
        from optimusprime.utils import find_optimusprime_dir
        op_dir = find_optimusprime_dir()
    if op_dir is None:
        raise FileNotFoundError("No .optimusprime/ directory found")
    return IntelligenceEngine(op_dir)
