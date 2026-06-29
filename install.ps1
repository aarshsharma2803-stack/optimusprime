#Requires -Version 5.1
<#
.SYNOPSIS
    OptimusPrime installer for Windows (PowerShell).
    Idempotent — safe to run multiple times.
.EXAMPLE
    .\install.ps1
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$GlobalDir = Join-Path $HOME '.optimusprime'
$VenvDir   = Join-Path $GlobalDir 'venv'
$ClaudeSettings = Join-Path $HOME '.claude' 'settings.json'

function Write-Info  { param([string]$msg) Write-Host "[op] $msg" -ForegroundColor Green }
function Write-Warn  { param([string]$msg) Write-Host "[op] $msg" -ForegroundColor Yellow }
function Write-Err   { param([string]$msg) Write-Error "[op] ERROR: $msg"; exit 1 }

# ── 1. python3 >= 3.8 ─────────────────────────────────────────────────────────
$python = $null
foreach ($cmd in @('python', 'python3', 'py')) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match 'Python (\d+)\.(\d+)') {
            $maj = [int]$Matches[1]; $min = [int]$Matches[2]
            if ($maj -ge 3 -and $min -ge 8) { $python = $cmd; break }
        }
    } catch { }
}
if (-not $python) {
    Write-Err "Python 3.8+ not found. Install from https://python.org and re-run."
}
$verStr = (& $python --version 2>&1) -replace 'Python ', ''
Write-Info "Python $verStr OK"
$pymaj = [int]($verStr -split '\.')[0]
$pymin = [int]($verStr -split '\.')[1]

# ── 2. venv at %USERPROFILE%\.optimusprime\venv ───────────────────────────────
New-Item -ItemType Directory -Path $GlobalDir -Force | Out-Null
$venvPy  = Join-Path $VenvDir 'Scripts' 'python.exe'
$venvPip = Join-Path $VenvDir 'Scripts' 'pip.exe'

if (-not (Test-Path $venvPy)) {
    Write-Info "Creating venv at $VenvDir ..."
    & $python -m venv $VenvDir
} else {
    Write-Info "venv exists, skipping creation"
}

# ── 3. pip install -e . ───────────────────────────────────────────────────────
Write-Info "Installing OptimusPrime into venv ..."
& $venvPip install --quiet --upgrade pip | Out-Null

if ($pymaj -gt 3 -or ($pymaj -eq 3 -and $pymin -ge 10)) {
    & $venvPip install --quiet -e "$RepoDir[mcp]"
    Write-Info "Package installed with MCP server support OK"
} else {
    & $venvPip install --quiet -e $RepoDir
    Write-Warn "Python $verStr : MCP server skipped (requires 3.10+). Core hooks + CLI installed."
}

# ── 4. copy skills ────────────────────────────────────────────────────────────
Write-Info "Copying skills to $GlobalDir\skills ..."
$skillsSrc = Join-Path $RepoDir 'skills'
$skillsDst = Join-Path $GlobalDir 'skills'
Copy-Item -Path $skillsSrc -Destination $skillsDst -Recurse -Force
Write-Info "Skills copied OK"

# ── 5. create project .optimusprime\ ─────────────────────────────────────────
$ProjectOpDir = Join-Path (Get-Location) '.optimusprime'
if (-not (Test-Path $ProjectOpDir)) {
    New-Item -ItemType Directory -Path $ProjectOpDir -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $ProjectOpDir '.gitkeep') -Force | Out-Null
    Write-Info "Created $ProjectOpDir"
} else {
    Write-Info "Project .optimusprime\ already exists"
}

# ── 6. register hooks + MCP in %USERPROFILE%\.claude\settings.json ────────────
$claudeDir = Split-Path $ClaudeSettings
New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null
Write-Info "Merging hooks and MCP server into $ClaudeSettings ..."

$pyScript = @"
import json, os, sys
from pathlib import Path

