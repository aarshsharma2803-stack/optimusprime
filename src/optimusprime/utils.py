"""Shared utilities used by every hook, the CLI, and the MCP server.

Hooks must stay stdlib-only (no pip deps). All functions here use only stdlib.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

PROTOCOL_DIR = ".optimusprime"
MAX_LINE_LENGTH = 120

_DEFAULT_OUT_OF_SCOPE = [
    ".env", "*.env", "node_modules/**", "secrets/**",
    "*.key", "*.pem", ".git/**", "__pycache__/**",
]

_DEFAULT_SKILLS = {
    "installed": {
        "caveman":       {"mode": "auto",       "version": "2.0.0", "trigger": "tokens>40000"},
        "superpowers":   {"mode": "contextual", "version": "1.0.0", "trigger": "complexity_budget:full"},
        "ui-ux-pro-max": {"mode": "contextual", "version": "1.0.0", "trigger": "frontend_files"},
        "ponytail":      {"mode": "contextual", "version": "1.0.0", "trigger": "complexity_budget:minimal"},
        "gstack":        {"mode": "contextual", "version": "1.0.0", "trigger": "goal:deploy,ship,pr"},
    }
}


# ---------------------------------------------------------------------------
# Directory discovery
# ---------------------------------------------------------------------------


def find_optimusprime_dir(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from start (default: cwd) looking for .optimusprime/.

    Returns the Path to the .optimusprime directory, or None if not found.
    Never raises; missing directory is a valid state (no contract = no enforcement).
    """
    try:
        current = Path(start or Path.cwd()).resolve()
        while True:
            candidate = current / PROTOCOL_DIR
            if candidate.is_dir():
                return candidate
            parent = current.parent
            if parent == current:
                return None
            current = parent
    except Exception:
        return None


def find_project_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from start looking for CLAUDE.md or .git/.

    Returns directory containing CLAUDE.md first, then .git, then None.
    Used by claude-md-generator skill.
    """
    try:
        current = Path(start or Path.cwd()).resolve()
        git_root: Optional[Path] = None
        while True:
            if (current / "CLAUDE.md").is_file():
                return current
            if (current / ".git").exists() and git_root is None:
                git_root = current
            parent = current.parent
            if parent == current:
                return git_root
            current = parent
    except Exception:
        return None


def scaffold_optimusprime_dir(op_dir: Path) -> None:
    """Create .optimusprime/ and every file a hook or skill needs to actually
    function, if missing. Idempotent — never overwrites an existing file.

    Without this, scope-guard and skill activation silently no-op on a fresh
    repo until a full session happens to populate contract.json/skills.json
    by hand. This makes '/optimusprime' (or any first prompt) self-sufficient.
    """
    try:
        op_dir.mkdir(parents=True, exist_ok=True)

        contract_path = op_dir / "contract.json"
        if not contract_path.is_file():
            write_json_safe(contract_path, {
                "version": "0.1.0",
                "goal": "",
                "in_scope": ["**"],
                "out_of_scope": list(_DEFAULT_OUT_OF_SCOPE),
                "complexity_budget": "moderate",
                "agent_id": "main",
                "session_id": secrets.token_hex(4),
                "created_at": utcnow_iso(),
            })

        skills_path = op_dir / "skills.json"
        if not skills_path.is_file():
            write_json_safe(skills_path, dict(_DEFAULT_SKILLS))

        cost_path = op_dir / "cost-log.json"
        if not cost_path.is_file():
            write_json_safe(cost_path, {"sessions": []})

        loop_path = op_dir / "loop-state.json"
        if not loop_path.is_file():
            write_json_safe(loop_path, {"consecutive_failures": []})

        for name in ("decisions.md", "attempts.md", "todos.md", ".gitkeep"):
            p = op_dir / name
            if not p.is_file():
                p.write_text("", encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------


def load_contract(optimusprime_dir: Path) -> Dict[str, Any]:
    """Load contract.json safely. Returns {} on missing file or bad JSON."""
    return _load_json_safe(optimusprime_dir / "contract.json")


def load_json(path: Path) -> Dict[str, Any]:
    """Load any JSON file safely. Returns {} on missing file or bad JSON."""
    return _load_json_safe(path)


def _load_json_safe(path: Path) -> Dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        text = path.read_text(encoding="utf-8")
        result = json.loads(text)
        if not isinstance(result, dict):
            return {}
        return result
    except Exception:
        return {}


def write_json_safe(path: Path, data: Dict[str, Any]) -> bool:
    """Atomically write data as JSON to path.

    Uses temp file + os.rename() to prevent corruption on crash.
    Returns True on success, False on any error (never raises).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=".tmp_" + path.name + "_",
            suffix=".json",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.rename(tmp_path, path)
            return True
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Append-only log files
# ---------------------------------------------------------------------------


