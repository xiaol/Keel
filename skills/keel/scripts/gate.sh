#!/bin/sh
# Stop-hook wrapper: block the stop only when the ledger proves work is
# unfinished (an in_progress phase, or a done phase whose check now fails).
KEEL="${CLAUDE_SKILL_DIR:-$HOME/.claude/skills/keel}/scripts/keel.py"
[ -f "$KEEL" ] || KEEL="$(ls "$HOME/.claude/skills/keel/scripts/keel.py" \
  "$HOME/.claude/plugins/marketplaces/keel/skills/keel/scripts/keel.py" \
  2>/dev/null | head -1)"
[ -n "$KEEL" ] && [ -f "$KEEL" ] || exit 0
PY="$(command -v python3 || command -v python)" || exit 0
"$PY" "$KEEL" verify --gate 2>/dev/null
exit 0
