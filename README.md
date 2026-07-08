# keel

**The plan that binds the agent.**

keel is a planning skill for AI coding agents where the plan is not a story
the agent tells — it's a contract the agent is held to. State lives in an
append-only JSONL ledger; every phase carries an executable acceptance check;
"done" means *the check passed*, not that a checkbox was ticked.

A keel is the part of the ship you never see that keeps it on course.

## Why not just planning-with-files?

File-based planning ([Manus-style](https://github.com/OthmanAdi/planning-with-files))
made one great point: context is RAM, the filesystem is disk. But free-form
markdown planning has structural problems that more markdown can't fix:

| | markdown planning | keel |
|---|---|---|
| "Done" means | a checkbox was ticked | an acceptance command exited 0 |
| Stop gate | greps for unchecked boxes | **re-runs the failing phase's check** |
| State | 3 growing prose files | typed ledger + budgeted rendered view |
| Old findings | accumulate forever, can contradict | superseded entries drop out of the view |
| "Have I tried this?" | vibes | error-signature query (`keel query errors --sig ...`) |
| Context injection | every tool call, unconditionally | drift-triggered: only when the ledger changed |
| Multiple agents | not addressed | atomic phase claiming on the shared ledger |
| Experiments | not addressed | config-hash dedup: a run that exists is never silently repeated |

One sentence: markdown planning makes the agent **narrate** its work to disk;
keel makes the disk **bind** the agent.

## The core loop

```bash
keel init --goal "Add --json flag to the report CLI"
keel phase add "Flag parsing" --check "python -m pytest tests/test_cli.py -q"

keel phase start p1
# ... agent works ...
keel done p1        # runs the check — refuses to mark done if it fails
```

Everything is one self-contained stdlib-only Python file
([`skills/keel/scripts/keel.py`](skills/keel/scripts/keel.py)) writing to
`.keel/ledger.jsonl` in your project. Markdown views are always *rendered*
from the ledger (`keel status`), never authored, so they can't drift from
the truth.

## What the agent gets

**Verifiable completion.** Checks are written *before* the work, as
acceptance criteria. The Claude Code Stop hook runs `keel verify --gate`: the
agent cannot end its turn while a phase is `in_progress` or while a
"done" phase's check fails. Because `keel done` records a passing check,
the gate is normally free.

**A memory that can forget.** Findings supersede older findings
(`--supersedes e12`), so the rendered view shows current belief, not a
contradiction pile. Errors dedupe by normalized signature — retrying an
action against an unresolved signature is flagged the moment it's logged.

**Drift-triggered re-grounding.** Instead of re-injecting the plan on every
tool call, the `UserPromptSubmit` hook injects the rendered view only when
the ledger changed since the agent last saw it (or 15+ minutes passed, or
compaction is imminent via `PreCompact`). Fewer tokens, same grounding.

**Multi-agent coordination.** `keel claim p3` is an atomic, lock-protected
append — two workers cannot win the same phase. All agents share one ledger,
so the rendered view doubles as the team's coordination surface.

**A research profile.** `keel init --profile research` adds hypotheses with
open/supported/refuted status and evidence links, plus `keel exp`: runs are
keyed by the SHA-256 of the canonicalized config, and a hash that already
has a result is refused rather than silently rerun.

## Install (Agent Skills / Vercel)

keel follows the open [Agent Skills](https://agentskills.io/specification)
layout, so it can be installed directly from this GitHub repo with Vercel's
skills CLI:

```bash
npx skills add xiaol/Keel --skill keel
```

To inspect what the repo exposes before installing:

```bash
npx skills add xiaol/Keel --list
```

Skills installed through the CLI can be discovered by the broader
[skills.sh](https://www.skills.sh/) ecosystem through normal sharing and
install activity.

## Install (GitHub Copilot)

GitHub Copilot's skill CLI can install skills from GitHub repositories:

```bash
gh skill install xiaol/Keel keel
```

## Install (Claude Code)

```bash
git clone https://github.com/xiaol/Keel ~/.claude/skills/keel-repo
ln -s ~/.claude/skills/keel-repo/skills/keel ~/.claude/skills/keel
```

or as a plugin: `/plugin marketplace add xiaol/Keel` then `/plugin install keel`.

The skill's hooks (defined in [`skills/keel/SKILL.md`](skills/keel/SKILL.md))
activate automatically in any project containing a `.keel/` directory and do
nothing elsewhere.

## Install (Codex CLI)

Codex has no lifecycle hooks, so the adapter skill
([`adapters/codex/keel/SKILL.md`](adapters/codex/keel/SKILL.md)) turns the
Stop gate and re-grounding into standing instructions: run `keel status` on
resume, `keel verify` before declaring done, `keel render` every ~10 tool
calls. Same ledger, same CLI — prompt-side enforcement instead of hooks.

```bash
git clone https://github.com/xiaol/Keel ~/keel
mkdir -p ~/.codex/skills/keel/references
ln -sfn ~/keel/adapters/codex/keel/SKILL.md ~/.codex/skills/keel/SKILL.md
ln -sfn ~/keel/skills/keel/scripts ~/.codex/skills/keel/scripts
ln -sfn ~/keel/skills/keel/reference.md ~/.codex/skills/keel/references/reference.md
```

Because both installs share one `keel.py` and one `.keel/ledger.jsonl`,
Claude Code and Codex can work the same project's plan interchangeably — or
simultaneously, via `keel claim`.

The CLI also works standalone with any agent (or human):

```bash
alias keel='python3 ~/.claude/skills/keel/scripts/keel.py'
```

## Share

The shortest share text is:

> keel: ledger-bound planning for AI coding agents. Append-only task state,
> executable checks per phase, stop-gate verification, multi-agent claims, and
> config-hash experiment dedup.
>
> Install: `npx skills add xiaol/Keel --skill keel`

Good places to share it:

- GitHub repo topics: `agent-skills`, `ai-agents`, `codex`, `claude-code`,
  `planning`, `developer-tools`
- [skills.sh](https://www.skills.sh/) via install activity from
  `npx skills add xiaol/Keel --skill keel`
- Hacker News as a Show HN post
- X / Twitter with a short demo GIF or terminal transcript
- Reddit communities for agent tooling and coding agents
- Discord or Slack communities around Codex, Claude Code, Vercel AI, and
  agent engineering

## Session recovery

After `/clear`, a crash, or compaction, the ledger *is* the recovery: the
next `UserPromptSubmit` injects the rendered view (goal, phase states, live
findings, unresolved error signatures), and the skill instructs the agent to
run `keel status` before anything else. There is no separate catch-up
machinery because state was never in the conversation to begin with.

## Repo layout

```
skills/keel/
  SKILL.md              skill definition + hooks (UserPromptSubmit, PreCompact, Stop)
  reference.md          ledger schema, gate policy, CLI reference
  templates/example-session.md
  scripts/keel.py       the entire implementation (stdlib only)
  scripts/inject.sh     hook wrapper: drift-triggered view injection
  scripts/gate.sh       hook wrapper: Stop gate
commands/               /keel-status, /keel-verify slash commands
tests/test_keel.sh      end-to-end CLI test
```

## License

MIT
