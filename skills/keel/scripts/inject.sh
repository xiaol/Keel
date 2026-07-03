#!/bin/sh
# Hook wrapper: drift-triggered ledger view injection.
# Usage: inject.sh --context=userprompt|precompact
CTX="userprompt"
case "$1" in --context=*) CTX="${1#--context=}";; esac
KEEL="${CLAUDE_SKILL_DIR:-$HOME/.claude/skills/keel}/scripts/keel.py"
[ -f "$KEEL" ] || KEEL="$(ls "$HOME/.claude/skills/keel/scripts/keel.py" \
  "$HOME/.claude/plugins/marketplaces/keel/skills/keel/scripts/keel.py" \
  2>/dev/null | head -1)"
[ -n "$KEEL" ] && [ -f "$KEEL" ] || exit 0
PY="$(command -v python3 || command -v python)" || exit 0
"$PY" "$KEEL" inject --context="$CTX" 2>/dev/null
exit 0