def append_to_file(
    path: Path,
    prefix: str,
    body: str,
    agent_id: str = "main",
    session_id: Optional[str] = None,
) -> bool:
    """Append one timestamped line to path (decisions.md, attempts.md, todos.md).

    Line format: [<timestamp>] [agent:<agent_id>] <prefix> <body>
    If session_id given: [<timestamp>] [session:<session_id>] <prefix> <body>
    Line is truncated to MAX_LINE_LENGTH chars with trailing '…'.
    Returns True on success, False on error (never raises).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = _utcnow_iso()
        if session_id:
            tag = f"[session:{session_id}]"
        else:
            tag = f"[agent:{agent_id}]"
        line = f"[{timestamp}] {tag} {prefix} {body}"
        if len(line) > MAX_LINE_LENGTH:
            line = line[: MAX_LINE_LENGTH - 1] + "…"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except Exception:
        return False


def append_decision(
    optimusprime_dir: Path,
    body: str,
    agent_id: str = "main",
) -> bool:
    """Append a DECISION: line to decisions.md."""
    return append_to_file(
        optimusprime_dir / "decisions.md",
        prefix="DECISION:",
        body=body,
        agent_id=agent_id,
    )


def append_block(
    optimusprime_dir: Path,
    body: str,
    agent_id: str = "main",
) -> bool:
    """Append a BLOCK: line to decisions.md."""
    return append_to_file(
        optimusprime_dir / "decisions.md",
        prefix="BLOCK:",
        body=body,
        agent_id=agent_id,
    )


# ---------------------------------------------------------------------------
# Hook output helpers
# ---------------------------------------------------------------------------


def block_response(reason: str) -> str:
    """Return JSON block decision string for hook stdout. Exit code must be 2."""
    import sys
    print(f"OPTIMUSPRIME: {reason}", file=sys.stderr)
    return json.dumps({"decision": "block", "reason": f"OPTIMUSPRIME: {reason}"})


def approve_response() -> str:
    """Return JSON approve decision string for hook stdout. Exit code must be 0."""
    return json.dumps({"decision": "approve"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 string ending in Z."""
    try:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow_iso() -> str:
    """Public alias for timestamp generation."""
    return _utcnow_iso()


def truncate_line(line: str, max_len: int = MAX_LINE_LENGTH) -> str:
    """Truncate line to max_len, appending '…' if truncated."""
    if len(line) <= max_len:
        return line
    return line[: max_len - 1] + "…"


def append_event(
    optimusprime_dir: Path,
    event: str,
    tool: str = "",
    file: str = "",
    action: str = "",
) -> bool:
    """Append one JSON event line to events.jsonl. Keeps last 100 entries.

    Returns True on success, False on any error (never raises).
    """
    try:
        if optimusprime_dir is None or not optimusprime_dir.is_dir():
            return False
        entry = json.dumps({
            "ts": _utcnow_iso(),
            "event": event,
            "tool": tool,
            "file": str(file)[:120],
            "action": action,
        })
        log_path = optimusprime_dir / "events.jsonl"
        lines: list[str] = []
        if log_path.is_file():
            try:
                lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            except Exception:
                lines = []
        lines.append(entry)
        if len(lines) > 100:
            lines = lines[-100:]
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False
