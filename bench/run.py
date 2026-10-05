#!/usr/bin/env python3
"""OneCommand benchmark.

Builds a fixed set of prompts headless with the plugin under test and scores
every build from the files OneCommand itself writes — the quality gate verdict,
the acceptance report and the checkpoint state — so improvements to the plugin
become measurable instead of anecdotal.

Subcommands
-----------
run       Build prompts (sequentially — builds share ~/.onecommand/brain) and write
          bench/results/<run-id>/results.{json,md}.
collect   Score an existing build from its stream-json log(s) and project directory.
compare   Compare two results.json files (e.g. before/after a plugin change).

A build needs the `claude` CLI logged in. Unattended runs require
--skip-permissions (passes --dangerously-skip-permissions; only use it in a
sandbox or VM). Each build takes 30–90 minutes.

Exit codes: 0 ok · 1 at least one build failed its gate · 2 usage / setup error
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("bench")
REPO = Path(__file__).resolve().parent.parent
PROMPTS = Path(__file__).resolve().parent / "prompts.json"
BRAIN = Path.home() / ".onecommand" / "brain"


# ─── scoring ──────────────────────────────────────────────────────────────────

def parse_logs(logs: list[Path]) -> dict[str, Any]:
    """Facts from claude stream-json logs (several logs = one build that was resumed)."""
    facts = {"cost_usd": 0.0, "turns": 0, "agents": 0, "foreground_agents": 0, "gate_runs": 0,
             "terminated": False, "logs": [str(p) for p in logs]}
    for log in logs:
        cost = 0.0
        try:
            lines = log.read_text(errors="replace").splitlines()
        except OSError as exc:
            LOG.warning("cannot read %s: %s", log, exc)
            continue
        for raw in lines:
            if "Background tasks still running" in raw and "terminating" in raw:
                facts["terminated"] = True
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get("type") == "result":
                cost = max(cost, float(ev.get("total_cost_usd") or 0))
                facts["turns"] += int(ev.get("num_turns") or 0)
            if ev.get("type") != "assistant":
                continue
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") != "tool_use":
                    continue
                inp = c.get("input") or {}
                if c.get("name") in ("Agent", "Task") and not ev.get("parent_tool_use_id"):
                    facts["agents"] += 1
                    facts["foreground_agents"] += inp.get("run_in_background") is False
                if c.get("name") == "Bash" and "quality-gate.sh" in str(inp.get("command", "")):
                    facts["gate_runs"] += 1
        facts["cost_usd"] += cost  # total_cost_usd is cumulative within one session
    facts["cost_usd"] = round(facts["cost_usd"], 2)
    return facts


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def score_build(project: Path | None, logs: list[Path], wall_minutes: float | None,
                working_memory: dict[str, Any] | None) -> dict[str, Any]:
    gate = read_json(project / ".onecommand" / "gate" / "result.json") if project else None
    acc = (gate or {}).get("acceptance") or {}
    phases = sorted((working_memory or {}).get("phases_completed") or [])
    blocking = int(acc.get("blocking") or 0)
    ratio = (int(acc.get("blocking_passed") or 0) / blocking) if blocking else 0.0
    gate_passed = bool(gate and gate.get("passed"))
    finished = 8 in phases
    # 0–100: verified behaviour dominates; a finished delivery without a green gate scores low.
    score = round(50 * gate_passed + 40 * ratio + 10 * finished, 1)
    return {
        "project_dir": str(project) if project else None,
        "phases_completed": phases,
        "finished": finished,
        "gate_passed": gate_passed,
        "gate_stage": (gate or {}).get("stage"),
        "failed_steps": (gate or {}).get("failed_steps") or ([] if gate else ["gate never ran"]),
        "acceptance": {"passed": int(acc.get("blocking_passed") or 0), "total": blocking,
                       "manual": int(acc.get("manual") or 0), "flaky": int(acc.get("flaky") or 0)},
        "delivery_report": bool(project and (project / "ONECOMMAND-DELIVERY.md").exists()),
        "wall_minutes": round(wall_minutes, 1) if wall_minutes is not None else None,
        **parse_logs(logs),
        "score": score,
    }


# ─── running ──────────────────────────────────────────────────────────────────

def load_prompts(selection: list[str] | None, prompt_set: str) -> list[dict[str, Any]]:
    data = json.loads(PROMPTS.read_text())
    by_id = {p["id"]: p for p in data["prompts"]}
    ids = selection or data["sets"][prompt_set]
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise SystemExit(f"[bench] unknown prompt id(s): {', '.join(unknown)} — known: {', '.join(by_id)}")
    return [by_id[i] for i in ids]


def claude_cmd(prompt: str, plugin_dir: Path, skip_permissions: bool) -> list[str]:
    escaped = prompt.replace('"', '\\"')
    cmd = ["claude", "--plugin-dir", str(plugin_dir), "--output-format", "stream-json", "--verbose",
           "-p", f'/onecommand:onecommand "{escaped}"']
    if skip_permissions:
        cmd.insert(1, "--dangerously-skip-permissions")
    return cmd


def run_one(p: dict[str, Any], run_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    case_dir = run_dir / p["id"]
    app = case_dir / "app"
    app.mkdir(parents=True, exist_ok=True)
    log = case_dir / "build.log"
    cmd = claude_cmd(p["prompt"], Path(args.plugin_dir).resolve(), args.skip_permissions)
    if args.dry_run:
        print(f"[bench] {p['id']}: (cd {app} && {' '.join(cmd)} > {log})")
        return {"id": p["id"], "type": p["type"], "dry_run": True}

    print(f"[bench] ▶ {p['id']} ({p['type']}) — log: {log}", flush=True)
    env = {**os.environ,
           "ONECOMMAND_AUTO_UPDATE": "0",               # never self-update the plugin under test
           # Claude Code may run parallel agents in the background even when the orchestrator asks for
           # foreground; in -p mode the CLI then kills them after a 600 s ceiling (seen in real builds).
           "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}
    started = time.monotonic()
    with log.open("w") as fh:
        try:
            proc = subprocess.run(cmd, cwd=app, stdout=fh, stderr=subprocess.STDOUT, env=env,
                                  timeout=args.timeout * 60)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = "timeout"
    minutes = (time.monotonic() - started) / 60

    wm = read_json(BRAIN / "working_memory.json") or {}
    # The build may have moved itself (e.g. to ~/Desktop/<Name>); the checkpoint knows where.
    project = Path(wm["project_dir"]) if wm.get("project_dir") and Path(wm["project_dir"]).exists() else app
    if project != app:
        LOG.info("%s built in %s", p["id"], project)
    result = {"id": p["id"], "type": p["type"], "exit_code": exit_code, **score_build(project, [log], minutes, wm)}
    (case_dir / "metrics.json").write_text(json.dumps(result, indent=2))
    print(f"[bench] ✓ {p['id']}: score {result['score']} · gate {'PASSED' if result['gate_passed'] else 'FAILED'} · "
          f"acceptance {result['acceptance']['passed']}/{result['acceptance']['total']} · "
          f"{result['wall_minutes']} min · ${result['cost_usd']}", flush=True)
    return result


def plugin_version(plugin_dir: Path) -> str:
    try:
        return json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return "?"


def git_sha(plugin_dir: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(plugin_dir), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip() or "?"
    except (OSError, subprocess.TimeoutExpired):
        return "?"


def render_md(summary: dict[str, Any]) -> str:
    lines = [f"# OneCommand benchmark — {summary['run_id']}", "",
             f"Plugin v{summary['plugin_version']} ({summary['git_sha']}) · {len(summary['builds'])} build(s) · "
             f"mean score **{summary['mean_score']}**", "",
             "| Prompt | Type | Score | Gate | Acceptance | Phases | Minutes | Cost | Agents (fg) | Gate runs |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for b in summary["builds"]:
        if b.get("dry_run"):
            continue
        a = b["acceptance"]
        lines.append(f"| {b['id']} | {b['type']} | {b['score']} | {'✅' if b['gate_passed'] else '❌'} | "
                     f"{a['passed']}/{a['total']} | {len(b['phases_completed'])}/8 | {b['wall_minutes']} | "
                     f"${b['cost_usd']} | {b['agents']} ({b['foreground_agents']}) | {b['gate_runs']} |")
    return "\n".join(lines) + "\n"


def summarize(run_id: str, builds: list[dict[str, Any]], plugin_dir: Path) -> dict[str, Any]:
    scored = [b["score"] for b in builds if "score" in b]
    return {"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "plugin_version": plugin_version(plugin_dir), "git_sha": git_sha(plugin_dir),
            "mean_score": round(sum(scored) / len(scored), 1) if scored else None, "builds": builds}


def cmd_run(args: argparse.Namespace) -> int:
    prompts = load_prompts(args.only, args.set)
    if not args.dry_run and shutil.which("claude") is None:
        print("[bench] the claude CLI is not on PATH", file=sys.stderr)
        return 2
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.out).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    builds = [run_one(p, run_dir, args) for p in prompts]
    summary = summarize(run_id, builds, Path(args.plugin_dir).resolve())
    (run_dir / "results.json").write_text(json.dumps(summary, indent=2))
    (run_dir / "results.md").write_text(render_md(summary))
    print(f"[bench] results: {run_dir / 'results.md'}")
    if args.dry_run:
        return 0
    return 0 if all(b.get("gate_passed") for b in builds) else 1


def cmd_collect(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    wm = read_json(Path(args.working_memory)) if args.working_memory else None
    if wm is None:
        # Fall back to the checkpoint in the brain when it belongs to this project.
        candidate = read_json(BRAIN / "working_memory.json")
        wm = candidate if candidate and Path(candidate.get("project_dir", "")).resolve() == project else {}
    result = {"id": args.id, "type": args.type,
              **score_build(project, [Path(p) for p in args.log], args.minutes, wm)}
    print(json.dumps(result, indent=2))
    return 0 if result["gate_passed"] else 1


def cmd_compare(args: argparse.Namespace) -> int:
    before, after = json.loads(Path(args.before).read_text()), json.loads(Path(args.after).read_text())
    old = {b["id"]: b for b in before["builds"] if "score" in b}
    print(f"OneCommand benchmark: {before['run_id']} (v{before['plugin_version']}) → "
          f"{after['run_id']} (v{after['plugin_version']})")
    print(f"{'prompt':<14}{'score':>16}{'acceptance':>18}{'minutes':>16}{'cost':>16}")
    regressions = 0
    for b in after["builds"]:
        if "score" not in b:
            continue
        o = old.get(b["id"])
        if not o:
            print(f"{b['id']:<14}{'new':>16}")
            continue
        d = b["score"] - o["score"]
        regressions += d < 0
        acc = f"{o['acceptance']['passed']}/{o['acceptance']['total']}→{b['acceptance']['passed']}/{b['acceptance']['total']}"
        print(f"{b['id']:<14}{o['score']:>7}→{b['score']:<6}{d:+5.1f}{acc:>18}"
              f"{(o['wall_minutes'] or 0):>8}→{(b['wall_minutes'] or 0):<6}"
              f"{o['cost_usd']:>8}→{b['cost_usd']:<6}")
    print(f"mean score: {before['mean_score']} → {after['mean_score']}" + (f" · {regressions} regression(s)" if regressions else ""))
    return 1 if regressions else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="build prompts and score them")
    p.add_argument("--set", default="core", choices=("core", "extended"))
    p.add_argument("--only", nargs="+", help="prompt ids to run instead of a set")
    p.add_argument("--plugin-dir", default=str(REPO), help="OneCommand checkout under test")
    p.add_argument("--out", default=str(REPO / "bench" / "results"))
    p.add_argument("--timeout", type=int, default=120, help="minutes per build")
    p.add_argument("--skip-permissions", action="store_true",
                   help="pass --dangerously-skip-permissions (unattended runs; sandbox/VM only)")
    p.add_argument("--dry-run", action="store_true", help="print the commands only")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("collect", help="score an existing build")
    p.add_argument("--project-dir", required=True)
    p.add_argument("--log", nargs="+", required=True, help="stream-json log(s) of the build, in order")
    p.add_argument("--id", default="adhoc")
    p.add_argument("--type", default="web")
    p.add_argument("--minutes", type=float, help="wall-clock minutes, if known")
    p.add_argument("--working-memory", help="working_memory.json of the build (default: the brain's)")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("compare", help="compare two results.json files")
    p.add_argument("before")
    p.add_argument("after")
    p.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="[bench] %(levelname)s %(message)s")
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
