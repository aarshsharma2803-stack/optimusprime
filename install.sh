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

def _merge_hooks(hook_list, hooks_with_timeouts):
    """Idempotent merge: add missing hooks, skip already-registered ones."""
    existing_cmds = {h.get("command") for h in hook_list if isinstance(h, dict)}
    for path, timeout in hooks_with_timeouts:
        cmd = f"python3 {path}"
        if cmd not in existing_cmds:
            entry = {"type": "command", "command": cmd, "timeout": timeout}
            hook_list.append(entry)
            existing_cmds.add(cmd)

# ── UserPromptSubmit hooks ────────────────────────────────────────────────────
user_submit_hooks = [
    (str(repo_dir / "hooks" / "pre" / "pre-response.py"), 8),
]
user_submit_list = hooks_cfg.setdefault("UserPromptSubmit", [])
_merge_hooks(user_submit_list, user_submit_hooks)

# ── PreToolUse hooks ──────────────────────────────────────────────────────────
# Order: predictive-context → pre-write-injector → scope-guard → loop-detector → ...
pre_hooks = [
    (str(repo_dir / "hooks" / "pre" / "predictive-context.py"), 8),
    (str(repo_dir / "hooks" / "pre" / "pre-write-injector.py"), 8),
    (str(repo_dir / "hooks" / "pre" / "scope-guard.py"), 10),
    (str(repo_dir / "hooks" / "pre" / "loop-detector.py"), 10),
    (str(repo_dir / "hooks" / "pre" / "dependency-analyzer.py"), 10),
    (str(repo_dir / "hooks" / "pre" / "breaking-change-detector.py"), 10),
]
pre_list = hooks_cfg.setdefault("PreToolUse", [])
_merge_hooks(pre_list, pre_hooks)

# ── PostToolUse hooks ─────────────────────────────────────────────────────────
# Only per-tool-call hooks: compressor + attempt logger + post-write analyzer.
# todo-scanner belongs in Stop (session-end diff), not here.
post_hooks = [
    (str(repo_dir / "hooks" / "post" / "output-compressor.py"), 10),
    (str(repo_dir / "hooks" / "post" / "attempt-logger.py"), 10),
    (str(repo_dir / "hooks" / "post" / "post-write-analyzer.py"), 10),
    (str(repo_dir / "hooks" / "post" / "task-state-updater.py"), 10),
]
post_list = hooks_cfg.setdefault("PostToolUse", [])
_merge_hooks(post_list, post_hooks)

# ── Stop hooks ────────────────────────────────────────────────────────────────
# todo-scanner diffs session start vs end; must run at Stop, not PostToolUse.
# learner-hook runs AFTER session-logger (resume.json must exist first).
stop_hooks = [
    (str(repo_dir / "hooks" / "post" / "todo-scanner.py"), 15),
    (str(repo_dir / "hooks" / "post" / "done-checker.py"), 15),
    (str(repo_dir / "hooks" / "post" / "session-logger.py"), 15),
    (str(repo_dir / "hooks" / "post" / "learner-hook.py"), 20),
]
stop_list = hooks_cfg.setdefault("Stop", [])
_merge_hooks(stop_list, stop_hooks)

# ── SubagentStop hooks ────────────────────────────────────────────────────────
subagent_hooks = [
    (str(repo_dir / "hooks" / "post" / "todo-scanner.py"), 15),
    (str(repo_dir / "hooks" / "post" / "session-logger.py"), 15),
    (str(repo_dir / "hooks" / "post" / "learner-hook.py"), 20),
]
subagent_list = hooks_cfg.setdefault("SubagentStop", [])
_merge_hooks(subagent_list, subagent_hooks)

# ── PreCompact hook ───────────────────────────────────────────────────────────
precompact_hooks = [
    (str(repo_dir / "hooks" / "post" / "session-logger.py"), 15),
]
precompact_list = hooks_cfg.setdefault("PreCompact", [])
_merge_hooks(precompact_list, precompact_hooks)

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

# ── PATH setup ──────────────────────────────────────────
SHELL_NAME="$(basename "${SHELL:-zsh}")"
if [[ "$SHELL_NAME" == "zsh" ]]; then
  PROFILE="$HOME/.zshrc"
elif [[ "$SHELL_NAME" == "bash" ]]; then
  PROFILE="$HOME/.bash_profile"
  [[ -f "$HOME/.bashrc" ]] && PROFILE="$HOME/.bashrc"
else
  PROFILE="$HOME/.profile"
fi

VENV_BIN="$HOME/.optimusprime/venv/bin"
PATH_LINE="export PATH=\"$VENV_BIN:\$PATH\""

if ! grep -qF "$VENV_BIN" "$PROFILE" 2>/dev/null; then
  echo "" >> "$PROFILE"
  echo "# OptimusPrime CLI" >> "$PROFILE"
  echo "$PATH_LINE" >> "$PROFILE"
  echo "[op] Added op to PATH in $PROFILE"
else
  echo "[op] PATH already configured in $PROFILE"
fi

# Apply immediately for this session
export PATH="$VENV_BIN:$PATH"

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
echo "  Run: source $PROFILE (or open a new terminal)"
echo "  Then: op --version"
echo ""
