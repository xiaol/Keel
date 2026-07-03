# Worked examples

## Coding task

```bash
keel init --goal "Add --json output flag to the report CLI"
keel phase add "Add flag parsing + plumbing" --check "python -m pytest tests/test_cli.py -q"
keel phase add "JSON serializer for report model" --check "python -c 'import json,report; json.dumps(report.Report.demo().to_dict())'"
keel phase add "Update README usage section" --check "grep -q -- '--json' README.md"

keel phase start p1
keel finding "flag parsing centralized in cli/opts.py:parse_args, not per-command" --refs cli/opts.py
keel done p1                      # runs pytest; refuses on red

keel phase start p2
keel error "TypeError: Object of type datetime is not JSON serializable"
# → sig recorded; if seen before unresolved, change approach instead of retrying
keel resolve a1b2c3d4 "added default=str to json.dumps"
keel done p2

keel phase start p3
keel done p3
keel verify                       # all done-phases hold under their checks
```

## Research task

```bash
keel init --goal "Does warmup length explain the LSA/DSA gap?" --profile research
keel hypo add "gap closes when warmup matched at 2k steps"
keel phase add "Run matched-warmup ablation" --check "test -f results/warmup2k/metrics.json"

keel exp --config runs/warmup2k.json --hypothesis H1 -- python train.py --config runs/warmup2k.json
# rerunning with the same config file is refused: the hash already has a result

keel finding "loss curves converge after 1.5k steps at matched warmup" --refs results/warmup2k/metrics.json
keel hypo set H1 supported --evidence e6
keel done p1
```

## Multi-agent

```bash
# orchestrator
keel init --goal "Migrate all call sites of old_api()"
keel phase add "Migrate src/a/" --check "! grep -rn old_api src/a/"
keel phase add "Migrate src/b/" --check "! grep -rn old_api src/b/"

# worker 1                          # worker 2
KEEL_AGENT=w1 keel claim p1         KEEL_AGENT=w2 keel claim p2
# ... work ...                      # ... work ...
keel done p1                        keel done p2
```
