"""TF-IDF search engine for decisions.md — no external dependencies.

Supports two decision body formats:
  1. Simple:  "chose hatchling as build backend — avoids extra config"
  2. Rich:    "DECIDED: X | REJECTED: Y | REASON: Z | ASSUMPTION: yes/no"

Both are indexed and returned with decided/rejected/reason/assumption fields.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+(?P<prefix>\w+)[:\s]+(?P<body>.+)$"
)
_DECIDED_RE = re.compile(r"DECIDED:\s*([^|]+)", re.IGNORECASE)
_REJECTED_RE = re.compile(r"REJECTED:\s*([^|]+)", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON:\s*([^|]+)", re.IGNORECASE)
_ASSUMPTION_RE = re.compile(r"ASSUMPTION:\s*(\S+)", re.IGNORECASE)

_STOP_WORDS = frozenset(
    "a an the in on at to of for is are was were be been being "
    "have has had do does did will would could should may might "
    "this that with from by as if but or and not".split()
)


def _tokenize(text: str) -> List[str]:
    raw = re.findall(r"[a-z0-9][a-z0-9_-]*", text.lower())
    return [t for t in raw if t not in _STOP_WORDS and len(t) > 1]


def _parse_body(body: str) -> Dict[str, str]:
    """Extract structured fields from a decision body, handling both formats."""
    dm = _DECIDED_RE.search(body)
    rm_rej = _REJECTED_RE.search(body)
    rm_rea = _REASON_RE.search(body)
    am = _ASSUMPTION_RE.search(body)

    decided = dm.group(1).strip() if dm else body
    rejected = rm_rej.group(1).strip() if rm_rej else ""
    reason = rm_rea.group(1).strip() if rm_rea else ""
    assumption = am.group(1).strip() if am else ""
    return {
        "decided": decided,
        "rejected": rejected,
        "reason": reason,
        "assumption": assumption,
    }


class DecisionSearchEngine:
    """TF-IDF search over decisions.md. Re-index when file changes."""

    def __init__(self) -> None:
        self._docs: List[Dict[str, Any]] = []
        # term -> [(doc_id, tf)]
        self._postings: Dict[str, List[tuple]] = {}
        self._idf: Dict[str, float] = {}

    def index(self, decisions_path: Path) -> None:
        """Parse decisions.md and build TF-IDF index."""
        self._docs = []
        self._postings = {}
        self._idf = {}

        if not decisions_path.is_file():
            return

        try:
            text = decisions_path.read_text(encoding="utf-8")
        except Exception:
            return

        raw: List[Dict[str, Any]] = []
        for line in text.splitlines():
            m = _LINE_RE.match(line.strip())
            if not m:
                continue
            body = m.group("body").strip()
            parsed = _parse_body(body)
            raw.append(
                {
                    "ts": m.group("ts"),
                    "tag": m.group("tag"),
                    "prefix": m.group("prefix"),
                    "body": body,
                    **parsed,
                }
            )

        if not raw:
            return

        # Build TF per document
        tf_list: List[Dict[str, float]] = []
        for doc_id, doc in enumerate(raw):
            tokens = _tokenize(doc["body"])
            if not tokens:
                tf_list.append({})
                continue
            freq: Dict[str, int] = {}
            for t in tokens:
                freq[t] = freq.get(t, 0) + 1
            n = len(tokens)
            tf: Dict[str, float] = {t: c / n for t, c in freq.items()}
            tf_list.append(tf)
            for t, tval in tf.items():
                self._postings.setdefault(t, []).append((doc_id, tval))

        # IDF with smoothing: log((N+1)/(df+1)) + 1
        n_docs = len(raw)
        for term, postings in self._postings.items():
            df = len(postings)
            self._idf[term] = math.log((n_docs + 1) / (df + 1)) + 1.0

        self._docs = raw

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return up to top_k results ranked by TF-IDF, with exact-match fallback."""
        if not self._docs or not query.strip():
            return []

        query_tokens = _tokenize(query)
        scores: Dict[int, float] = {}

        for token in query_tokens:
            if token not in self._postings:
                continue
            idf = self._idf.get(token, 1.0)
            for doc_id, tf in self._postings[token]:
                scores[doc_id] = scores.get(doc_id, 0.0) + tf * idf

        # Exact substring fallback when TF-IDF finds nothing
        if not scores:
            q_lower = query.lower()
            for doc_id, doc in enumerate(self._docs):
                if q_lower in doc["body"].lower():
                    scores[doc_id] = 1.0

        if not scores:
            return []

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        results = []
        for doc_id, score in ranked:
            doc = self._docs[doc_id]
            results.append(
                {
                    "timestamp": doc["ts"],
                    "prefix": doc["prefix"],
                    "decided": doc["decided"],
                    "rejected": doc["rejected"],
                    "reason": doc["reason"],
                    "assumption": doc["assumption"],
                    "body": doc["body"],
                    "relevance_score": round(score, 4),
                }
            )
        return results

    @property
    def doc_count(self) -> int:
        return len(self._docs)
