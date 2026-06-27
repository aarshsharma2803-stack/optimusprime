"""OptimusPrime MCP server.

Exposes .optimusprime/ protocol files as 6 queryable tools.
Any MCP-capable agent can call these tools to get full session state.

Run:
  python mcp/server.py           # stdio transport (default)
  python -m mcp.server.fastmcp   # alternative invocation

Communicates over stdio. Register in Claude Code via:
  claude mcp add optimusprime -- python /path/to/mcp/server.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add src/ to path so we can import optimusprime.utils.
# IMPORTANT: add src/ specifically, NOT the project root — the project root
# contains a mcp/ directory that would shadow the `mcp` PyPI package.
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from mcp.server.fastmcp import FastMCP
from optimusprime.utils import find_optimusprime_dir

# Load search.py by file path to avoid shadowing the `mcp` package with mcp/ dir.
def _load_search() -> Any:
    spec = importlib.util.spec_from_file_location("optimusprime_search", _HERE / "search.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod

_search_mod = _load_search()
DecisionSearchEngine = _search_mod.DecisionSearchEngine

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "optimusprime",
    instructions=(
        "OptimusPrime session state tools. Use get_contract() to check current scope, "
        "search_decisions() to query why decisions were made, get_snapshot() to restore "
        "context from the last session, get_attempts() to see what already failed."
    ),
)

_engine = DecisionSearchEngine()
_decisions_mtime: float = -1.0


def _op_dir() -> Optional[Path]:
    return find_optimusprime_dir()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _ensure_indexed(decisions_path: Path) -> None:
    global _decisions_mtime
    try:
        mtime = decisions_path.stat().st_mtime
    except Exception:
        mtime = -1.0
    if mtime != _decisions_mtime:
        _engine.index(decisions_path)
        _decisions_mtime = mtime


def _read_last_n_lines(path: Path, n: int, prefix_filter: str = "") -> List[str]:
    """Return last n lines from path, optionally filtered by prefix substring."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    if prefix_filter:
        lines = [l for l in lines if prefix_filter in l]
    return lines[-n:]


# ---------------------------------------------------------------------------
# Tool 1: get_contract
# ---------------------------------------------------------------------------

@mcp.tool()
def get_contract() -> Dict[str, Any]:
    """Get the current scope contract: goal, in-scope/out-of-scope files, budget, agent_id.

    Returns no_contract status if no session has been started yet.
    """
    op_dir = _op_dir()
    if op_dir is None:
        return {
            "status": "no_op_dir",
            "message": "No .optimusprime/ directory found. Run from inside a project using OptimusPrime.",
        }

    data = _load_json(op_dir / "contract.json")
    if not data:
        return {
            "status": "no_contract",
            "message": "No scope contract found. Start a Claude Code session to create one.",
        }

    return {
        "status": "ok",
        "goal": data.get("goal", ""),
        "in_scope_files": data.get("in_scope", []),
        "out_of_scope_files": data.get("out_of_scope", []),
        "complexity_budget": data.get("complexity_budget", ""),
        "agent_id": data.get("agent_id", "main"),
        "session_id": data.get("session_id", ""),
        "created_at": data.get("created_at", ""),
        "done_checklist": data.get("done_checklist", []),
    }


# ---------------------------------------------------------------------------
# Tool 2: search_decisions
# ---------------------------------------------------------------------------

@mcp.tool()
def search_decisions(query: str, top_k: int = 5) -> Dict[str, Any]:
    """Search decisions.md with TF-IDF. Use this to answer 'why did we choose X'.

    Args:
        query: Search terms (e.g. "why stdlib", "loop detection", "atomic write")
        top_k: Maximum results to return (default 5, max 20)
    """
    top_k = min(max(1, top_k), 20)
    op_dir = _op_dir()
    if op_dir is None:
        return {
            "status": "no_op_dir",
            "results": [],
            "message": "No .optimusprime/ directory found.",
        }

    decisions_path = op_dir / "decisions.md"
    if not decisions_path.is_file():
        return {
            "status": "no_decisions",
            "results": [],
            "message": "No decisions.md yet. Decisions are logged during Claude Code sessions.",
        }

    _ensure_indexed(decisions_path)
    results = _engine.search(query, top_k=top_k)

    return {
        "status": "ok",
        "query": query,
        "total_indexed": _engine.doc_count,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Tool 3: get_snapshot
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _parse_snapshot_md(text: str) -> Dict[str, str]:
    """Extract ## sections from session-snapshot.md."""
    sections: Dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()
    return sections


@mcp.tool()
def get_snapshot() -> Dict[str, Any]:
    """Get the current session snapshot: goal, changed files, decisions, TODOs, next action.

    Returns full snapshot content plus structured fields from resume.json.
    Use this at the start of a new session to restore context.
    """
    op_dir = _op_dir()
    if op_dir is None:
        return {
            "status": "no_op_dir",
            "message": "No .optimusprime/ directory found.",
        }

    snapshot_path = op_dir / "session-snapshot.md"
    resume_path = op_dir / "resume.json"

    if not snapshot_path.is_file() and not resume_path.is_file():
        return {
            "status": "no_snapshot",
            "message": "No snapshot yet. It's written when a Claude Code session ends (Stop/PreCompact).",
        }

    result: Dict[str, Any] = {"status": "ok"}

    # Raw markdown + parsed sections
    if snapshot_path.is_file():
        raw = snapshot_path.read_text(encoding="utf-8")
        result["raw_snapshot"] = raw
        sections = _parse_snapshot_md(raw)
        result["goal"] = sections.get("Goal", "")
        result["changed_files"] = sections.get("Changed Files", "")
        result["key_decisions"] = sections.get("Key Decisions", "")
        result["failed_attempts"] = sections.get("Failed Attempts", "")
        result["open_todos"] = sections.get("Open TODOs", "")
        result["next_action"] = sections.get("Next Action", "")

    # Structured data from resume.json (overrides where available)
    if resume_path.is_file():
        resume = _load_json(resume_path)
        if resume:
            result["captured_at"] = resume.get("captured_at", "")
            result["session_id"] = resume.get("session_id", "")
            if not result.get("goal"):
                result["goal"] = resume.get("goal", "")
            result["decision_count"] = resume.get("decision_count", 0)
            result["open_todo_count"] = resume.get("open_todo_count", 0)
            if not result.get("next_action"):
                result["next_action"] = resume.get("next_action", "")

    return result


# ---------------------------------------------------------------------------
# Tool 4: get_attempts
# ---------------------------------------------------------------------------

_ATTEMPT_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+FAILED[:\s]+(?P<body>.+)$"
)


