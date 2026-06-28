"""OptimusPrime MCP server.

Exposes .optimusprime/ protocol files as 9 queryable tools.
Any MCP-capable agent can call these tools to get full session state.

Run:
  python mcp/server.py           # stdio transport (default)
  python mcp/server.py --help    # show this help

Communicates over stdio using JSON-RPC 2.0 with Content-Length framing (MCP protocol).
No external packages required — works with Python 3.8+ stdlib.

Register in Claude Code via:
  claude mcp add optimusprime -- python /path/to/mcp/server.py

If the official mcp package (Python 3.10+ only) is available it is used automatically.
Otherwise falls back to a stdlib implementation.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from optimusprime.utils import find_optimusprime_dir

# Load search.py by file path to avoid shadowing the `mcp` package with mcp/ dir.
def _load_search() -> Any:
    spec = importlib.util.spec_from_file_location("optimusprime_search", _HERE / "search.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod

_search_mod = _load_search()
DecisionSearchEngine = _search_mod.DecisionSearchEngine

from optimusprime.intelligence import IntelligenceEngine

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    if prefix_filter:
        lines = [l for l in lines if prefix_filter in l]
    return lines[-n:]


# ---------------------------------------------------------------------------
# Tool implementations (shared between FastMCP and stdlib paths)
# ---------------------------------------------------------------------------

def _get_contract() -> Dict[str, Any]:
    op_dir = _op_dir()
    if op_dir is None:
        return {"status": "no_op_dir", "message": "No .optimusprime/ directory found."}
    data = _load_json(op_dir / "contract.json")
    if not data:
        return {"status": "no_contract", "message": "No scope contract found."}
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


def _search_decisions(query: str, top_k: int = 5) -> Dict[str, Any]:
    top_k = min(max(1, top_k), 20)
    op_dir = _op_dir()
    if op_dir is None:
        return {"status": "no_op_dir", "results": [], "message": "No .optimusprime/ directory found."}
    decisions_path = op_dir / "decisions.md"
    if not decisions_path.is_file():
        return {"status": "no_decisions", "results": [], "message": "No decisions.md yet."}
    _ensure_indexed(decisions_path)
    return {"status": "ok", "query": query, "total_indexed": _engine.doc_count, "results": _engine.search(query, top_k=top_k)}


_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _parse_snapshot_md(text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()
    return sections


def _get_snapshot() -> Dict[str, Any]:
    op_dir = _op_dir()
    if op_dir is None:
        return {"status": "no_op_dir", "message": "No .optimusprime/ directory found."}
    snapshot_path = op_dir / "session-snapshot.md"
    resume_path = op_dir / "resume.json"
    if not snapshot_path.is_file() and not resume_path.is_file():
        return {"status": "no_snapshot", "message": "No snapshot yet."}
    result: Dict[str, Any] = {"status": "ok"}
    if snapshot_path.is_file():
        raw = snapshot_path.read_text(encoding="utf-8")
        result["raw_snapshot"] = raw
        sections = _parse_snapshot_md(raw)
        result["goal"] = sections.get("Goal", "")
        result["changed_files"] = sections.get("Changed Files", "")
        result["key_decisions"] = sections.get("Key Decisions", "")
        result["next_action"] = sections.get("Next Action", "")
    if resume_path.is_file():
        resume = _load_json(resume_path)
        if resume:
            result["captured_at"] = resume.get("captured_at", "")
            result["session_id"] = resume.get("session_id", "")
            if not result.get("goal"):
                result["goal"] = resume.get("goal", "")
            result["decision_count"] = resume.get("decision_count", 0)
    return result


_ATTEMPT_LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+FAILED[:\s]+(?P<body>.+)$")


def _get_attempts(last_n: int = 10) -> Dict[str, Any]:
    last_n = min(max(1, last_n), 100)
    op_dir = _op_dir()
    if op_dir is None:
        return {"status": "no_op_dir", "attempts": []}
    attempts_path = op_dir / "attempts.md"
    if not attempts_path.is_file():
        return {"status": "no_attempts", "attempts": []}
    try:
        lines = attempts_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {"status": "error", "attempts": []}
    parsed = []
    for line in lines:
        m = _ATTEMPT_LINE_RE.match(line.strip())
        if not m:
            continue
        body = m.group("body").strip()
        tool_m = re.search(r"tool=(\S+)", body)
        target_m = re.search(r"target=(\S+)", body)
        error_m = re.search(r"error=(.+)$", body)
        parsed.append({
            "timestamp": m.group("ts"),
            "tool": tool_m.group(1) if tool_m else "",
            "target": target_m.group(1) if target_m else "",
            "error": error_m.group(1).strip() if error_m else body,
        })
    return {"status": "ok", "count": len(parsed[-last_n:]), "attempts": parsed[-last_n:]}


_TODO_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<tag>[^\]]+)\]\s+(?P<kind>TODO|FIXME|HACK|XXX)[:\s]+(?P<body>.+)$",
    re.IGNORECASE,
)


def _get_todos() -> Dict[str, Any]:
    op_dir = _op_dir()
    if op_dir is None:
        return {"status": "no_op_dir", "todos": []}
    todos_path = op_dir / "todos.md"
    if not todos_path.is_file():
        return {"status": "no_todos", "todos": []}
    todos = []
    for line in todos_path.read_text(encoding="utf-8").splitlines():
        m = _TODO_LINE_RE.match(line.strip())
        if m:
            body = m.group("body").strip()
            todos.append({"timestamp": m.group("ts"), "kind": m.group("kind").upper(), "body": body})
    return {"status": "ok", "open_count": len(todos), "todos": todos}


def _get_cost() -> Dict[str, Any]:
    op_dir = _op_dir()
    if op_dir is None:
        return {"status": "no_op_dir", "message": "No .optimusprime/ directory found."}
    cost_path = op_dir / "cost-log.json"
    if not cost_path.is_file():
        return {"status": "no_cost_data", "sessions": [], "total": {}}
    data = _load_json(cost_path)
    sessions: List[Dict[str, Any]] = data.get("sessions", [])
    total_cost = sum(s.get("estimated_cost_usd", 0.0) for s in sessions)
    return {
        "status": "ok",
        "session_count": len(sessions),
        "sessions": sessions,
        "total": {
            "input_tokens": sum(s.get("estimated_input_tokens", s.get("input_tokens", 0)) for s in sessions),
            "output_tokens": sum(s.get("estimated_output_tokens", s.get("output_tokens", 0)) for s in sessions),
            "estimated_cost_usd": round(total_cost, 6),
        },
    }


def _get_intelligence_engine() -> "IntelligenceEngine":
    op_dir = _op_dir()
    if op_dir is None:
        raise FileNotFoundError("No .optimusprime/ directory found")
    return IntelligenceEngine(op_dir)


def _reason_about(question: str) -> Dict[str, Any]:
    try:
        engine = _get_intelligence_engine()
    except FileNotFoundError as e:
        return {"status": "no_op_dir", "message": str(e)}
    return {"status": "ok", "question": question, "answer": engine.reason_about(question)}


def _get_contradictions(severity: str = "all") -> Dict[str, Any]:
    severity = severity.lower()
    if severity not in ("hard", "soft", "all"):
        return {"status": "error", "message": "severity must be 'hard', 'soft', or 'all'"}
    try:
        engine = _get_intelligence_engine()
    except FileNotFoundError as e:
        return {"status": "no_op_dir", "contradictions": [], "message": str(e)}
    recs = engine._decisions
    if not recs:
        return {"status": "no_decisions", "contradictions": []}
    found = []
    seen: set = set()
    for i, rec in enumerate(recs):
        for c in engine.detect_contradictions(rec, past_decisions=recs[:i]):
            if severity != "all" and c.severity != severity:
                continue
            key = (c.past.raw[:60], c.current.raw[:60])
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "severity": c.severity,
                "similarity_score": round(c.similarity_score, 4),
                "explanation": c.explanation,
                "past": {"timestamp": c.past.timestamp, "decided": c.past.decided},
                "current": {"timestamp": c.current.timestamp, "decided": c.current.decided},
            })
    return {"status": "ok", "total_decisions": len(recs), "contradiction_count": len(found), "contradictions": found}


def _get_patterns() -> Dict[str, Any]:
    try:
        engine = _get_intelligence_engine()
    except FileNotFoundError as e:
        return {"status": "no_op_dir", "patterns": [], "message": str(e)}
    recs = engine._decisions
    if not recs:
        return {"status": "no_decisions", "patterns": []}
    pattern_list = engine.find_patterns()
    return {
        "status": "ok",
        "total_decisions": len(recs),
        "pattern_count": len(pattern_list),
        "patterns": [
            {
                "topic": p.topic,
                "decision_count": p.decision_count,
                "rejected_count": p.rejected_count,
                "velocity": p.velocity,
                "unstable": p.unstable,
                "sample_decisions": [r.decided[:80] for r in p.decisions[:3]],
            }
            for p in pattern_list
        ],
    }


# Public aliases — keep the same names as before so existing tests work.
# These call the private implementations; the private funcs have no mcp SDK dep.
get_contract = _get_contract
search_decisions = _search_decisions
get_snapshot = _get_snapshot
get_attempts = _get_attempts
get_todos = _get_todos
get_cost = _get_cost
reason_about = _reason_about
get_contradictions = _get_contradictions
get_patterns = _get_patterns

# Tool registry for stdlib transport
_TOOLS = {
    "get_contract": {
        "description": "Get the current scope contract: goal, in-scope/out-of-scope files, budget, agent_id.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "fn": lambda args: _get_contract(),
    },
    "search_decisions": {
        "description": "Search decisions.md with TF-IDF. Use to answer 'why did we choose X'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
                "top_k": {"type": "integer", "description": "Max results (default 5)", "default": 5},
            },
            "required": ["query"],
        },
        "fn": lambda args: _search_decisions(args.get("query", ""), args.get("top_k", 5)),
    },
    "get_snapshot": {
        "description": "Get the session snapshot: goal, changed files, decisions, next action.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "fn": lambda args: _get_snapshot(),
    },
    "get_attempts": {
        "description": "Get recent failed tool attempts. Prevents retrying what already failed.",
        "inputSchema": {
            "type": "object",
            "properties": {"last_n": {"type": "integer", "default": 10}},
            "required": [],
        },
        "fn": lambda args: _get_attempts(args.get("last_n", 10)),
    },
    "get_todos": {
        "description": "Get open TODOs added this session.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "fn": lambda args: _get_todos(),
    },
    "get_cost": {
        "description": "Get session cost and token usage.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "fn": lambda args: _get_cost(),
    },
    "reason_about": {
        "description": "Answer a question about the project by reasoning over decisions.md.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        "fn": lambda args: _reason_about(args.get("question", "")),
    },
    "get_contradictions": {
        "description": "Scan decisions.md for contradictions.",
        "inputSchema": {
            "type": "object",
            "properties": {"severity": {"type": "string", "enum": ["hard", "soft", "all"], "default": "all"}},
            "required": [],
        },
        "fn": lambda args: _get_contradictions(args.get("severity", "all")),
    },
    "get_patterns": {
        "description": "Analyze decision patterns clustered by topic.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "fn": lambda args: _get_patterns(),
    },
}


# ---------------------------------------------------------------------------
# stdlib stdio transport (Python 3.8+ compatible)
# ---------------------------------------------------------------------------

def _read_message() -> Optional[Dict[str, Any]]:
    """Read one Content-Length-framed JSON-RPC message from stdin."""
    headers: Dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.rstrip(b"\r\n")
        if not line:
            break
        if b":" in line:
            key, _, val = line.partition(b":")
            headers[key.strip().decode()] = val.strip().decode()
    length = int(headers.get("Content-Length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(obj: Dict[str, Any]) -> None:
    """Write one Content-Length-framed JSON-RPC message to stdout."""
    body = json.dumps(obj).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode()
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def _rpc_result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _run_stdlib() -> None:
    """Minimal MCP stdio server — handles initialize, tools/list, tools/call."""
    while True:
        msg = _read_message()
        if msg is None:
            break
        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}

        if method == "initialize":
            _write_message(_rpc_result(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "optimusprime", "version": "0.1.0"},
            }))

        elif method == "notifications/initialized":
            pass  # notification, no response

        elif method == "tools/list":
            tools = [
                {
                    "name": name,
                    "description": info["description"],
                    "inputSchema": info["inputSchema"],
                }
                for name, info in _TOOLS.items()
            ]
            _write_message(_rpc_result(req_id, {"tools": tools}))

        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments") or {}
            if tool_name not in _TOOLS:
                _write_message(_rpc_error(req_id, -32601, f"Tool not found: {tool_name}"))
                continue
            try:
                result = _TOOLS[tool_name]["fn"](tool_args)
                _write_message(_rpc_result(req_id, {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                    "isError": False,
                }))
            except Exception as e:
                _write_message(_rpc_result(req_id, {
                    "content": [{"type": "text", "text": str(e)}],
                    "isError": True,
                }))

        elif req_id is not None:
            _write_message(_rpc_error(req_id, -32601, f"Method not found: {method}"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_HELP = """\
