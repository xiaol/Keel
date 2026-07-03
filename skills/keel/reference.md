# keel reference

## Ledger format

`.keel/ledger.jsonl` — one JSON object per line, append-only. Never edited in
place; state is derived by replaying all entries. Entry `_id`s are line
numbers (`e1`, `e2`, …) assigned at read time.

| type | fields | meaning |
|------|--------|---------|
| `init` | `profile` | ledger created (`default` or `research`) |
| `goal` | `text` | goal set/replaced (last one wins) |
| `phase` | `pid`, `title`, `check` | phase declared with acceptance check |
| `phase_status` | `pid`, `status` | `pending` → `in_progress` → `done` (or `dropped`) |
| `claim` / `release` | `pid`, `agent` | multi-agent phase ownership |
| `check_result` | `pid`, `ok`, `code`, `tail`, `skipped?` | outcome of running the check |
| `finding` | `text`, `refs?`, `supersedes?` | discovery; superseding removes the old one from views |
| `decision` / `artifact` | `text`, `refs?` | choice made / thing produced |
| `error` | `text`, `sig` | error occurrence, deduped by signature |
| `error_resolved` | `sig`, `resolution` | how a signature was fixed |
| `hypothesis` | `hid`, `text` | research: claim under test |
| `hypothesis_status` | `hid`, `status`, `evidence?` | `open` / `supported` / `refuted` |
| `experiment` | `hash`, `cmd`, `config`, `code`, `tail` | run keyed by config hash |

## Error signatures

`sig = sha256(normalized text)[:8]` where normalization lowercases, collapses
whitespace, and replaces hex addresses, numbers, and paths with placeholders —
so `Error at 0x7f3a in /tmp/a.py line 12` and `Error at 0x991b in /tmp/b.py
line 40` share a signature.

## Stop gate policy

Blocks only when:
1. any phase is `in_progress`, or
2. any `done` phase with an executable check has no passing `check_result`
   recorded at-or-after its done transition — in which case the check is
   re-run once, and blocks if it fails.

Pending phases never block (stopping between phases is legitimate). Because
`keel done` records a passing check, the gate normally does zero work.

## Injection policy (drift-triggered)

`keel inject` prints the rendered view only if: the ledger line count changed
since the last injection, more than 15 minutes elapsed, or the context is
`precompact` (always inject before compaction). The stamp lives in
`.keel/last_inject.json` (gitignored).

## Concurrency

Appends take an exclusive `flock` on `.keel/.lock`; `claim` re-reads the
ledger under the lock before appending, so two agents cannot both win a
phase. On platforms without `fcntl`, appends are lockless (single-agent use
only).

## CLI summary

```
keel init [--goal G] [--profile default|research] [--force]
keel goal TEXT
keel phase add TITLE [--id pN] [--check CMD|manual]
keel phase start|drop pN
keel done pN [--skip-check --reason R]
keel finding|decision|error|artifact TEXT [--refs ...] [--supersedes eN]
keel resolve SIG RESOLUTION
keel claim|release pN [--agent NAME]        # or KEEL_AGENT env
keel verify [--gate]
keel render [--budget CHARS] | keel status
keel inject --context userprompt|precompact
keel query errors|findings|phases [--sig TEXT]
keel hypo add TEXT | keel hypo set Hn open|supported|refuted [--evidence eN]
keel exp --config FILE [--hypothesis Hn] [--force] -- COMMAND...
```
