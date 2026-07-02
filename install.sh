#!/usr/bin/env bash
# OptimusPrime installer — macOS / Linux
# Idempotent: safe to run multiple times.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLOBAL_DIR="$HOME/.optimusprime"
VENV_DIR="$GLOBAL_DIR/venv"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

# ── colours + progress ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'

_STEP=0
step() { _STEP=$((_STEP + 1)); printf "${BOLD}[%d/8]${NC} %-35s" "$_STEP" "$1"; }
ok()   { echo -e " ${GREEN}✓${NC}"; }
fail() { echo -e " ${RED}✗${NC}"; echo -e "${RED}  ERROR: $*${NC}" >&2; exit 1; }
warn() { echo -e " ${YELLOW}⚠${NC}  $*"; }

# ── parse args ────────────────────────────────────────────────────────────────
MODE="install"
for arg in "$@"; do
    case "$arg" in
        --update)    MODE="update"    ;;
        --uninstall) MODE="uninstall" ;;
    esac
done

# ── UNINSTALL ─────────────────────────────────────────────────────────────────
if [[ "$MODE" == "uninstall" ]]; then
    echo ""
    echo -e "${BOLD}⚡ OptimusPrime — uninstalling...${NC}"
    echo ""

    [[ -f "$GLOBAL_DIR/venv/bin/op" ]] && "$GLOBAL_DIR/venv/bin/op" menubar stop 2>/dev/null || true

    UNINSTALL_PY="python3"
    [[ -f "$VENV_DIR/bin/python3" ]] && UNINSTALL_PY="$VENV_DIR/bin/python3"

    if [[ -f "$CLAUDE_SETTINGS" ]]; then
        "$UNINSTALL_PY" - "$CLAUDE_SETTINGS" << 'PYEOF'
import json, sys, os
from pathlib import Path

p = Path(sys.argv[1])
try:
    settings = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    print("  settings.json unreadable — skipped")
    sys.exit(0)

OP_SCRIPTS = {
    "pre-response.py", "predictive-context.py", "pre-write-injector.py",
    "scope-guard.py", "loop-detector.py", "dependency-analyzer.py",
    "breaking-change-detector.py", "output-compressor.py", "attempt-logger.py",
    "post-write-analyzer.py", "task-state-updater.py", "todo-scanner.py",
    "done-checker.py", "session-logger.py", "learner-hook.py",
}

def is_op_hook(cmd):
    return any(s in cmd for s in OP_SCRIPTS)

for event in list(settings.get("hooks", {}).keys()):
    settings["hooks"][event] = [
        h for h in settings["hooks"][event]
        if not is_op_hook(h.get("command", ""))
    ]

settings.pop("statusLine", None)
settings.get("mcpServers", {}).pop("optimusprime", None)

tmp = str(p) + f".tmp.{os.getpid()}"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
os.replace(tmp, str(p))
print("  Hooks and statusLine removed ✓")
PYEOF
    fi

    if [[ -d "$VENV_DIR" ]]; then
        rm -rf "$VENV_DIR"
        echo "  Venv removed ✓"
    fi

    echo ""
    echo -e "${GREEN}✓ OptimusPrime uninstalled.${NC}"
    echo "  Your .optimusprime/ data is preserved."
    echo "  To fully remove all data: rm -rf $GLOBAL_DIR"
    echo ""
    exit 0
fi

# ── UPDATE ────────────────────────────────────────────────────────────────────
if [[ "$MODE" == "update" ]]; then
    echo ""
    echo -e "${BOLD}⚡ OptimusPrime — updating...${NC}"
    echo ""
    if [[ -d "$REPO_DIR/.git" ]]; then
        git -C "$REPO_DIR" pull --quiet && echo "  ↑ Updated from git ✓"
    else
        echo "  (Not a git repo — skipping pull)"
    fi
    [[ -f "$GLOBAL_DIR/venv/bin/op" ]] && "$GLOBAL_DIR/venv/bin/op" menubar stop 2>/dev/null || true
    echo ""
    echo "  Reinstalling..."
    echo ""
else
    echo ""
    echo -e "${BOLD}⚡ OptimusPrime — installing...${NC}"
    echo ""
fi

# ── STEP 1: Python ────────────────────────────────────────────────────────────
step "Checking Python"
if ! command -v python3 &>/dev/null; then
    fail "python3 not found. Install Python 3.8+ from https://python.org"
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYMAJ=$(python3 -c "import sys; print(sys.version_info.major)")
PYMIN=$(python3 -c "import sys; print(sys.version_info.minor)")
if [[ "$PYMAJ" -lt 3 ]] || [[ "$PYMAJ" -eq 3 && "$PYMIN" -lt 8 ]]; then
    fail "Python $PYVER found — OptimusPrime requires 3.8+. Download: https://python.org/downloads"
