#!/usr/bin/env python3
"""keel — an append-only ledger that binds an agent to its plan.

The ledger (.keel/ledger.jsonl) is the single source of truth. Markdown is
only ever a rendered view of it. Phases carry executable acceptance checks;
"done" means the check passed, not that a checkbox was ticked.

Stdlib only. Python 3.8+.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

try:
    import fcntl
except ImportError:  # Windows: degrade to lockless appends
    fcntl = None

KEEL_DIR = ".keel"
LEDGER = "ledger.jsonl"
CHECK_TIMEOUT = 120


# ---------------------------------------------------------------- ledger io

def find_root(start=None):
    """Walk up from start until a .keel dir is found. Returns dir or None."""
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(d, KEEL_DIR)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def ledger_path(root):
    return os.path.join(root, KEEL_DIR, LEDGER)


class Ledger:
    def __init__(self, root):
        self.root = root
        self.path = ledger_path(root)

    def _lockfile(self):
        return open(os.path.join(self.root, KEEL_DIR, ".lock"), "a+")

    def read(self):
        entries = []
        if not os.path.exists(self.path):
            return entries
        with open(self.path, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    e["_id"] = "e%d" % i
                    entries.append(e)
                except json.JSONDecodeError:
                    print("keel: skipping corrupt ledger line %d" % i,
                          file=sys.stderr)
        return entries

    def append(self, entry, precondition=None):
        """Atomically append. If precondition(entries) returns a string,
        abort with that message instead of appending."""
        lock = self._lockfile()
        try:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_EX)
            if precondition:
                err = precondition(self.read())
                if err:
                    return None, err
            entry = dict(entry)
            entry["ts"] = now_iso()
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry, None
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ------------------------------------------------------------ state builder

def build_state(entries):
    st = {
        "goal": None,
        "profile": "default",
        "phases": {},        # pid -> phase dict
        "phase_order": [],
        "findings": {},      # entry id -> finding (superseded ones removed)
        "decisions": [],
        "artifacts": [],
        "errors": {},        # sig -> {text, count, resolution, last_ts}
        "hypotheses": {},    # hid -> {text, status, evidence}
        "hypo_order": [],
        "experiments": {},   # config hash -> result entry
    }
    for e in entries:
        t = e.get("type")
        if t == "init":
            st["profile"] = e.get("profile", "default")
        elif t == "goal":
            st["goal"] = e.get("text")
        elif t == "phase":
            pid = e["pid"]
            st["phases"][pid] = {
                "pid": pid, "title": e.get("title", ""),
                "check": e.get("check", "manual"),
                "status": "pending", "claimed_by": None,
                "done_seq": None, "last_check": None,
            }
            st["phase_order"].append(pid)
        elif t == "phase_status":
            p = st["phases"].get(e.get("pid"))
            if p:
                p["status"] = e.get("status", p["status"])
                if p["status"] == "done":
                    p["done_seq"] = e["_id"]
        elif t == "claim":
            p = st["phases"].get(e.get("pid"))
            if p and p["claimed_by"] is None:
                p["claimed_by"] = e.get("agent", "?")
        elif t == "release":
            p = st["phases"].get(e.get("pid"))
            if p and p["claimed_by"] == e.get("agent", p["claimed_by"]):
                p["claimed_by"] = None
        elif t == "check_result":
            p = st["phases"].get(e.get("pid"))
            if p:
                p["last_check"] = e
        elif t == "finding":
            sup = e.get("supersedes")
            if sup and sup in st["findings"]:
                del st["findings"][sup]
            st["findings"][e["_id"]] = e
        elif t == "decision":
            st["decisions"].append(e)
        elif t == "artifact":
            st["artifacts"].append(e)
        elif t == "error":
            sig = e.get("sig", "")
            rec = st["errors"].setdefault(
                sig, {"text": e.get("text", ""), "count": 0,
                      "resolution": None, "last_ts": ""})
            rec["count"] += 1
            rec["last_ts"] = e.get("ts", "")
        elif t == "error_resolved":
            rec = st["errors"].get(e.get("sig", ""))
            if rec:
                rec["resolution"] = e.get("resolution", "")
        elif t == "hypothesis":
            hid = e["hid"]
            st["hypotheses"][hid] = {
                "hid": hid, "text": e.get("text", ""),
                "status": "open", "evidence": []}
            st["hypo_order"].append(hid)
        elif t == "hypothesis_status":
            h = st["hypotheses"].get(e.get("hid"))
            if h:
                h["status"] = e.get("status", h["status"])
                if e.get("evidence"):
                    h["evidence"].append(e["evidence"])
        elif t == "experiment":
            st["experiments"][e.get("hash", "")] = e
    return st


def error_sig(text):
    """Stable signature for an error: normalize numbers/paths, hash."""
    norm = re.sub(r"0x[0-9a-fA-F]+", "ADDR", text)
    norm = re.sub(r"\d+", "N", norm)
    norm = re.sub(r"/[^\s:]+", "PATH", norm)
    norm = re.sub(r"\s+", " ", norm).strip().lower()
    return hashlib.sha256(norm.encode()).hexdigest()[:8]


# ----------------------------------------------------------------- checks

def run_check(root, check):
    """Run an acceptance check command. Returns (ok, code, tail)."""
    if check == "manual":
        return True, 0, "(manual check — not executable)"
    try:
        r = subprocess.run(
            check, shell=True, cwd=root, timeout=CHECK_TIMEOUT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        tail = r.stdout.decode(errors="replace")[-500:].strip()
        return r.returncode == 0, r.returncode, tail
    except subprocess.TimeoutExpired:
        return False, -1, "check timed out after %ds" % CHECK_TIMEOUT


def has_fresh_pass(phase):
    """True if the phase's LATEST check_result is a pass recorded at or
    after its done transition (so the Stop gate can skip re-running it).
    A later failing result invalidates any earlier pass."""
    lc = phase.get("last_check")
    if phase["done_seq"] is None or lc is None:
        return False
    return bool(lc.get("ok")) and int(lc["_id"][1:]) >= int(
        phase["done_seq"][1:])


# ----------------------------------------------------------------- render

def render(st, budget=2500):
    lines = []
    add = lines.append
    add("# keel state (rendered from .keel/ledger.jsonl — edit via `keel` "
        "CLI, never by hand)")
    if st["goal"]:
        add("**Goal:** " + st["goal"])
    if st["phase_order"]:
        add("")
        add("## Phases")
        for pid in st["phase_order"]:
            p = st["phases"][pid]
            if p["status"] == "dropped":
                continue
            mark = {"pending": " ", "in_progress": ">", "done": "x"}.get(
                p["status"], " ")
            line = "- [%s] %s %s" % (mark, pid, p["title"])
            extras = []
            if p["check"] != "manual":
                res = p["last_check"]
                verdict = ""
                if res is not None:
                    verdict = " — %s" % ("PASS" if res.get("ok") else "FAIL")
                extras.append("check: `%s`%s" % (p["check"], verdict))
            else:
                extras.append("check: manual")
            if p["claimed_by"]:
                extras.append("claimed by %s" % p["claimed_by"])
            add(line + " (" + "; ".join(extras) + ")")
    if st["hypo_order"]:
        add("")
        add("## Hypotheses")
        for hid in st["hypo_order"]:
            h = st["hypotheses"][hid]
            ev = (" — evidence: " + ", ".join(h["evidence"])
                  if h["evidence"] else "")
            add("- %s [%s] %s%s" % (hid, h["status"], h["text"], ev))
    if st["experiments"]:
        add("")
        add("## Experiments (config-hash keyed; a hash with a result is "
            "never rerun)")
        for h, e in list(st["experiments"].items())[-10:]:
            add("- %s exit=%s `%s`" % (h, e.get("code"), e.get("cmd", "")))
    if st["findings"]:
        add("")
        add("## Live findings (superseded entries dropped)")
        for fid, f in list(st["findings"].items())[-30:]:
            refs = (" [%s]" % ",".join(f["refs"])) if f.get("refs") else ""
            add("- (%s) %s%s" % (fid, f.get("text", ""), refs))
    if st["decisions"]:
        add("")
        add("## Decisions")
        for d in st["decisions"][-10:]:
            add("- (%s) %s" % (d["_id"], d.get("text", "")))
    if st["errors"]:
        add("")
        add("## Errors (signature-deduped — do not retry an unresolved "
            "signature with the same action)")
        for sig, rec in st["errors"].items():
            res = (" → resolved: " + rec["resolution"]) if rec["resolution"] \
                else " → UNRESOLVED"
            add("- [%dx] sig=%s %s%s" % (
                rec["count"], sig, rec["text"][:160], res))
    out = "\n".join(lines)
    if len(out) > budget:
        out = out[:budget] + "\n… (truncated; run `keel status` for full view)"
    return out


# ------------------------------------------------------------ subcommands

def require_root():
    root = find_root()
    if not root:
        print("keel: no .keel ledger found (run `keel init` first)",
              file=sys.stderr)
        sys.exit(1)
    return root


def cmd_init(args):
    root = os.getcwd()
    kdir = os.path.join(root, KEEL_DIR)
    os.makedirs(kdir, exist_ok=True)
    led = Ledger(root)
    if os.path.exists(led.path) and not args.force:
        print("keel: ledger already exists at %s" % led.path)
        return
    led.append({"type": "init", "profile": args.profile})
    if args.goal:
        led.append({"type": "goal", "text": args.goal})
    gi = os.path.join(kdir, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w") as f:
            f.write(".lock\nlast_inject.json\n")
    print("keel: initialized %s (profile=%s)" % (led.path, args.profile))


def cmd_goal(args):
    root = require_root()
    Ledger(root).append({"type": "goal", "text": args.text})
    print("keel: goal set")


def cmd_phase(args):
    root = require_root()
    led = Ledger(root)
    st = build_state(led.read())
    if args.action == "add":
        pid = args.id or "p%d" % (len(st["phase_order"]) + 1)
        if pid in st["phases"]:
            print("keel: phase %s already exists" % pid, file=sys.stderr)
            sys.exit(1)
        check = args.check or "manual"
        led.append({"type": "phase", "pid": pid, "title": args.title,
                    "check": check})
        if check == "manual":
            print("keel: added %s (check: manual — prefer an executable "
                  "check when one exists)" % pid)
        else:
            print("keel: added %s (check: %s)" % (pid, check))
    elif args.action == "start":
        _need_phase(st, args.id)
        led.append({"type": "phase_status", "pid": args.id,
                    "status": "in_progress"})
        print("keel: %s in_progress" % args.id)
    elif args.action == "drop":
        _need_phase(st, args.id)
        led.append({"type": "phase_status", "pid": args.id,
                    "status": "dropped"})
        print("keel: %s dropped" % args.id)


def _need_phase(st, pid):
    if pid not in st["phases"]:
        print("keel: unknown phase %s" % pid, file=sys.stderr)
        sys.exit(1)


def cmd_done(args):
    root = require_root()
    led = Ledger(root)
    st = build_state(led.read())
    _need_phase(st, args.id)
    p = st["phases"][args.id]
    if args.skip_check:
        if not args.reason:
            print("keel: --skip-check requires --reason", file=sys.stderr)
            sys.exit(1)
        led.append({"type": "phase_status", "pid": args.id, "status": "done"})
        led.append({"type": "check_result", "pid": args.id, "ok": True,
                    "code": 0, "tail": "SKIPPED: " + args.reason,
                    "skipped": True})
        print("keel: %s done (check skipped: %s)" % (args.id, args.reason))
        return
    ok, code, tail = run_check(root, p["check"])
    if not ok:
        led.append({"type": "check_result", "pid": args.id, "ok": ok,
                    "code": code, "tail": tail})
        print("keel: %s check FAILED (exit %d) — phase NOT marked done"
              % (args.id, code))
        print(tail)
        sys.exit(1)
    # done first, then the passing result, so the gate sees a fresh pass
    led.append({"type": "phase_status", "pid": args.id, "status": "done"})
    led.append({"type": "check_result", "pid": args.id, "ok": ok,
                "code": code, "tail": tail})
    print("keel: %s done (check passed)" % args.id)


def cmd_log(args):
    root = require_root()
    led = Ledger(root)
    entry = {"type": args.kind, "text": args.text}
    if args.refs:
        entry["refs"] = args.refs
    if args.kind == "finding" and args.supersedes:
        entry["supersedes"] = args.supersedes
    if args.kind == "error":
        sig = error_sig(args.text)
        entry["sig"] = sig
        st = build_state(led.read())
        prior = st["errors"].get(sig)
        led.append(entry)
        if prior:
            res = ("resolved: " + prior["resolution"]) if prior["resolution"] \
                else "UNRESOLVED — do not retry the same action"
            print("keel: logged error sig=%s — SEEN %dx BEFORE (%s)"
                  % (sig, prior["count"], res))
        else:
            print("keel: logged error sig=%s (new)" % sig)
        return
    led.append(entry)
    print("keel: logged %s e%d" % (args.kind, len(led.read())))


def cmd_resolve(args):
    root = require_root()
    Ledger(root).append({"type": "error_resolved", "sig": args.sig,
                         "resolution": args.resolution})
    print("keel: error %s resolved" % args.sig)


def cmd_claim(args):
    root = require_root()
    led = Ledger(root)
    agent = args.agent or os.environ.get("KEEL_AGENT", "agent-%d" % os.getpid())

    def precondition(entries):
        st = build_state(entries)
        p = st["phases"].get(args.id)
        if not p:
            return "unknown phase %s" % args.id
        if p["claimed_by"] and p["claimed_by"] != agent:
            return "phase %s already claimed by %s" % (args.id, p["claimed_by"])
        if p["status"] == "done":
            return "phase %s is already done" % args.id
        return None

    _, err = led.append({"type": "claim", "pid": args.id, "agent": agent},
                        precondition=precondition)
    if err:
        print("keel: claim refused — %s" % err, file=sys.stderr)
        sys.exit(1)
    print("keel: %s claimed by %s" % (args.id, agent))


def cmd_release(args):
    root = require_root()
    agent = args.agent or os.environ.get("KEEL_AGENT", "agent-%d" % os.getpid())
    Ledger(root).append({"type": "release", "pid": args.id, "agent": agent})
    print("keel: %s released" % args.id)


def cmd_verify(args):
    root = require_root()
    led = Ledger(root)
    entries = led.read()
    st = build_state(entries)
    problems = []
    for pid in st["phase_order"]:
        p = st["phases"][pid]
        if p["status"] == "in_progress":
            problems.append("%s (%s) is still in_progress" % (pid, p["title"]))
        elif p["status"] == "done" and p["check"] != "manual":
            if args.gate and has_fresh_pass(p):
                continue
            ok, code, tail = run_check(root, p["check"])
            led.append({"type": "check_result", "pid": pid, "ok": ok,
                        "code": code, "tail": tail})
            if not ok:
                problems.append(
                    "%s marked done but its check `%s` fails (exit %d)"
                    % (pid, p["check"], code))
    if args.gate:
        if problems:
            print(json.dumps({
                "decision": "block",
                "reason": ("keel gate: " + "; ".join(problems) +
                           ". Finish the phase and run `keel done <pid>` "
                           "(which executes the check), or `keel phase drop "
                           "<pid>` if it is no longer needed.")}))
        return
    if problems:
        print("keel verify: %d problem(s)" % len(problems))
        for pr in problems:
            print("  - " + pr)
        sys.exit(1)
    print("keel verify: all done-phases hold under their checks")


def cmd_render(args):
    root = require_root()
    st = build_state(Ledger(root).read())
    print(render(st, budget=args.budget))


def cmd_status(args):
    root = require_root()
    st = build_state(Ledger(root).read())
    print(render(st, budget=10**9))


def cmd_inject(args):
    """Hook entrypoint: print rendered view only when re-grounding is
    warranted (ledger changed, long gap, or pre-compaction)."""
    root = find_root()
    if not root:
        return
    led = Ledger(root)
    entries = led.read()
    if not entries:
        return
    stamp_path = os.path.join(root, KEEL_DIR, "last_inject.json")
    stamp = {"lines": -1, "ts": 0}
    try:
        with open(stamp_path) as f:
            stamp = json.load(f)
    except (OSError, ValueError):
        pass
    lines = len(entries)
    stale = (time.time() - stamp.get("ts", 0)) > 900
    changed = lines != stamp.get("lines")
    if args.context != "precompact" and not (changed or stale):
        return
    st = build_state(entries)
    print(render(st, budget=args.budget))
    try:
        with open(stamp_path, "w") as f:
            json.dump({"lines": lines, "ts": time.time()}, f)
    except OSError:
        pass


def cmd_query(args):
    root = require_root()
    st = build_state(Ledger(root).read())
    if args.what == "errors":
        if args.sig:
            rec = st["errors"].get(args.sig)
            if not rec:
                # also accept raw error text and hash it
                rec = st["errors"].get(error_sig(args.sig))
            if rec:
                print(json.dumps(rec, ensure_ascii=False, indent=2))
            else:
                print("keel: signature not seen before — safe to attempt")
            return
        for sig, rec in st["errors"].items():
            print("[%dx] %s %s" % (rec["count"], sig, rec["text"][:100]))
    elif args.what == "findings":
        for fid, f in st["findings"].items():
            print("(%s) %s" % (fid, f.get("text", "")))
    elif args.what == "phases":
        for pid in st["phase_order"]:
            p = st["phases"][pid]
            print("%s\t%s\t%s\t%s" % (pid, p["status"],
                                      p["claimed_by"] or "-", p["title"]))


def cmd_hypo(args):
    root = require_root()
    led = Ledger(root)
    st = build_state(led.read())
    if args.action == "add":
        hid = args.id or "H%d" % (len(st["hypo_order"]) + 1)
        led.append({"type": "hypothesis", "hid": hid, "text": args.text})
        print("keel: added %s" % hid)
    elif args.action == "set":
        if args.id not in st["hypotheses"]:
            print("keel: unknown hypothesis %s" % args.id, file=sys.stderr)
            sys.exit(1)
        if args.status not in ("open", "supported", "refuted"):
            print("keel: status must be open|supported|refuted",
                  file=sys.stderr)
            sys.exit(1)
        led.append({"type": "hypothesis_status", "hid": args.id,
                    "status": args.status, "evidence": args.evidence})
        print("keel: %s → %s" % (args.id, args.status))


def config_hash(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:  # canonicalize JSON configs so formatting doesn't change the hash
        canon = json.dumps(json.loads(raw), sort_keys=True,
                           separators=(",", ":")).encode()
    except ValueError:
        canon = raw
    return hashlib.sha256(canon).hexdigest()[:12]


def cmd_exp(args):
    root = require_root()
    led = Ledger(root)
    h = config_hash(args.config)
    st = build_state(led.read())
    prev = st["experiments"].get(h)
    if prev and not args.force:
        print("keel: experiment with config hash %s already ran "
              "(exit=%s, ts=%s) — refusing to rerun. Result tail:"
              % (h, prev.get("code"), prev.get("ts")))
        print(prev.get("tail", ""))
        print("Use --force to rerun anyway.")
        sys.exit(1)
    argv = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not argv:
        print("keel: no experiment command given (use: keel exp --config "
              "cfg.json -- <command>)", file=sys.stderr)
        sys.exit(1)
    cmd = " ".join(argv)
    print("keel: running experiment %s: %s" % (h, cmd))
    r = subprocess.run(cmd, shell=True, cwd=root,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail = r.stdout.decode(errors="replace")[-1000:]
    sys.stdout.write(tail)
    led.append({"type": "experiment", "hash": h, "cmd": cmd,
                "config": args.config, "code": r.returncode,
                "tail": tail[-500:], "hypothesis": args.hypothesis})
    print("\nkeel: recorded experiment %s (exit %d)" % (h, r.returncode))
    sys.exit(r.returncode)


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(prog="keel")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create .keel ledger here")
    p.add_argument("--goal")
    p.add_argument("--profile", default="default",
                   choices=["default", "research"])
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("goal", help="set/replace the goal")
    p.add_argument("text")
    p.set_defaults(fn=cmd_goal)

    p = sub.add_parser("phase", help="add/start/drop a phase")
    p.add_argument("action", choices=["add", "start", "drop"])
    p.add_argument("title", nargs="?", default="")
    p.add_argument("--id")
    p.add_argument("--check", help="shell command that exits 0 when the "
                   "phase is truly complete")
    p.set_defaults(fn=lambda a: cmd_phase(_phase_fix(a)))

    p = sub.add_parser("done", help="run the phase check; mark done on pass")
    p.add_argument("id")
    p.add_argument("--skip-check", action="store_true")
    p.add_argument("--reason")
    p.set_defaults(fn=cmd_done)

    for kind in ("finding", "decision", "error", "artifact"):
        p = sub.add_parser(kind, help="log a %s" % kind)
        p.add_argument("text")
        p.add_argument("--refs", nargs="*")
        if kind == "finding":
            p.add_argument("--supersedes")
        p.set_defaults(fn=cmd_log, kind=kind)

    p = sub.add_parser("resolve", help="mark an error signature resolved")
    p.add_argument("sig")
    p.add_argument("resolution")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("claim", help="claim a phase (multi-agent)")
    p.add_argument("id")
    p.add_argument("--agent")
    p.set_defaults(fn=cmd_claim)

    p = sub.add_parser("release", help="release a claimed phase")
    p.add_argument("id")
    p.add_argument("--agent")
    p.set_defaults(fn=cmd_release)

    p = sub.add_parser("verify", help="re-run checks of done phases")
    p.add_argument("--gate", action="store_true",
                   help="Stop-hook mode: emit block JSON on problems")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("render", help="budgeted markdown view of the ledger")
    p.add_argument("--budget", type=int, default=2500)
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("status", help="full markdown view")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("inject", help="hook entrypoint (drift-triggered)")
    p.add_argument("--context", default="userprompt",
                   choices=["userprompt", "precompact"])
    p.add_argument("--budget", type=int, default=2500)
    p.set_defaults(fn=cmd_inject)

    p = sub.add_parser("query", help="query errors/findings/phases")
    p.add_argument("what", choices=["errors", "findings", "phases"])
    p.add_argument("--sig", help="error signature or raw error text")
    p.set_defaults(fn=cmd_query)

    p = sub.add_parser("hypo", help="research profile: hypotheses")
    p.add_argument("action", choices=["add", "set"])
    p.add_argument("id_or_text")
    p.add_argument("status", nargs="?")
    p.add_argument("--id")
    p.add_argument("--evidence")
    p.set_defaults(fn=lambda a: cmd_hypo(_hypo_fix(a)))

    p = sub.add_parser("exp", help="research profile: run experiment "
                       "(config-hash deduped)")
    p.add_argument("--config", required=True)
    p.add_argument("--hypothesis")
    p.add_argument("--force", action="store_true")
    p.add_argument("command", nargs=argparse.REMAINDER,
                   help="command to run (after --)")
    p.set_defaults(fn=cmd_exp)

    args = ap.parse_args()
    args.fn(args)


def _phase_fix(a):
    # `phase start p2` / `phase drop p2`: positional title is actually the id
    if a.action in ("start", "drop") and not a.id:
        a.id = a.title
    return a


def _hypo_fix(a):
    if a.action == "add":
        a.text = a.id_or_text
    else:
        a.id = a.id_or_text
    return a


if __name__ == "__main__":
    main()
