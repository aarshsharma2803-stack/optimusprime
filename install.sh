#!/usr/bin/env bash
# OptimusPrime installer — macOS / Linux
# Idempotent: safe to run multiple times.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLOBAL_DIR="$HOME/.optimusprime"
VENV_DIR="$GLOBAL_DIR/venv"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[op]${NC} $*"; }
warn()    { echo -e "${YELLOW}[op]${NC} $*"; }
error()   { echo -e "${RED}[op] ERROR:${NC} $*" >&2; exit 1; }

# ── 1. python3 >= 3.8 ────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    error "python3 not found. Install Python 3.8+ from https://python.org and re-run."
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYMAJ=$(python3 -c "import sys; print(sys.version_info.major)")
PYMIN=$(python3 -c "import sys; print(sys.version_info.minor)")
if [[ "$PYMAJ" -lt 3 ]] || [[ "$PYMAJ" -eq 3 && "$PYMIN" -lt 8 ]]; then
    error "Python $PYVER found, but OptimusPrime requires Python 3.8+."
fi
info "Python $PYVER ✓"

# ── 2. venv at ~/.optimusprime/venv/ ─────────────────────────────────────────
mkdir -p "$GLOBAL_DIR"
if [[ ! -f "$VENV_DIR/bin/python" ]]; then
    info "Creating venv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
else
    info "venv exists, skipping creation"
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# ── 3. pip install -e . into venv ────────────────────────────────────────────
info "Installing OptimusPrime into venv ..."
"$VENV_PIP" install --quiet --upgrade pip
# mcp>=1.0 requires Python 3.10+; install it only when supported
if [[ "$PYMAJ" -gt 3 ]] || [[ "$PYMAJ" -eq 3 && "$PYMIN" -ge 10 ]]; then
    "$VENV_PIP" install --quiet -e "$REPO_DIR[mcp]"
    info "Package installed with MCP server support ✓"
else
    "$VENV_PIP" install --quiet -e "$REPO_DIR"
    warn "Python $PYVER: MCP server skipped (requires 3.10+). Core hooks + CLI installed."
fi

# ── 4. copy skills ───────────────────────────────────────────────────────────
info "Copying skills to $GLOBAL_DIR/skills/ ..."
mkdir -p "$GLOBAL_DIR/skills"
cp -r "$REPO_DIR/skills/." "$GLOBAL_DIR/skills/"
info "Skills copied ✓"

# ── 5. create project .optimusprime/ ─────────────────────────────────────────
PROJECT_OP_DIR="$(pwd)/.optimusprime"
if [[ ! -d "$PROJECT_OP_DIR" ]]; then
    mkdir -p "$PROJECT_OP_DIR"
    touch "$PROJECT_OP_DIR/.gitkeep"
    info "Created $PROJECT_OP_DIR"
else
    info "Project .optimusprime/ already exists"
fi

# ── 6. register hooks + MCP in ~/.claude/settings.json ───────────────────────
mkdir -p "$(dirname "$CLAUDE_SETTINGS")"

info "Merging hooks and MCP server into $CLAUDE_SETTINGS ..."

"$VENV_PY" - <<PYEOF
import json, sys
from pathlib import Path

settings_path = Path("$CLAUDE_SETTINGS")
repo_dir      = Path("$REPO_DIR")

# Load existing settings (or start fresh)
if settings_path.exists():
    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        settings = {}
else:
    settings = {}

hooks_cfg = settings.setdefault("hooks", {})

# ── PreToolUse hooks ──────────────────────────────────────────────────────────
pre_hooks = [
    str(repo_dir / "hooks" / "pre" / "scope-guard.py"),
    str(repo_dir / "hooks" / "pre" / "dependency-analyzer.py"),
    str(repo_dir / "hooks" / "pre" / "loop-detector.py"),
    str(repo_dir / "hooks" / "pre" / "breaking-change-detector.py"),
]
pre_list = hooks_cfg.setdefault("PreToolUse", [])

# Each hook entry: {"type": "command", "command": "python3 /path/to/hook.py"}
for hook_path in pre_hooks:
    cmd = f"python3 {hook_path}"
    entry = {"type": "command", "command": cmd}
    if not any(h.get("command") == cmd for h in pre_list):
        pre_list.append(entry)

# ── PostToolUse hooks ─────────────────────────────────────────────────────────
post_hooks = [
    str(repo_dir / "hooks" / "post" / "output-compressor.py"),
    str(repo_dir / "hooks" / "post" / "attempt-logger.py"),
    str(repo_dir / "hooks" / "post" / "todo-scanner.py"),
]
post_list = hooks_cfg.setdefault("PostToolUse", [])
for hook_path in post_hooks:
    cmd = f"python3 {hook_path}"
    entry = {"type": "command", "command": cmd}
    if not any(h.get("command") == cmd for h in post_list):
        post_list.append(entry)

# ── Stop hooks ────────────────────────────────────────────────────────────────
stop_hooks = [
    str(repo_dir / "hooks" / "post" / "done-checker.py"),
    str(repo_dir / "hooks" / "post" / "session-logger.py"),
]
stop_list = hooks_cfg.setdefault("Stop", [])
for hook_path in stop_hooks:
    cmd = f"python3 {hook_path}"
    entry = {"type": "command", "command": cmd}
    if not any(h.get("command") == cmd for h in stop_list):
        stop_list.append(entry)

# ── MCP server ────────────────────────────────────────────────────────────────
mcp_servers = settings.setdefault("mcpServers", {})
if "optimusprime" not in mcp_servers:
    mcp_servers["optimusprime"] = {
        "command": "python3",
        "args": [str(repo_dir / "mcp" / "server.py")],
        "env": {}
    }

# Write atomically
import os, tempfile
tmp = settings_path.parent / f".settings.json.tmp.{os.getpid()}"
tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
tmp.replace(settings_path)
print("settings.json updated")
PYEOF

info "Hooks and MCP registered ✓"

# ── 7. summary ───────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${GREEN} OptimusPrime installed successfully!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo ""
echo "  Global dir:  $GLOBAL_DIR"
echo "  Project dir: $PROJECT_OP_DIR"
echo "  Settings:    $CLAUDE_SETTINGS"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code (hooks take effect on next launch)"
echo "  2. Start a new session — OptimusPrime activates automatically"
echo "  3. Run: op snapshot    — to see current session state"
echo "  4. Run: op decision list --last 10    — to review decisions"
echo ""
echo "  Install community skills:"
echo "    op skills install superpowers"
echo "    op skills install caveman"
echo "    op skills install --all"
echo ""
