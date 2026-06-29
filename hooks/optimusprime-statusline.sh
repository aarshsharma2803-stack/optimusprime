#!/usr/bin/env bash
# OptimusPrime statusline — runs every few seconds
# Shows compact session status in Claude Code UI

OP_DIR=""

# Find .optimusprime/ from cwd upward
dir="$PWD"
while [[ "$dir" != "/" ]]; do
  if [[ -d "$dir/.optimusprime" ]]; then
    OP_DIR="$dir/.optimusprime"
    break
  fi
  dir="$(dirname "$dir")"
done

# No .optimusprime found — show minimal badge
if [[ -z "$OP_DIR" ]]; then
  echo "[⚡OP]"
  exit 0
fi

# Read token estimate
TOKENS="0"
COST="\$0.000"
if [[ -f "$OP_DIR/cost-log.json" ]]; then
  TOKENS=$(python3 -c "
import json,sys
try:
  data=json.load(open('$OP_DIR/cost-log.json'))
  sessions=data.get('sessions',[])
  if sessions:
    s=sessions[-1]
    t=s.get('token_estimate',s.get('estimated_input_tokens',0))
    print(f'{t//1000}k' if t>=1000 else str(t))
  else: print('0')
except: print('0')
" 2>/dev/null || echo "0")
  COST=$(python3 -c "
import json,sys
try:
  data=json.load(open('$OP_DIR/cost-log.json'))
  sessions=data.get('sessions',[])
  if sessions:
    c=sessions[-1].get('cost_estimate',sessions[-1].get('estimated_cost_usd',0))
    print(f'\${c:.3f}')
  else: print('\$0.000')
except: print('\$0.000')
" 2>/dev/null || echo '$0.000')
fi

# Read loop status
LOOPS=""
if [[ -f "$OP_DIR/loop-state.json" ]]; then
  STREAK=$(python3 -c "
import json
try:
  d=json.load(open('$OP_DIR/loop-state.json'))
  streak=d.get('consecutive_failures',0)
  if streak>0: print(f'🔁{streak}')
  else: print('')
except: print('')
" 2>/dev/null || echo "")
  LOOPS="$STREAK"
fi

# Read active auto bots
BOTS=""
if [[ -f "$OP_DIR/skills.json" ]]; then
  BOTS=$(python3 -c "
import json
try:
  d=json.load(open('$OP_DIR/skills.json'))
  installed=d.get('installed',{})
  active=[k for k,v in installed.items() if v.get('mode') in ('auto','always')]
  if active: print('🤖'+','.join(active[:2]))
  else: print('')
except: print('')
" 2>/dev/null || echo "")
fi

# Read decision count
DECISIONS=""
if [[ -f "$OP_DIR/decisions.md" ]]; then
  COUNT=$(grep -c "DECIDED\|DECISION" "$OP_DIR/decisions.md" 2>/dev/null || echo "0")
  if [[ "$COUNT" -gt 0 ]]; then
    DECISIONS="📝${COUNT}"
  fi
fi

# Read scope violations today
VIOLATIONS=""
if [[ -f "$OP_DIR/scope-guard-log.json" ]]; then
  TODAY=$(date +%Y-%m-%d)
  VCOUNT=$(python3 -c "
import json
try:
  d=json.load(open('$OP_DIR/scope-guard-log.json'))
  entries=d if isinstance(d,list) else d.get('entries',[])
  today_blocks=[e for e in entries if '$TODAY' in str(e.get('timestamp',''))]
  if today_blocks: print(f'🚫{len(today_blocks)}')
  else: print('')
except: print('')
" 2>/dev/null || echo "")
  VIOLATIONS="$VCOUNT"
fi

# Build status line
STATUS="[⚡OP"
[[ -n "$TOKENS" && "$TOKENS" != "0" ]] && STATUS+=" tok:${TOKENS}"
[[ -n "$COST" && "$COST" != '$0.000' ]] && STATUS+=" ${COST}"
[[ -n "$LOOPS" ]] && STATUS+=" ${LOOPS}"
[[ -n "$BOTS" ]] && STATUS+=" ${BOTS}"
[[ -n "$DECISIONS" ]] && STATUS+=" ${DECISIONS}"
[[ -n "$VIOLATIONS" ]] && STATUS+=" ${VIOLATIONS}"
STATUS+="]"

echo "$STATUS"
