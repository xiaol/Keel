---
name: keel
description: "Ledger-bound planning for AI coding agents: an append-only JSONL ledger (.keel/ledger.jsonl) where every plan phase carries an executable acceptance check. 'Done' means the check passed, not that a checkbox was ticked. Use when planning, breaking down, or organizing any multi-step task, research project, or work requiring 5+ tool calls; supports multi-agent phase claiming and a research profile with hypothesis tracking and experiment dedup."
user-invocable: true
allowed-tools: "Read Write Edit Bash Glob Grep"
hooks:
  UserPromptSubmit:
    - hooks:
        - type: command
          command: "sh \"${CLAUDE_SKILL_DIR}/scripts/inject.sh\" --context=userprompt; exit 0"
  PreCompact:
    - matcher: "*"
      hooks:
        - type: command
          command: "sh \"${CLAUDE_SKILL_DIR}/scripts/inject.sh\" --context=precompact; exit 0"
  Stop:
    - hooks:
        - type: command
          command: "sh \"${CLAUDE_SKILL_DIR}/scripts/gate.sh\"; exit 0"
metadata:
  version: "0.1.0"
---

# keel

The ledger binds you; markdown only describes you. Everything important goes
through the `keel` CLI into `.keel/ledger.jsonl` — an append-only,
machine-checkable record. You never edit `.keel/` files by hand.

Set once per session for convenience:

```bash
KEEL="$(command -v python3 || command -v python) ${CLAUDE_SKILL_DIR}/scripts/keel.py"
```

## FIRST: restore state

If `.keel/` exists in the project (or any parent), run `$KEEL status` before
anything else. The rendered view is the authoritative state: current phases,
what passed its check, unresolved error signatures, live findings. Trust it
over your memory of the conversation.

## Starting a task

For any multi-step task (roughly 5+ tool calls):

```bash
$KEEL init --goal "one-sentence goal"          # add --profile research for research work
$KEEL phase add "Parse the config" --check "python -m pytest tests/test_config.py -q"
$KEEL phase add "Wire up CLI flag" --check "myapp --dry-run --new-flag 2>&1 | grep -q OK"
$KEEL phase add "Write migration notes" --check manual
```

**The check is the point.** A phase's `--check` is a shell command that exits
0 only when the phase is genuinely complete — a test selector, a
file-existence assertion, a grep over output. Write the check *when you write
the phase*, before doing the work; it is your acceptance criterion. Use
`--check manual` only when no executable check exists, and treat every manual
check as a smell.

## Working a phase

```bash
$KEEL phase start p1        # marks in_progress — the Stop gate now knows work is open
# ... do the work ...
$KEEL done p1               # RUNS the check; refuses to mark done if it fails
```

`keel done` failing is a feature: it caught a phase you believed finished but
wasn't. Fix the work (or the check, if the check itself was wrong) and rerun.
`keel done p1 --skip-check --reason "..."` exists for emergencies and is
recorded as skipped in the ledger — visible to anyone auditing the run.

## Logging as you go

- `$KEEL finding "the retry logic lives in transport.py, not client.py" --refs src/transport.py`
  — after any discovery worth surviving a context reset. To correct an earlier
  finding, pass `--supersedes e12`; the old one disappears from the rendered
  view instead of contradicting you forever.
- `$KEEL decision "use SQLite over JSONL for the cache"` — decisions with a why.
- `$KEEL artifact "wrote benchmark results" --refs results/bench.csv`

## Errors: query before retrying

Every error gets logged, and keel deduplicates by a normalized signature:

```bash
$KEEL error "ImportError: no module named foo.bar"
# → keel: logged error sig=3fa2c1b0 — SEEN 2x BEFORE (UNRESOLVED — do not retry the same action)
```

If keel says the signature was seen before and is unresolved, **do not repeat
the same action** — mutate the approach. When you fix one:

```bash
$KEEL resolve 3fa2c1b0 "foo needs pip install foo-extras"
```

Before attempting something that failed in a past session, ask the ledger:
`$KEEL query errors --sig "the error text"`.

## Multi-agent work

When several agents share one project, claim a phase before touching it:

```bash
KEEL_AGENT=worker-2 $KEEL claim p3     # atomic; refused if another agent holds it
KEEL_AGENT=worker-2 $KEEL release p3   # give it up without finishing
```

Claims and findings from all agents land in the same ledger, so the rendered
view is the shared coordination surface. An orchestrator assigns phases;
workers claim, work, `keel done`, release nothing (done releases implicitly).

## Research profile

`keel init --profile research` for experiment-driven work:

```bash
$KEEL hypo add "warmup length explains the gap, not LR"
$KEEL exp --config runs/ablation_a.json --hypothesis H1 -- python train.py --config runs/ablation_a.json
$KEEL hypo set H1 supported --evidence e17
```

`keel exp` hashes the canonicalized config; **a hash that already has a
recorded result is refused** (shown instead), so you can never silently rerun
an experiment and waste compute or overwrite evidence. `--force` overrides,
and is recorded.

## What the hooks do (so you aren't surprised)

- **UserPromptSubmit / PreCompact**: the rendered ledger view is injected
  only when it drifted from what you last saw (ledger changed, >15 min gap,
  or compaction imminent). No injection means nothing changed — don't re-read.
- **Stop gate**: stopping is blocked only if a phase is `in_progress`, or a
  phase marked done has a check that now fails. Pending phases don't block —
  pausing between phases is normal. To abandon a phase, `$KEEL phase drop pN`.

## Rules

1. No complex task without `keel init` and phases-with-checks first.
2. Write the check before the work. Manual checks need a stated reason.
3. Log findings immediately after discoveries — especially anything read
   from images, browser output, or other content that won't survive context loss.
4. `keel error` before any retry; never repeat an action against an
   unresolved signature.
5. Never edit `.keel/` by hand, and never present a rendered view as if you
   authored it — regenerate with `$KEEL status`.
6. When the user extends the task, add phases; don't start a second ledger.
