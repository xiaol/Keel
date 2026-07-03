#!/bin/sh
# End-to-end test of the keel CLI. Exits non-zero on first failure.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
KEEL_PY="$REPO/skills/keel/scripts/keel.py"
PY="$(command -v python3 || command -v python)"
keel() { "$PY" "$KEEL_PY" "$@"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

fail() { echo "FAIL: $1" >&2; exit 1; }
pass() { echo "ok - $1"; }

# --- init + goal ---
keel init --goal "test goal" >/dev/null
[ -f .keel/ledger.jsonl ] || fail "init creates ledger"
pass "init"

# --- phases with checks ---
keel phase add "make out.txt" --check "test -f out.txt" >/dev/null
keel phase add "manual phase" >/dev/null
keel phase start p1 >/dev/null

# done must FAIL while check fails
if keel done p1 >/dev/null 2>&1; then fail "done should refuse on failing check"; fi
pass "done refuses failing check"

# gate must block while p1 in_progress
GATE="$(keel verify --gate)"
echo "$GATE" | grep -q '"decision": "block"' || fail "gate blocks on in_progress"
pass "gate blocks in_progress phase"

touch out.txt
keel done p1 >/dev/null
keel query phases | grep -qE "^p1[[:space:]]+done" || fail "p1 marked done after passing check"
pass "done passes when check passes"

# gate must be quiet now (p2 pending doesn't block)
GATE="$(keel verify --gate)"
[ -z "$GATE" ] || fail "gate should be silent with only pending phases"
pass "gate silent on pending"

# regression: remove artifact, gate must catch it... only via verify (non-gate re-runs)
rm out.txt
if keel verify >/dev/null 2>&1; then fail "verify should fail after regression"; fi
pass "verify catches regression"
GATE="$(keel verify --gate)"
echo "$GATE" | grep -q '"decision": "block"' || fail "gate re-runs check after new check_result failure"
pass "gate blocks on regressed done-phase"
touch out.txt
keel verify >/dev/null || fail "verify green again"

# --- findings + supersede ---
keel finding "old belief" >/dev/null
FID="$(keel query findings | tail -1 | sed 's/^(\(e[0-9]*\)).*/\1/')"
keel finding "new belief" --supersedes "$FID" >/dev/null
keel query findings | grep -q "old belief" && fail "superseded finding still visible"
keel query findings | grep -q "new belief" || fail "new finding missing"
pass "finding supersession"

# --- error signature dedup ---
keel error "TypeError at 0x7f3a in /tmp/a.py line 12" >/dev/null
OUT="$(keel error "TypeError at 0x991b in /tmp/b.py line 40")"
echo "$OUT" | grep -q "SEEN 1x BEFORE" || fail "error signature dedup"
pass "error signature dedup"
SIG="$(echo "$OUT" | sed 's/.*sig=\([0-9a-f]*\).*/\1/')"
keel resolve "$SIG" "fixed it" >/dev/null
keel query errors --sig "TypeError at 0xdead in /tmp/c.py line 9" | grep -q "fixed it" \
  || fail "resolved signature queryable"
pass "error resolution query"

# --- claims ---
KEEL_AGENT=w1 keel claim p2 >/dev/null
if KEEL_AGENT=w2 keel claim p2 >/dev/null 2>&1; then fail "second claim should be refused"; fi
pass "claim conflict refused"
KEEL_AGENT=w1 keel release p2 >/dev/null
KEEL_AGENT=w2 keel claim p2 >/dev/null || fail "claim after release"
pass "claim after release"

# --- skip-check audit trail ---
if keel done p2 --skip-check >/dev/null 2>&1; then fail "skip-check requires reason"; fi
keel done p2 --skip-check --reason "manual review done" >/dev/null
grep -q '"skipped": true' .keel/ledger.jsonl || fail "skip recorded in ledger"
pass "skip-check recorded"

# --- render / inject drift ---
keel render | grep -q "test goal" || fail "render shows goal"
OUT="$(keel inject --context=userprompt)"
[ -n "$OUT" ] || fail "first inject emits view"
OUT="$(keel inject --context=userprompt)"
[ -z "$OUT" ] || fail "second inject should be suppressed (no drift)"
keel decision "something changed" >/dev/null
OUT="$(keel inject --context=userprompt)"
[ -n "$OUT" ] || fail "inject after ledger change"
OUT="$(keel inject --context=precompact)"
[ -n "$OUT" ] || fail "precompact always injects"
pass "drift-triggered injection"

# --- research profile ---
cd "$TMP" && mkdir research && cd research
keel init --goal "research" --profile research >/dev/null
keel hypo add "warmup explains gap" >/dev/null
echo '{"lr": 0.001,   "steps": 100}' > cfg.json
keel exp --config cfg.json --hypothesis H1 -- "echo result=42" >/dev/null 2>&1 || true
# same config, different formatting → same hash → refused
echo '{"steps":100,"lr":0.001}' > cfg.json
if keel exp --config cfg.json -- "echo again" >/dev/null 2>&1; then
  fail "exp rerun with same config hash should be refused"
fi
pass "experiment config-hash dedup"
keel hypo set H1 supported --evidence e4 >/dev/null
keel status | grep -q "H1 \[supported\]" || fail "hypothesis status rendered"
pass "hypothesis lifecycle"

echo ""
echo "ALL TESTS PASSED"
