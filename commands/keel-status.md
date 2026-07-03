---
description: Show the full rendered keel ledger state for this project
allowed-tools: Bash
---

Run `$(command -v python3 || command -v python) "${CLAUDE_PLUGIN_ROOT}/skills/keel/scripts/keel.py" status` from the project root and show the user the rendered state. If it reports no ledger, say so and offer to `keel init`.