fi
ok

# ── STEP 2: venv ──────────────────────────────────────────────────────────────
step "Creating venv"
mkdir -p "$GLOBAL_DIR"
if [[ ! -f "$VENV_DIR/bin/python" ]]; then
    python3 -m venv "$VENV_DIR" 2>/dev/null \
        || fail "venv creation failed. Try: sudo apt install python3-venv (Ubuntu/Debian)"
fi
VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
ok

# ── STEP 3: Install package ────────────────────────────────────────────────────
step "Installing package"
PIP_LOG="$GLOBAL_DIR/pip-install.log"
"$VENV_PIP" install --quiet --upgrade pip 2>/dev/null \
    || fail "pip upgrade failed. Check network connection and try again."
if [[ "$PYMAJ" -gt 3 ]] || [[ "$PYMAJ" -eq 3 && "$PYMIN" -ge 10 ]]; then
    "$VENV_PIP" install --quiet -e "$REPO_DIR[mcp]" 2>"$PIP_LOG" \
        || fail "pip install failed. See $PIP_LOG — try: $VENV_PIP install -e $REPO_DIR --verbose"
else
    "$VENV_PIP" install --quiet -e "$REPO_DIR" 2>"$PIP_LOG" \
        || fail "pip install failed. See $PIP_LOG — try: $VENV_PIP install -e $REPO_DIR --verbose"
fi
mkdir -p "$GLOBAL_DIR/skills"
cp -r "$REPO_DIR/skills/." "$GLOBAL_DIR/skills/"
PROJECT_OP_DIR="$(pwd)/.optimusprime"
if [[ ! -d "$PROJECT_OP_DIR" ]]; then
    mkdir -p "$PROJECT_OP_DIR"
    touch "$PROJECT_OP_DIR/.gitkeep"
fi
ok

# ── STEP 4: Register hooks ────────────────────────────────────────────────────
step "Registering hooks"
mkdir -p "$(dirname "$CLAUDE_SETTINGS")"

"$VENV_PY" - <<PYEOF
import json, os
from pathlib import Path

settings_path = Path("$CLAUDE_SETTINGS")
repo_dir      = Path("$REPO_DIR")

if settings_path.exists():
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        import shutil
        bak = str(settings_path) + ".bak"
        shutil.copy(str(settings_path), bak)
        print(f"  ⚠ settings.json was malformed — backed up to {bak}, starting fresh")
        settings = {}
else:
    settings = {}

hooks_cfg = settings.setdefault("hooks", {})

def _merge_hooks(hook_list, hooks_with_timeouts):
    existing_cmds = {h.get("command") for h in hook_list if isinstance(h, dict)}
    for path, timeout in hooks_with_timeouts:
        cmd = f"python3 {path}"
        if cmd not in existing_cmds:
            hook_list.append({"type": "command", "command": cmd, "timeout": timeout})
            existing_cmds.add(cmd)

_merge_hooks(hooks_cfg.setdefault("UserPromptSubmit", []),
    [(str(repo_dir / "hooks" / "pre" / "pre-response.py"), 8)])

_merge_hooks(hooks_cfg.setdefault("PreToolUse", []), [
    (str(repo_dir / "hooks" / "pre" / "predictive-context.py"), 8),
    (str(repo_dir / "hooks" / "pre" / "pre-write-injector.py"), 8),
    (str(repo_dir / "hooks" / "pre" / "scope-guard.py"), 10),
    (str(repo_dir / "hooks" / "pre" / "loop-detector.py"), 10),
    (str(repo_dir / "hooks" / "pre" / "dependency-analyzer.py"), 10),
    (str(repo_dir / "hooks" / "pre" / "breaking-change-detector.py"), 10),
])

_merge_hooks(hooks_cfg.setdefault("PostToolUse", []), [
    (str(repo_dir / "hooks" / "post" / "output-compressor.py"), 10),
    (str(repo_dir / "hooks" / "post" / "attempt-logger.py"), 10),
    (str(repo_dir / "hooks" / "post" / "post-write-analyzer.py"), 10),
    (str(repo_dir / "hooks" / "post" / "task-state-updater.py"), 10),
])

_merge_hooks(hooks_cfg.setdefault("Stop", []), [
    (str(repo_dir / "hooks" / "post" / "todo-scanner.py"), 15),
    (str(repo_dir / "hooks" / "post" / "done-checker.py"), 15),
    (str(repo_dir / "hooks" / "post" / "session-logger.py"), 15),
    (str(repo_dir / "hooks" / "post" / "learner-hook.py"), 20),
])

