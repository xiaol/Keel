---
name: keel
description: "Ledger-bound planning: keep task state in an append-only JSONL ledger (.keel/ledger.jsonl) where every plan phase carries an executable acceptance check, so 'done' means the check passed. Use when planning, breaking down, or organizing any multi-step project, research task, or work requiring 5+ tool calls; supports multi-agent phase claiming and a research profile with hypothesis tracking and experiment dedup. Also use to resume work in any repo that contains a .keel directory."
---

# keel (Codex adapter)

The ledger binds you; markdown only describes you. Everything important goes
through the `keel` CLI into `.keel/ledger.jsonl` — an append-only,
machine-checkable record. Never edit `.keel/` files by hand.

```bash
KEEL="$(command -v python3 || command -v python) $HOME/.codex/skills/keel/scripts/keel.py"
```

Codex has no lifecycle hooks, so YOU enforce what hooks enforce elsewhere.
Three standing obligations, non-negotiable:

1. **On session start / task resume**: if `.keel/` exists in the project (or
   a parent), run `$KEEL status` before anything else and trust it over your
   memory of the conversation.
2. **Before declaring any task complete or ending a work turn**: run
   `$KEEL verify`. If it exits non-zero, you are not done — a phase is still
   in_progress or a "done" phase's check now fails. Fix it or
   `$KEEL phase drop pN` with a stated reason.
3. **After roughly every 10 tool calls, and always when resuming after
   compaction or feeling uncertain about state**: run `$KEEL render` to
   re-ground on the current phase, live findings, and unresolved errors.

## Starting a task

For any multi-step task (roughly 5+ tool calls):

```bash
$KEEL init --goal "one-sentence goal"          # add --profile research for research work
$KEEL phase add "Parse the config" --check "python -m pytest tests/test_config.py -q"
$KEEL phase add "Write migration notes" --check manual
```

**The check is the point.** A phase's `--check` is a shell command that exits
0 only when the phase is genuinely complete — a test selector, a
file-existence assertion, a grep over output. Write the check *when you write
the phase*, before doing the work. Use `--check manual` only when no
executable check exists; treat every manual check as a smell.

## Working a phase

```bash
$KEEL phase start p1        # mark in_progress BEFORE touching the work
# ... do the work ...
$KEEL done p1               # RUNS the check; refuses to mark done if it fails
```

`keel done` failing is a feature: it caught a phase you believed finished but
wasn't. Fix the work (or the check, if the check was wrong) and rerun.
`--skip-check --reason "..."` exists for emergencies and is recorded as
skipped, visible to anyone auditing the run.

## Logging as you go

- `$KEEL finding "text" --refs path` after any discovery worth surviving a
  context reset — especially content read from images or browser output.
  To correct an earlier finding, pass `--supersedes e12`.
- `$KEEL decision "text"` for choices with a why.
- `$KEEL artifact "text" --refs path` for things produced.

## Errors: query before retrying

```bash
$KEEL error "ImportError: no module named foo.bar"
# → sig=3fa2c1b0 — SEEN 2x BEFORE (UNRESOLVED — do not retry the same action)
$KEEL resolve 3fa2c1b0 "foo needs pip install foo-extras"
$KEEL query errors --sig "some error text"     # ask before attempting risky repeats
```

If a signature was seen before and is unresolved, do not repeat the same
action — mutate the approach.

## Multi-agent and research

```bash
KEEL_AGENT=w1 $KEEL claim p3     # atomic; refused if another agent holds it
$KEEL hypo add "warmup length explains the gap"
$KEEL exp --config runs/a.json --hypothesis H1 -- python train.py --config runs/a.json
$KEEL hypo set H1 supported --evidence e17
```

`keel exp` refuses to rerun a config whose canonical hash already has a
recorded result (`--force` overrides, and is recorded).

See `references/reference.md` for the full ledger schema and CLI summary.
