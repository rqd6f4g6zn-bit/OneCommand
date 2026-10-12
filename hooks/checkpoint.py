#!/usr/bin/env python3
"""OneCommand build checkpoints.

One command per phase keeps a build resumable — after a crash, a closed
terminal, a manual /clear or a headless run that was cut off. Written as a
script because a real run showed that prose instructions ("invoke
context-manager CHECKPOINT, then auto-clear SAVE") get skipped.

Files (in ~/.onecommand/brain, the schema brain-core and /oc-resume use):
  working_memory.json   build state: phases_completed, current_phase, summaries, project_dir, plugin_root
  resume_brief.md       what /oc-resume reads to continue
  file_manifest.json    files on disk after the last phase
  checkpoints/          one snapshot per phase

Subcommands
-----------
start    begin a build (or keep the active one for the same project)
phase N  mark phase N complete:  --summary "..." [--status ok|warn|fail]
         Refused (exit 1) while a skill assigned to phase N was not loaded
         (skill-catalog.py check-read N) — unless --skills-skipped "<reason>".
finish   mark the build complete (phase 8 done)
status   print the current state

Exit codes: 0 ok · 1 state error · 2 usage error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

BRAIN = Path.home() / ".onecommand" / "brain"
WM_PATH = BRAIN / "working_memory.json"
PHASES = {
    1: "Spec + acceptance criteria + skill plan",
    2: "Build (frontend, backend, mobile / game / os)",
    3: "Integration + live integrations + marketing",
    4: "Quality gate + acceptance tests + self-healing",
    5: "Automations (CI, git hooks, Makefile)",
    6: "Quality pass (exceed, security, demo cleanup, store readiness) + regression gate",
    7: "Self-improvement + brain reflection",
    8: "Delivery report",
}
SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", "__pycache__", ".dart_tool",
             ".gradle", "Pods", "test-results", "playwright-report", ".onecommand", ".turbo", "coverage"}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def load_wm() -> dict[str, Any] | None:
    try:
        data = json.loads(WM_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except ValueError as exc:
        raise SystemExit(f"[checkpoint] {WM_PATH} is not valid JSON: {exc}") from None


def read_spec(project: Path) -> dict[str, Any]:
    try:
        return json.loads((project / ".onecommand-spec.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_active(wm: dict[str, Any] | None) -> bool:
    return bool(wm) and not wm.get("finished_at") and 8 not in (wm.get("phases_completed") or [])


def new_wm(project: Path, oc_root: str | None) -> dict[str, Any]:
    spec = read_spec(project)
    now = datetime.now()
    return {
        "build_id": f"build_{now.strftime('%Y%m%d_%H%M%S')}",
        "project_name": spec.get("project_name", project.name),
        "app_type": spec.get("app_type", "unknown"),
        "features": spec.get("features", []),
        "started_at": now.isoformat(timespec="seconds"),
        "project_dir": str(project),
        "plugin_root": oc_root or "",
        "current_phase": 1,
        "phases_completed": [],
        "phase_summaries": {},
        "phase_status": {},
        "files_created": [],
        "errors_log": [],
        "decisions_made": {},
        "patterns_applied": [],
        "context_compression_count": 0,
    }


def manifest(project: Path) -> list[str]:
    files = []
    for root, dirs, names in os.walk(project):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for n in names:
            if not n.startswith("."):
                files.append(str(Path(root, n).relative_to(project)))
    return sorted(files)


def gate_line(project: Path) -> str:
    try:
        r = json.loads((project / ".onecommand" / "gate" / "result.json").read_text())
    except (OSError, ValueError):
        return "not run yet"
    acc = r.get("acceptance") or {}
    verdict = "PASSED" if r.get("passed") else ("N/A" if r.get("not_applicable") else "FAILED")
    extra = f", acceptance {acc.get('blocking_passed')}/{acc.get('blocking')}" if acc else ""
    failed = f", failing: {', '.join(r.get('failed_steps') or [])}" if not r.get("passed") else ""
    return f"{verdict} (stage {r.get('stage')}{extra}{failed})"


def resume_brief(wm: dict[str, Any], project: Path) -> str:
    done = sorted(wm.get("phases_completed") or [])
    nxt = wm.get("current_phase", 1)
    lines = [
        "# OneCommand — Resume Brief",
        f"**Generated:** {datetime.now().isoformat(timespec='seconds')}",
        f"**Build ID:** {wm.get('build_id')}",
        f"**Status:** {'complete' if nxt > 8 else f'Phase {max(done) if done else 0} complete — NEXT: Phase {nxt}'}",
        "",
        "## Project",
        f"- **Name:** {wm.get('project_name')}",
        f"- **Type:** {wm.get('app_type')}",
        f"- **Location (PROJECT_DIR):** {project}",
        f"- **Plugin root (OC_ROOT):** {wm.get('plugin_root') or 'resolve as in pre-flight step 4'}",
        f"- **Quality gate:** {gate_line(project)}",
        "",
        "## Completed Phases",
    ]
    for p in done:
        status = wm.get("phase_status", {}).get(str(p), "ok")
        mark = {"ok": "✅", "warn": "⚠️", "fail": "❌"}.get(status, "✅")
        lines.append(f"- {mark} **Phase {p}:** {wm.get('phase_summaries', {}).get(str(p), PHASES.get(p, ''))}")
    if nxt <= 8:
        lines += ["", f"## Remaining Phases (continue from Phase {nxt})"]
        lines += [f"- ⏳ **Phase {p}:** {PHASES[p]}" for p in range(nxt, 9)]
    lines += [
        "",
        "## Rules for the resumed run",
        "- Do not repeat completed phases or regenerate files that exist (see file_manifest.json).",
        "- Read `.onecommand-spec.json` and `.onecommand/skill-plan.md` in PROJECT_DIR before continuing.",
        "- Dispatch phase agents in the foreground (`run_in_background: false`) and checkpoint after each phase.",
    ]
    return "\n".join(lines) + "\n"


def persist(wm: dict[str, Any], project: Path, label: str) -> None:
    files = manifest(project)
    wm["files_created"] = files[:2000]
    wm["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(WM_PATH, wm)
    write_json(BRAIN / "file_manifest.json", {"files": files, "count": len(files), "project_dir": str(project)})
    (BRAIN / "resume_brief.md").write_text(resume_brief(wm, project), encoding="utf-8")
    write_json(BRAIN / "checkpoints" / f"{wm['build_id']}-{label}.json", wm)


# ─── commands ─────────────────────────────────────────────────────────────────

def project_of(args: argparse.Namespace) -> Path:
    return Path(args.project_dir).expanduser().resolve()


def cmd_start(args: argparse.Namespace) -> int:
    project = project_of(args)
    wm = load_wm()
    if is_active(wm) and Path(wm.get("project_dir", "")) == project and not args.new:
        if args.oc_root and not wm.get("plugin_root"):
            wm["plugin_root"] = args.oc_root
        persist(wm, project, "start")
        print(f"[checkpoint] continuing build {wm['build_id']} — next phase {wm['current_phase']}")
        return 0
    if is_active(wm) and Path(wm.get("project_dir", "")) != project:
        print(f"[checkpoint] note: unfinished build {wm.get('build_id')} in {wm.get('project_dir')} is replaced")
    wm = new_wm(project, args.oc_root)
    persist(wm, project, "start")
    print(f"[checkpoint] build {wm['build_id']} started for {wm['project_name']} in {project}")
    return 0


def skills_loaded(project: Path, n: int) -> tuple[bool, str]:
    """skill-catalog.py check-read N — only when the build has a skill catalog."""
    if not (project / ".onecommand" / "skills-catalog.json").exists():
        return True, ""
    import subprocess
    script = Path(__file__).resolve().parent / "skill-catalog.py"
    r = subprocess.run([sys.executable, str(script), "--project-dir", str(project), "check-read", str(n)],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def cmd_phase(args: argparse.Namespace) -> int:
    project = project_of(args)
    ok, report = skills_loaded(project, args.n)
    if not ok and not args.skills_skipped:
        print(report)
        print(f"[checkpoint] ✗ Phase {args.n} NOT saved — the skills above were assigned but never loaded. "
              "Re-dispatch the owning agent to load and apply them, then run this checkpoint again "
              "(or pass --skills-skipped \"<reason>\" if a skill truly does not apply).")
        return 1
    wm = load_wm()
    if not is_active(wm) or Path(wm.get("project_dir", "")) != project:
        wm = new_wm(project, args.oc_root)  # robust: a forgotten `start` must not lose the checkpoint
    if args.oc_root:
        wm["plugin_root"] = args.oc_root
    spec = read_spec(project)
    for key in ("project_name", "app_type", "features"):
        if spec.get(key) and wm.get(key) in (None, "unknown", [], project.name):
            wm[key] = spec[key]
    done = set(wm.get("phases_completed") or [])
    done.update(range(1, args.n))  # phases before N are complete by definition
    done.add(args.n)
    wm["phases_completed"] = sorted(done)
    wm["current_phase"] = args.n + 1
    wm.setdefault("phase_summaries", {})[str(args.n)] = args.summary
    wm.setdefault("phase_status", {})[str(args.n)] = args.status
    if not ok:
        wm.setdefault("skills_skipped", {})[str(args.n)] = args.skills_skipped
    if args.n == 8:
        wm["finished_at"] = datetime.now().isoformat(timespec="seconds")
    persist(wm, project, f"phase{args.n}")
    nxt = "build complete" if args.n == 8 else f"next: Phase {args.n + 1}"
    print(f"[checkpoint] ✓ Phase {args.n} saved ({args.status}) — {nxt} · resumable with /oc-resume")
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    args.n, args.status = 8, args.status or "ok"
    args.skills_skipped = getattr(args, "skills_skipped", None)
    args.summary = args.summary or "Delivery report written"
    return cmd_phase(args)


def cmd_status(args: argparse.Namespace) -> int:
    wm = load_wm()
    if not wm:
        print("[checkpoint] no build recorded")
        return 0
    state = "active" if is_active(wm) else "finished"
    print(f"[checkpoint] {wm.get('build_id')} · {wm.get('project_name')} · {state} · "
          f"done {wm.get('phases_completed')} · next {wm.get('current_phase')} · {wm.get('project_dir')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--oc-root", help="plugin root, stored for /oc-resume")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("start", help="begin (or continue) a build")
    p.add_argument("--new", action="store_true", help="always start a new build")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("phase", help="mark a phase complete")
    p.add_argument("n", type=int, choices=list(PHASES))
    p.add_argument("--summary", required=True)
    p.add_argument("--status", choices=("ok", "warn", "fail"), default="ok")
    p.add_argument("--skills-skipped", help="save although check-read fails; the reason is recorded")
    p.set_defaults(func=cmd_phase)

    p = sub.add_parser("finish", help="mark the build complete")
    p.add_argument("--summary")
    p.add_argument("--status", choices=("ok", "warn", "fail"))
    p.set_defaults(func=cmd_finish)

    p = sub.add_parser("status", help="print the current state")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