def _parse_attempts(path: Path, last_n: int) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    parsed = []
    for line in lines:
        m = _ATTEMPT_LINE_RE.match(line.strip())
        if not m:
            continue
        body = m.group("body").strip()
        # Body format: "tool=X target=Y error=Z"
        tool_m = re.search(r"tool=(\S+)", body)
        target_m = re.search(r"target=(\S+)", body)
        error_m = re.search(r"error=(.+)$", body)
        parsed.append(
            {
                "timestamp": m.group("ts"),
                "tool": tool_m.group(1) if tool_m else "",
                "target": target_m.group(1) if target_m else "",
                "error": error_m.group(1).strip() if error_m else body,
                "raw": line.strip(),
            }
        )

    return parsed[-last_n:]


@mcp.tool()
def get_attempts(last_n: int = 10) -> Dict[str, Any]:
    """Get recent failed tool attempts. Prevents retrying what already failed.

    Args:
        last_n: Number of most recent failures to return (default 10)
    """
    last_n = min(max(1, last_n), 100)
    op_dir = _op_dir()
    if op_dir is None:
        return {
            "status": "no_op_dir",
            "attempts": [],
            "message": "No .optimusprime/ directory found.",
        }

    attempts_path = op_dir / "attempts.md"
    if not attempts_path.is_file():
        return {
            "status": "no_attempts",
            "attempts": [],
            "message": "No failed attempts logged this session.",
        }

    attempts = _parse_attempts(attempts_path, last_n)
    return {
        "status": "ok",
        "count": len(attempts),
        "attempts": attempts,
    }


# ---------------------------------------------------------------------------
# Tool 5: get_todos
# ---------------------------------------------------------------------------

_TODO_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+(?P<kind>TODO|FIXME|HACK|XXX)[:\s]+(?P<body>.+)$",
    re.IGNORECASE,
)
_DEFERRED_RE = re.compile(r"\[deferred", re.IGNORECASE)


def _parse_todos(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    todos = []
    for line in lines:
        m = _TODO_LINE_RE.match(line.strip())
        if not m:
            continue
        body = m.group("body").strip()
        todos.append(
            {
                "timestamp": m.group("ts"),
                "kind": m.group("kind").upper(),
                "body": body,
                "deferred": bool(_DEFERRED_RE.search(body)),
            }
        )
    return todos


@mcp.tool()
def get_todos() -> Dict[str, Any]:
    """Get open TODOs added during this session. Shows what needs resolution before Done."""
    op_dir = _op_dir()
    if op_dir is None:
        return {
            "status": "no_op_dir",
            "todos": [],
            "message": "No .optimusprime/ directory found.",
        }

    todos_path = op_dir / "todos.md"
    if not todos_path.is_file():
        return {
            "status": "no_todos",
            "todos": [],
            "message": "No TODOs tracked this session.",
        }

    all_todos = _parse_todos(todos_path)
    open_todos = [t for t in all_todos if not t["deferred"]]
    deferred = [t for t in all_todos if t["deferred"]]

    return {
        "status": "ok",
        "open_count": len(open_todos),
        "deferred_count": len(deferred),
        "todos": open_todos,
        "deferred": deferred,
    }


# ---------------------------------------------------------------------------
# Tool 6: get_cost
# ---------------------------------------------------------------------------

@mcp.tool()
def get_cost() -> Dict[str, Any]:
    """Get session cost and token usage. Returns all sessions plus running total."""
    op_dir = _op_dir()
    if op_dir is None:
        return {
            "status": "no_op_dir",
            "message": "No .optimusprime/ directory found.",
        }

    cost_path = op_dir / "cost-log.json"
    if not cost_path.is_file():
        return {
            "status": "no_cost_data",
            "message": "No cost data yet. Written by cost-awareness skill during sessions.",
            "sessions": [],
            "total": {},
        }

    data = _load_json(cost_path)
    sessions: List[Dict[str, Any]] = data.get("sessions", [])

    total_in = sum(
        s.get("estimated_input_tokens", s.get("input_tokens", 0)) for s in sessions
    )
    total_out = sum(
        s.get("estimated_output_tokens", s.get("output_tokens", 0)) for s in sessions
    )
    total_cost = sum(s.get("estimated_cost_usd", 0.0) for s in sessions)

    return {
        "status": "ok",
        "session_count": len(sessions),
        "sessions": sessions,
        "total": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "estimated_cost_usd": round(total_cost, 6),
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