_merge_hooks(hooks_cfg.setdefault("SubagentStop", []), [
    (str(repo_dir / "hooks" / "post" / "todo-scanner.py"), 15),
    (str(repo_dir / "hooks" / "post" / "session-logger.py"), 15),
    (str(repo_dir / "hooks" / "post" / "learner-hook.py"), 20),
])

_merge_hooks(hooks_cfg.setdefault("PreCompact", []),
    [(str(repo_dir / "hooks" / "post" / "session-logger.py"), 15)])

mcp_servers = settings.setdefault("mcpServers", {})
if "optimusprime" not in mcp_servers:
    mcp_servers["optimusprime"] = {
        "command": "python3",
        "args": [str(repo_dir / "mcp" / "server.py")],
        "env": {}
    }

tmp = settings_path.parent / f".settings.json.tmp.{os.getpid()}"
tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
tmp.replace(settings_path)
PYEOF
ok

# ── STEP 5: StatusLine ────────────────────────────────────────────────────────
step "Registering statusLine"
STATUSLINE_SH="$REPO_DIR/hooks/optimusprime-statusline.sh"
chmod +x "$STATUSLINE_SH"

"$VENV_PY" - "$CLAUDE_SETTINGS" "$STATUSLINE_SH" << 'PYEOF'
import json, sys, os
from pathlib import Path
p = Path(sys.argv[1])
script_path = sys.argv[2]
if p.is_file():
    try:
        settings = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        settings = {}
else:
    settings = {}
if "statusLine" not in settings:
    settings["statusLine"] = {"type": "command", "command": script_path}
    tmp = str(p) + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, str(p))
PYEOF

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
fi
export PATH="$VENV_BIN:$PATH"
ok

# ── STEP 6: Global Claude Code skill ──────────────────────────────────────────
step "Installing Claude Code skill"
SKILL_DIR="$HOME/.claude/skills/optimusprime"
mkdir -p "$SKILL_DIR"
cp "$REPO_DIR/skills/optimusprime/SKILL.md" "$SKILL_DIR/SKILL.md" 2>/dev/null \
    || cp "$REPO_DIR/.claude/skills/optimusprime/SKILL.md" "$SKILL_DIR/SKILL.md" 2>/dev/null \
    || true
# Write skill inline if file not found in repo yet
if [[ ! -f "$SKILL_DIR/SKILL.md" ]]; then
cat > "$SKILL_DIR/SKILL.md" << 'SKILLEOF'
---
name: optimusprime
description: >
  OptimusPrime session state protocol — scope enforcement, loop detection,
  output compression, Auto Bots, cross-session memory. Invoke /optimusprime
  to see live status dashboard. Trigger: /optimusprime, /op, "op status",
  "is optimusprime running", "show op status".
---

OptimusPrime is active. Hooks fire silently on every tool call and response.

When invoked, show the live status dashboard by reading .optimusprime/ from the current project (walk up from cwd). Display goal, tokens, decisions, loop streak, compression %, and active Auto Bots.

If .optimusprime/ not found: run `mkdir -p .optimusprime` and report initialized.

Auto Bots activate automatically: Caveman Bot at 40k+ tokens, Ponytail Bot on minimal budget, UI/UX Pro Max on frontend files.

Use /optimusprime:op-watch for detailed dashboard, /optimusprime:op-decisions to view logged decisions, /optimusprime:op-autopilot for session brief.
SKILLEOF
fi
ok

# ── STEP 7: Auto Bots ─────────────────────────────────────────────────────────
step "Installing Auto Bots"
"$GLOBAL_DIR/venv/bin/op" skills install --all \
    2>/dev/null && ok || warn "skills install skipped (network or already installed)"

# ── STEP 8: Menu bar ──────────────────────────────────────────────────────────
step "Starting menu bar"
"$GLOBAL_DIR/venv/bin/op" menubar start \
    2>/dev/null && ok || warn "menu bar skipped (optional — pip install 'optimusprime[menubar]')"

# ── Post-install verification ─────────────────────────────────────────────────
echo ""
"$VENV_PY" -c "import optimusprime; print('  Package: ok ✓')" \
    || echo "  Package: ⚠ check failed — try: $VENV_PIP install -e $REPO_DIR"
"$GLOBAL_DIR/venv/bin/op" --version 2>/dev/null \
    && echo "  op command: working ✓" \
    || echo "  op command: ⚠ PATH issue — run: source $PROFILE"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${GREEN} ⚡ OptimusPrime installed!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo ""
echo "  → Restart Claude Code (hooks + skill take effect on next launch)"
echo "  → Type: /optimusprime        — live status inside Claude Code"
echo "  → Type: /optimusprime:op-watch — full dashboard (no terminal)"
echo "  → Run: op menubar autostart  — launch menu bar at login"
echo ""
echo "  source $PROFILE   (or open a new terminal)"
echo "  op --version"
echo ""
