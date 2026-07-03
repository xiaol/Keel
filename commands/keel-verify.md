---
description: Re-run every done phase's acceptance check and report which hold
allowed-tools: Bash
---

Run `$(command -v python3 || command -v python) "${CLAUDE_PLUGIN_ROOT}/skills/keel/scripts/keel.py" verify` from the project root. Report which phases hold under their checks and which fail. For each failure, read the check output tail and propose whether the work regressed or the check is stale.