OptimusPrime MCP Server

Exposes 9 tools over JSON-RPC stdio transport (MCP protocol).

Tools:
  get_contract         current scope contract
  search_decisions     TF-IDF search over decisions.md
  get_snapshot         last session snapshot + resume.json
  get_attempts         recent failed tool attempts
  get_todos            open TODOs this session
  get_cost             token usage and cost data
  reason_about         structured analysis of a question
  get_contradictions   scan decisions.md for conflicts
  get_patterns         topic clusters + velocity metrics

Register with Claude Code:
  claude mcp add optimusprime -- python /path/to/mcp/server.py

Python 3.8+ compatible (no external packages required).
"""


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print(_HELP)
        sys.exit(0)

    # Try FastMCP if mcp package is available (Python 3.10+)
    try:
        from mcp.server.fastmcp import FastMCP as _FastMCP  # type: ignore[import]

        _fmcp = _FastMCP(
            "optimusprime",
            instructions="OptimusPrime session state tools.",
        )

        @_fmcp.tool()
        def get_contract() -> Dict[str, Any]:
            """Get the current scope contract."""
            return _get_contract()

        @_fmcp.tool()
        def search_decisions(query: str, top_k: int = 5) -> Dict[str, Any]:
            """Search decisions.md with TF-IDF."""
            return _search_decisions(query, top_k)

        @_fmcp.tool()
        def get_snapshot() -> Dict[str, Any]:
            """Get the session snapshot."""
            return _get_snapshot()

        @_fmcp.tool()
        def get_attempts(last_n: int = 10) -> Dict[str, Any]:
            """Get recent failed attempts."""
            return _get_attempts(last_n)

        @_fmcp.tool()
        def get_todos() -> Dict[str, Any]:
            """Get open TODOs."""
            return _get_todos()

        @_fmcp.tool()
        def get_cost() -> Dict[str, Any]:
            """Get session cost."""
            return _get_cost()

        @_fmcp.tool()
        def reason_about(question: str) -> Dict[str, Any]:
            """Answer a question using decisions.md."""
            return _reason_about(question)

        @_fmcp.tool()
        def get_contradictions(severity: str = "all") -> Dict[str, Any]:
            """Scan for contradictions."""
            return _get_contradictions(severity)

        @_fmcp.tool()
        def get_patterns() -> Dict[str, Any]:
            """Analyze decision patterns."""
            return _get_patterns()

        _fmcp.run()

    except ImportError:
        # mcp package not available — use stdlib stdio transport
        _run_stdlib()