settings_path = Path(r'$ClaudeSettings')
repo_dir      = Path(r'$RepoDir')

if settings_path.exists():
    try:
        settings = json.loads(settings_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        settings = {}
else:
    settings = {}

hooks_cfg = settings.setdefault('hooks', {})

pre_hooks = [
    str(repo_dir / 'hooks' / 'pre' / 'scope-guard.py'),
    str(repo_dir / 'hooks' / 'pre' / 'dependency-analyzer.py'),
    str(repo_dir / 'hooks' / 'pre' / 'loop-detector.py'),
    str(repo_dir / 'hooks' / 'pre' / 'breaking-change-detector.py'),
]
pre_list = hooks_cfg.setdefault('PreToolUse', [])
for hook_path in pre_hooks:
    cmd = f'python {hook_path}'
    entry = {'type': 'command', 'command': cmd}
    if not any(h.get('command') == cmd for h in pre_list):
        pre_list.append(entry)

post_hooks = [
    str(repo_dir / 'hooks' / 'post' / 'output-compressor.py'),
    str(repo_dir / 'hooks' / 'post' / 'attempt-logger.py'),
    str(repo_dir / 'hooks' / 'post' / 'todo-scanner.py'),
]
post_list = hooks_cfg.setdefault('PostToolUse', [])
for hook_path in post_hooks:
    cmd = f'python {hook_path}'
    entry = {'type': 'command', 'command': cmd}
    if not any(h.get('command') == cmd for h in post_list):
        post_list.append(entry)

stop_hooks = [
    str(repo_dir / 'hooks' / 'post' / 'done-checker.py'),
    str(repo_dir / 'hooks' / 'post' / 'session-logger.py'),
]
stop_list = hooks_cfg.setdefault('Stop', [])
for hook_path in stop_hooks:
    cmd = f'python {hook_path}'
    entry = {'type': 'command', 'command': cmd}
    if not any(h.get('command') == cmd for h in stop_list):
        stop_list.append(entry)

mcp_servers = settings.setdefault('mcpServers', {})
if 'optimusprime' not in mcp_servers:
    mcp_servers['optimusprime'] = {
        'command': 'python',
        'args': [str(repo_dir / 'mcp' / 'server.py')],
        'env': {}
    }

tmp = settings_path.parent / f'.settings.json.tmp.{os.getpid()}'
tmp.write_text(json.dumps(settings, indent=2), encoding='utf-8')
tmp.replace(settings_path)
print('settings.json updated')
"@

& $venvPy -c $pyScript
Write-Info "Hooks and MCP registered OK"

# ── PATH setup ────────────────────────────────────────────────────────────────
$VenvScripts = Join-Path $VenvDir 'Scripts'
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$VenvScripts*") {
    [Environment]::SetEnvironmentVariable(
        "PATH",
        "$VenvScripts;" + $userPath,
        "User"
    )
    Write-Info "Added op to user PATH ($VenvScripts)"
} else {
    Write-Info "PATH already configured"
}
# Apply immediately for this session
$env:PATH = "$VenvScripts;$env:PATH"

# ── 7. summary ────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
Write-Host " OptimusPrime installed successfully!"         -ForegroundColor Green
Write-Host "══════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Global dir:  $GlobalDir"
Write-Host "  Project dir: $ProjectOpDir"
Write-Host "  Settings:    $ClaudeSettings"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Restart Claude Code (hooks take effect on next launch)"
Write-Host "  2. Start a new session -- OptimusPrime activates automatically"
Write-Host "  3. Run: op snapshot          to see current session state"
Write-Host "  4. Run: op decision list --last 10    to review decisions"
Write-Host ""
Write-Host "  Install community skills:"
Write-Host "    op skills install superpowers"
Write-Host "    op skills install caveman"
Write-Host "    op skills install --all"
Write-Host ""
Write-Host "  Open a new terminal, then: op --version"
Write-Host ""
