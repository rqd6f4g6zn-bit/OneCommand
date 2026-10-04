#!/usr/bin/env python3
"""OneCommand cross-agent learnings.

Shared memory between Claude Code and Codex: every fix the self-healer makes
is recorded, and once a fix has been confirmed often enough it becomes a
permanent rule that every future build loads before healing.

Files (default directory ~/.onecommand/memory, override with --memory-dir or
ONECOMMAND_MEMORY_DIR):
  cross_learnings.json   every recorded learning with its confirmation count
  evolved_rules.md       confirmed learnings as rules — read by the self-healer

Rules are deliberately kept in the user's memory directory, not in the plugin
files: plugin files are replaced on every install/upgrade and tracked in git,
so rules written there were either lost or left a dirty checkout.

Subcommands
-----------
read     print known learnings (optionally filtered by stack)
record   add a learning, or reinforce an existing one with the same error
evolve   promote learnings with >= --threshold confirmations into evolved_rules.md
stats    one-line summary

Exit codes: 0 ok · 1 runtime error · 2 usage error
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import logging
import os
import re
import sys
import tempfile
import uuid
from typing import Any, Iterator

LOG = logging.getLogger("learnings")

MAX_LEARNINGS = 200
DEFAULT_THRESHOLD = 3
CATEGORIES = ("error_fix", "pattern", "dependency", "stack_preference")
AGENTS = ("claude", "codex")
RULES_HEADER = "## Auto-Evolved Rules — Cross-Agent Learnings"


# ─── storage ──────────────────────────────────────────────────────────────────

def memory_dir(arg: str | None) -> str:
    path = arg or os.environ.get("ONECOMMAND_MEMORY_DIR") or os.path.expanduser("~/.onecommand/memory")
    os.makedirs(path, exist_ok=True)
    return path


@contextlib.contextmanager
def locked(directory: str) -> Iterator[None]:
    """Serialise writers (Claude Code and Codex may run at the same time)."""
    lock_path = os.path.join(directory, ".learnings.lock")
    with open(lock_path, "a+") as fh:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        except ImportError:  # non-POSIX: best effort, atomic replace still protects the file
            LOG.debug("fcntl unavailable — running without lock")
        yield


def load(directory: str, repair: bool = False) -> dict[str, Any]:
    path = os.path.join(directory, "cross_learnings.json")
    if not os.path.exists(path):
        return {"version": "1.0", "learnings": []}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        if not repair:
            raise SystemExit(f"[learnings] {path} is not valid JSON ({exc}) — the next record/evolve moves it aside")
        # Never overwrite a file we cannot read — keep a copy and start a fresh one.
        backup = f"{path}.corrupt-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
        os.replace(path, backup)
        LOG.warning("cross_learnings.json was unreadable (%s) — moved to %s", exc, backup)
        return {"version": "1.0", "learnings": []}
    if not isinstance(data, dict) or not isinstance(data.get("learnings"), list):
        data = {"version": "1.0", "learnings": data.get("learnings", []) if isinstance(data, dict) else []}
    return data


def write_atomic(path: str, content: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)


def save(directory: str, data: dict[str, Any]) -> None:
    data["learnings"] = data["learnings"][-MAX_LEARNINGS:]
    write_atomic(os.path.join(directory, "cross_learnings.json"), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def today() -> str:
    return dt.date.today().isoformat()


# ─── commands ─────────────────────────────────────────────────────────────────

def cmd_read(args: argparse.Namespace) -> int:
    data = load(memory_dir(args.memory_dir))
    items = data["learnings"]
    if args.stack:
        needle = args.stack.lower()
        items = [l for l in items if needle in str(l.get("stack", "")).lower() or not l.get("stack")]
    if not items:
        print("[learnings] no learnings yet" + (f" for stack '{args.stack}'" if args.stack else ""))
        return 0
    items = sorted(items, key=lambda l: l.get("confirmations", 1), reverse=True)[: args.limit]
    print(f"[learnings] {len(data['learnings'])} learnings in memory — top {len(items)}:")
    for l in items:
        print(f"  [{l.get('source_agent', '?')}][{l.get('category', '?')}][x{l.get('confirmations', 1)}] "
              f"{l.get('description') or l.get('error_pattern', '?')}")
        print(f"      error: {l.get('error_pattern', '')[:160]}")
        print(f"      fix:   {l.get('fix', '')[:160]}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    directory = memory_dir(args.memory_dir)
    with locked(directory):
        data = load(directory, repair=True)
        key = normalise(args.error)
        existing = next((l for l in data["learnings"] if normalise(l.get("error_pattern", "")) == key), None)
        if existing:
            existing["confirmations"] = int(existing.get("confirmations", 1)) + 1
            existing.setdefault("confirmed_by", []).append(args.agent)
            existing["last_confirmed"] = today()
            if args.fix and args.fix != existing.get("fix"):
                existing.setdefault("alternative_fixes", [])
                if args.fix not in existing["alternative_fixes"]:
                    existing["alternative_fixes"].append(args.fix)
            print(f"[learnings] reinforced: '{existing.get('description')}' (x{existing['confirmations']})")
        else:
            data["learnings"].append({
                "id": uuid.uuid4().hex[:8],
                "source_agent": args.agent,
                "category": args.category,
                "error_pattern": args.error,
                "fix": args.fix,
                "stack": args.stack or "",
                "file_context": args.file or "",
                "description": args.description,
                "confirmations": 1,
                "confirmed_by": [args.agent],
                "date": today(),
                "applied_to_skill": False,
            })
            print(f"[learnings] new learning saved: '{args.description}'")
        save(directory, data)
    return 0


def render_rules(rules: list[dict[str, Any]]) -> str:
    lines = [
        RULES_HEADER,
        "",
        f"*Generated {today()} by hooks/learnings.py · {len(rules)} confirmed rule(s) · "
        "apply a rule when the error matches, before trying anything else.*",
        "",
    ]
    for l in sorted(rules, key=lambda r: r.get("confirmations", 0), reverse=True):
        agents = sorted(set(l.get("confirmed_by", [])))
        lines += [
            f"### [{l.get('category', 'error_fix')}] {l.get('description') or l.get('error_pattern', '?')}",
            f"- **Error pattern**: `{l.get('error_pattern', '')}`",
            f"- **Fix**: `{l.get('fix', '')}`",
            f"- **Stack**: {l.get('stack') or 'any'}",
            f"- **Confirmed**: {l.get('confirmations', 0)}x by {', '.join(agents) or '?'}",
            "",
        ]
    return "\n".join(lines)


def cmd_evolve(args: argparse.Namespace) -> int:
    directory = memory_dir(args.memory_dir)
    with locked(directory):
        data = load(directory, repair=True)
        ready = [l for l in data["learnings"]
                 if int(l.get("confirmations", 0)) >= args.threshold and not l.get("applied_to_skill")]
        for l in ready:
            l["applied_to_skill"] = True
            l["applied_date"] = today()
        # Regenerate from ALL promoted learnings — promoting a new batch must not drop earlier rules.
        rules = [l for l in data["learnings"] if l.get("applied_to_skill")]
        rules_path = os.path.join(directory, "evolved_rules.md")
        if rules:
            write_atomic(rules_path, render_rules(rules))
        if ready:
            save(directory, data)
    pending = [l for l in data["learnings"] if not l.get("applied_to_skill")]
    if ready:
        print(f"[learnings] {len(ready)} learning(s) promoted → {len(rules)} rules in {rules_path}")
    else:
        top = max((int(l.get("confirmations", 0)) for l in pending), default=0)
        print(f"[learnings] nothing to promote — {len(rules)} rules active, {len(pending)} pending "
              f"(best {top}/{args.threshold} confirmations)")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    data = load(memory_dir(args.memory_dir))
    total = len(data["learnings"])
    applied = sum(1 for l in data["learnings"] if l.get("applied_to_skill"))
    by_agent: dict[str, int] = {}
    for l in data["learnings"]:
        by_agent[l.get("source_agent", "?")] = by_agent.get(l.get("source_agent", "?"), 0) + 1
    agents = ", ".join(f"{k}: {v}" for k, v in sorted(by_agent.items())) or "none"
    print(f"[learnings] {total} learnings ({agents}) · {applied} promoted to rules · {total - applied} pending")
    return 0


# ─── cli ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--memory-dir", help="default: $ONECOMMAND_MEMORY_DIR or ~/.onecommand/memory")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("read", help="print known learnings")
    p.add_argument("--stack", help="only learnings for this stack (substring match) plus stack-agnostic ones")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("record", help="record or reinforce a learning")
    p.add_argument("--error", required=True, help="the error line that identifies the problem")
    p.add_argument("--fix", required=True, help="what fixed it (command or code change)")
    p.add_argument("--description", required=True, help="one-line human summary")
    p.add_argument("--file", help="file the fix touched")
    p.add_argument("--stack", help="e.g. 'Next.js + Prisma'")
    p.add_argument("--category", choices=CATEGORIES, default="error_fix")
    p.add_argument("--agent", choices=AGENTS, default=os.environ.get("ONECOMMAND_AGENT", "claude"),
                   help="who made the fix (default: $ONECOMMAND_AGENT or claude)")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("evolve", help="promote confirmed learnings into evolved_rules.md")
    p.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    p.set_defaults(func=cmd_evolve)

    p = sub.add_parser("stats", help="one-line summary")
    p.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="[learnings] %(levelname)s %(message)s")
    if getattr(args, "threshold", 1) < 1:
        parser.error("--threshold must be >= 1")
    try:
        return args.func(args)
    except OSError as exc:
        print(f"[learnings] error: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
