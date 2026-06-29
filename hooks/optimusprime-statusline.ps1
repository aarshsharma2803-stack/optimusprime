#Requires -Version 5.1
# OptimusPrime statusline for Windows PowerShell
# Shows compact session status in Claude Code UI

$OpDir = ""

# Find .optimusprime/ from cwd upward
$dir = (Get-Location).Path
while ($dir -ne [System.IO.Path]::GetPathRoot($dir)) {
    $candidate = Join-Path $dir ".optimusprime"
    if (Test-Path $candidate -PathType Container) {
        $OpDir = $candidate
        break
    }
    $dir = Split-Path $dir -Parent
    if (-not $dir) { break }
}

# No .optimusprime found — show minimal badge
if (-not $OpDir) {
    Write-Output "[⚡OP]"
    exit 0
}

# Read token estimate
$Tokens = "0"
$Cost = '$0.000'
$CostLogPath = Join-Path $OpDir "cost-log.json"
if (Test-Path $CostLogPath) {
    $pyTokens = @"
import json,sys
try:
    data=json.load(open(r'$CostLogPath'))
    sessions=data.get('sessions',[])
    if sessions:
        s=sessions[-1]
        t=s.get('token_estimate',s.get('estimated_input_tokens',0))
        print(f'{t//1000}k' if t>=1000 else str(t))
    else: print('0')
except: print('0')
"@
    $pyResult = python -c $pyTokens 2>$null
    if ($pyResult) { $Tokens = $pyResult.Trim() }

    $pyCost = @"
import json,sys
try:
    data=json.load(open(r'$CostLogPath'))
    sessions=data.get('sessions',[])
    if sessions:
        c=sessions[-1].get('cost_estimate',sessions[-1].get('estimated_cost_usd',0))
        print(f'\${c:.3f}')
    else: print('\$0.000')
except: print('\$0.000')
"@
    $cResult = python -c $pyCost 2>$null
    if ($cResult) { $Cost = $cResult.Trim() }
}

# Read loop status
$Loops = ""
$LoopPath = Join-Path $OpDir "loop-state.json"
if (Test-Path $LoopPath) {
    $pyLoop = @"
import json
try:
    d=json.load(open(r'$LoopPath'))
    streak=d.get('consecutive_failures',0)
    if streak>0: print(f'L{streak}')
    else: print('')
except: print('')
"@
    $lResult = python -c $pyLoop 2>$null
    if ($lResult) { $Loops = $lResult.Trim() }
}

# Read decision count
$Decisions = ""
$DecPath = Join-Path $OpDir "decisions.md"
if (Test-Path $DecPath) {
    $count = (Select-String -Path $DecPath -Pattern "DECIDED|DECISION" -ErrorAction SilentlyContinue).Count
    if ($count -gt 0) { $Decisions = "d$count" }
}

# Read scope violations today
$Violations = ""
$SgPath = Join-Path $OpDir "scope-guard-log.json"
if (Test-Path $SgPath) {
    $today = (Get-Date).ToString("yyyy-MM-dd")
    $pyViol = @"
import json
try:
    d=json.load(open(r'$SgPath'))
    entries=d if isinstance(d,list) else d.get('entries',[])
    today_blocks=[e for e in entries if '$today' in str(e.get('timestamp',''))]
    if today_blocks: print(f'V{len(today_blocks)}')
    else: print('')
except: print('')
"@
    $vResult = python -c $pyViol 2>$null
    if ($vResult) { $Violations = $vResult.Trim() }
}

# Build status line
$Status = "[OP"
if ($Tokens -and $Tokens -ne "0") { $Status += " tok:$Tokens" }
if ($Cost -and $Cost -ne '$0.000') { $Status += " $Cost" }
if ($Loops) { $Status += " $Loops" }
if ($Decisions) { $Status += " $Decisions" }
if ($Violations) { $Status += " $Violations" }
$Status += "]"

Write-Output $Status
