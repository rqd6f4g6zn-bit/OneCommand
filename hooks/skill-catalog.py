#!/usr/bin/env python3
"""OneCommand skill catalog.

Makes sure a build takes EVERY available skill into account — OneCommand's own
bundled skills as well as skills the user has installed elsewhere (personal
skills, project skills, other enabled plugins such as superpowers or
marketing-skills).

Subcommands
-----------
scan       Discover all skills and write <project>/.onecommand/skills-catalog.json.
           Bundled skills are mapped to phases deterministically (from the spec's
           build targets); every external skill starts as "undecided".
check      Merge the orchestrator's decisions (.onecommand/skill-plan.json) into
           the catalog. Fails while any skill is undecided, any decision is
           malformed, or a bundled skill has no phase mapping.
for-phase  Print the skills a phase must use (name, how to load it, why) — pasted
           into every phase subagent prompt.
show       Print the catalog grouped by status.

Decisions file (.onecommand/skill-plan.json), written by the orchestrator:
  {"decisions": [
     {"skill": "superpowers:frontend-design", "phases": [2], "use": "layout + visual polish"},
     {"skill": "pdf", "phases": [], "reason": "no PDF handling in this project"}
  ]}

Exit codes: 0 ok · 1 check failed · 2 usage / input error
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("skill-catalog")
PHASES = range(1, 9)
PHASE_NAMES = {
    1: "Spec", 2: "Build", 3: "Integration + Marketing", 4: "Quality Gate",
    5: "Automations", 6: "Exceed + Security", 7: "Self-Improvement", 8: "Delivery",
}

# Every bundled skill must appear here. "when" decides applicability from the spec:
#   always · web · mobile · game · os · setup (never inside a build) · support (used by
#   /oc-resume, /oc-save and the orchestrator itself, never handed to phase agents)
BUNDLED: dict[str, dict[str, Any]] = {
    "spec-analyzer":           {"phases": [1], "when": "always", "use": "prompt → spec with acceptance criteria"},
    "stack-detector":          {"phases": [1], "when": "always", "use": "confirm or detect the tech stack"},
    "brain-core":              {"phases": [1, 7], "when": "always", "use": "memory recall at start, reflection at end (via brain-agent)"},
    "context-manager":         {"phases": [], "when": "support", "use": "context compression helpers — checkpoints are written by hooks/checkpoint.py"},
    "auto-clear":              {"phases": [], "when": "support", "use": "RESUME mode for /oc-resume and /onecommand --resume"},
    "collab-protocol":         {"phases": [1, 2], "when": "always", "use": "Claude/Codex task split; claude-only fallback"},
    "cross-agent-sync":        {"phases": [1, 7], "when": "always", "use": "load shared learnings, promote confirmed ones"},
    "oc-frontend-design":      {"phases": [2], "when": "web", "use": "layout, typography, spacing rules"},
    "oc-ui-ux":                {"phases": [2], "when": "web", "use": "UX patterns and accessibility"},
    "21st-components":         {"phases": [2, 3], "when": "web", "use": "community UI sections before custom code"},
    "app-icon-generator":      {"phases": [2], "when": "mobile", "use": "app icons in every iOS/Android size"},
    "game-engine-selector":    {"phases": [2], "when": "game", "use": "choose Godot / Three.js / Phaser"},
    "godot-builder":           {"phases": [2], "when": "game", "use": "Godot 4 project (if selected)"},
    "threejs-builder":         {"phases": [2], "when": "game", "use": "Three.js project (if selected)"},
    "phaser-builder":          {"phases": [2], "when": "game", "use": "Phaser 3 project (if selected)"},
    "asset-generator":         {"phases": [2], "when": "game", "use": "sprites, models, audio"},
    "os-builder":              {"phases": [2], "when": "os", "use": "custom Linux OS build"},
    "live-integrations":       {"phases": [3], "when": "web", "use": "real e-mail, OAuth, push for production_dependencies"},
    "oc-marketing":            {"phases": [3], "when": "always", "use": "README, landing page, docs (via marketing-agent)"},
    "acceptance-tester":       {"phases": [4, 6], "when": "web", "use": "Playwright suite from acceptance_criteria"},
    "self-healer":             {"phases": [4, 6], "when": "always", "use": "fix gate failures, record learnings"},
    "automation-installer":    {"phases": [5], "when": "always", "use": "CI, git hooks, Makefile"},
    "exceed-expectations":     {"phases": [6], "when": "web", "use": "dark mode, PWA, a11y, error boundaries"},
    "demo-cleaner":            {"phases": [6], "when": "always", "use": "remove placeholder/demo content"},
    "store-readiness-checker": {"phases": [6], "when": "mobile", "use": "App Store / Play Store requirements"},
    "delivery-reporter":       {"phases": [8], "when": "always", "use": "ONECOMMAND-DELIVERY.md from gate results"},
    "codex-setup":             {"phases": [], "when": "setup", "use": "interactive Codex installation — recommended in pre-flight when Codex is missing, never run inside a build"},
}


# ─── helpers ──────────────────────────────────────────────────────────────────

def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except ValueError as exc:
        raise SystemExit(f"[skills] {path} is not valid JSON: {exc}") from None


def parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML front-matter reader: key: value, quoted values, | and > blocks."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict[str, str] = {}
    lines = text[3:end].strip("\n").splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", lines[i])
        i += 1
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if value in ("|", ">", "|-", ">-", "|+", ">+"):
            block = []
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            value = (" " if value.startswith(">") else "\n").join(b for b in block if b)
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key] = value
    return meta


def skill_entry(skill_md: Path, source: str, prefix: str | None) -> dict[str, Any] | None:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        LOG.warning("cannot read %s: %s", skill_md, exc)
        return None
    meta = parse_frontmatter(text)
    base = meta.get("name") or skill_md.parent.name
    name = f"{prefix}:{base}" if prefix else base
    return {
        "name": name,
        "base_name": base,
        "description": re.sub(r"\s+", " ", meta.get("description", "")).strip()[:400],
        "source": source,
        "path": str(skill_md),
    }


def skills_in(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*/SKILL.md") if p.is_file())


# ─── discovery ────────────────────────────────────────────────────────────────

def enabled_plugins(home: Path) -> list[tuple[str, Path]]:
    """(plugin name, install path) for every plugin that is installed AND enabled."""
    settings = read_json(home / ".claude" / "settings.json", {}) or {}
    enabled = {k for k, v in (settings.get("enabledPlugins") or {}).items() if v}
    registry = read_json(home / ".claude" / "plugins" / "installed_plugins.json", {}) or {}
    found = []
    for key, entries in (registry.get("plugins") or {}).items():
        if key not in enabled or not entries:
            continue
        entry = entries[0] if isinstance(entries, list) else entries
        path = entry.get("installPath") if isinstance(entry, dict) else None
        if path:
            found.append((key.split("@")[0], Path(path).expanduser()))
    return found


def discover(oc_root: Path, project_dir: Path, home: Path, extra_plugin_dirs: list[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add(skill_md: Path, source: str, prefix: str | None = None) -> None:
        real = str(skill_md.resolve())
        if real in seen_paths:
            return
        seen_paths.add(real)
        entry = skill_entry(skill_md, source, prefix)
        if entry:
            entries.append(entry)

    for p in skills_in(oc_root / "skills"):
        add(p, "bundled")
    for p in skills_in(project_dir / ".claude" / "skills"):
        add(p, "project")
    for p in skills_in(home / ".claude" / "skills"):
        add(p, "user")
    plugin_dirs = [(name, path) for name, path in enabled_plugins(home)]
    plugin_dirs += [(d.name, d) for d in extra_plugin_dirs]
    for name, path in plugin_dirs:
        if path.resolve() == oc_root.resolve() or name == "onecommand":
            continue
        for p in skills_in(path / "skills"):
            add(p, f"plugin:{name}", prefix=name)

    # A personal/project skill with the same name as a bundled one shadows nothing —
    # both stay visible, but flag it so the orchestrator knows which one is OneCommand's.
    bundled_names = {e["name"] for e in entries if e["source"] == "bundled"}
    for e in entries:
        if e["source"] != "bundled" and e["base_name"] in bundled_names:
            e["note"] = f"same name as bundled skill '{e['base_name']}'"
    return entries


def spec_targets(spec: dict[str, Any]) -> set[str]:
    targets = set(spec.get("build_targets") or [])
    app_type = spec.get("app_type")
    if app_type in ("game", "os"):
        targets.add(app_type)
    if not targets:
        targets.add("web")
    return targets


def resolve_bundled(entry: dict[str, Any], targets: set[str]) -> None:
    rule = BUNDLED.get(entry["name"])
    if rule is None:
        entry.update(status="unmapped", phases=[], use="",
                     reason="bundled skill missing from BUNDLED in hooks/skill-catalog.py")
        return
    when = rule["when"]
    if when == "setup":
        entry.update(status="not_used", phases=[], use=rule["use"], reason="setup-time skill, not part of a build")
    elif when == "support":
        entry.update(status="not_used", phases=[], use=rule["use"],
                     reason="infrastructure skill used by /oc-resume and /oc-save, not by phase agents")
    elif when == "always" or when in targets:
        entry.update(status="assigned", phases=rule["phases"], use=rule["use"])
    else:
        entry.update(status="not_used", phases=[], use=rule["use"],
                     reason=f"only for '{when}' builds (targets: {', '.join(sorted(targets))})")


# ─── commands ─────────────────────────────────────────────────────────────────

def paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    project = Path(args.project_dir).expanduser().resolve()
    state = project / ".onecommand"
    return project, state / "skills-catalog.json", state / "skill-plan.json"


def cmd_scan(args: argparse.Namespace) -> int:
    project, catalog_path, _ = paths(args)
    oc_root = Path(args.oc_root).expanduser().resolve()
    if not (oc_root / "skills").is_dir():
        print(f"[skills] OC_ROOT has no skills/ directory: {oc_root}", file=sys.stderr)
        return 2
    spec = read_json(project / args.spec, {}) or {}
    targets = spec_targets(spec)
    entries = discover(oc_root, project, Path(args.home).expanduser(), [Path(d).expanduser() for d in args.plugin_dir])
    for e in entries:
        if e["source"] == "bundled":
            resolve_bundled(e, targets)
        else:
            e.update(status="undecided", phases=[], use="")
    missing = sorted(set(BUNDLED) - {e["name"] for e in entries if e["source"] == "bundled"})
    catalog = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "oc_root": str(oc_root),
        "build_targets": sorted(targets),
        "skills": entries,
        "bundled_missing_on_disk": missing,
    }
    write_atomic(catalog_path, json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    external = [e for e in entries if e["source"] != "bundled"]
    by_status: dict[str, int] = {}
    for e in entries:
        by_status[e["status"]] = by_status.get(e["status"], 0) + 1
    print(f"[skills] {len(entries)} skills found ({len(entries) - len(external)} bundled, {len(external)} external) "
          f"· targets: {', '.join(sorted(targets))} · " + ", ".join(f"{k}: {v}" for k, v in sorted(by_status.items())))
    if external:
        print("[skills] external skills needing a decision (phases + use, or reason):")
        for e in external:
            note = f"  [{e['note']}]" if e.get("note") else ""
            print(f"  - {e['name']} ({e['source']}): {e['description'][:160]}{note}")
    if missing:
        print(f"[skills] ⚠ mapped but not on disk: {', '.join(missing)}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    project, catalog_path, plan_path = paths(args)
    catalog = read_json(catalog_path)
    if catalog is None:
        print(f"[skills] no catalog at {catalog_path} — run 'scan' first", file=sys.stderr)
        return 2
    plan = read_json(plan_path, {"decisions": []}) or {"decisions": []}
    decisions = plan.get("decisions") if isinstance(plan, dict) else None
    if not isinstance(decisions, list):
        print(f"[skills] {plan_path} must contain {{\"decisions\": [...]}}", file=sys.stderr)
        return 2

    by_name = {e["name"]: e for e in catalog["skills"]}
    errors: list[str] = []
    seen: set[str] = set()
    for i, d in enumerate(decisions):
        where = f"decisions[{i}]"
        if not isinstance(d, dict) or not d.get("skill"):
            errors.append(f"{where}: needs a 'skill' field")
            continue
        name = d["skill"]
        if name in seen:
            errors.append(f"{name}: decided twice")
        seen.add(name)
        entry = by_name.get(name)
        if entry is None:
            errors.append(f"{name}: not in the catalog (typo? re-run scan?)")
            continue
        if entry["source"] == "bundled":
            errors.append(f"{name}: bundled skills are mapped automatically — remove this decision")
            continue
        phases = d.get("phases") or []
        if not isinstance(phases, list) or any(p not in PHASES for p in phases):
            errors.append(f"{name}: phases must be a list of numbers 1–8")
            continue
        if phases:
            if not str(d.get("use", "")).strip():
                errors.append(f"{name}: assigned to phases {phases} but 'use' (what it is used for) is empty")
                continue
            entry.update(status="assigned", phases=sorted(set(phases)), use=d["use"].strip())
        else:
            if not str(d.get("reason", "")).strip():
                errors.append(f"{name}: not used but no 'reason' given")
                continue
            entry.update(status="not_used", phases=[], reason=d["reason"].strip())

    for e in catalog["skills"]:
        if e["status"] == "undecided":
            errors.append(f"{e['name']} ({e['source']}): no decision yet")
        elif e["status"] == "unmapped":
            errors.append(f"{e['name']}: {e['reason']}")

    catalog["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    catalog["complete"] = not errors
    write_atomic(catalog_path, json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    write_atomic(catalog_path.with_name("skill-plan.md"), render_plan(catalog))

    assigned = sum(1 for e in catalog["skills"] if e["status"] == "assigned")
    not_used = sum(1 for e in catalog["skills"] if e["status"] == "not_used")
    if errors:
        for err in errors:
            print(f"  ✗ {err}")
        print(f"[skills] plan INCOMPLETE — {len(errors)} problem(s). Add decisions to {plan_path} and re-run check.")
        return 1
    print(f"[skills] plan complete — {assigned} skills assigned, {not_used} not used (with reason), "
          f"{len(catalog['skills'])} considered · {catalog_path.with_name('skill-plan.md')}")
    return 0


def render_plan(catalog: dict[str, Any]) -> str:
    lines = ["# Skill Plan", "", f"Build targets: {', '.join(catalog['build_targets'])} · "
             f"{len(catalog['skills'])} skills considered", ""]
    for phase in PHASES:
        rows = [e for e in catalog["skills"] if e["status"] == "assigned" and phase in e["phases"]]
        if rows:
            lines.append(f"## Phase {phase} — {PHASE_NAMES[phase]}")
            lines += [f"- **{e['name']}** ({e['source']}) — {e['use']}" for e in rows]
            lines.append("")
    rest = [e for e in catalog["skills"] if e["status"] != "assigned"]
    if rest:
        lines.append("## Not used in this build")
        lines += [f"- {e['name']} ({e['source']}) — {e.get('reason') or e['status']}" for e in rest]
    return "\n".join(lines) + "\n"


def cmd_for_phase(args: argparse.Namespace) -> int:
    _, catalog_path, _ = paths(args)
    catalog = read_json(catalog_path)
    if catalog is None:
        print(f"[skills] no catalog at {catalog_path} — run 'scan' and 'check' first", file=sys.stderr)
        return 2
    if not catalog.get("complete"):
        print("[skills] ⚠ skill plan not complete — run 'check' and resolve all decisions", file=sys.stderr)
    rows = [e for e in catalog["skills"] if e["status"] == "assigned" and args.phase in e["phases"]]
    print(f"SKILLS FOR PHASE {args.phase} ({PHASE_NAMES[args.phase]}) — read each SKILL.md and apply it:")
    if not rows:
        print("  (none)")
    for e in rows:
        print(f"  - {e['name']} [{e['source']}] — {e['use']}\n      {e['path']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    _, catalog_path, _ = paths(args)
    catalog = read_json(catalog_path)
    if catalog is None:
        print(f"[skills] no catalog at {catalog_path}", file=sys.stderr)
        return 2
    print(render_plan(catalog), end="")
    undecided = [e["name"] for e in catalog["skills"] if e["status"] in ("undecided", "unmapped")]
    if undecided:
        print(f"\nUndecided / unmapped: {', '.join(undecided)}")
    return 0


def cmd_verify_bundled(args: argparse.Namespace) -> int:
    """Used by install.sh: every bundled skill directory must have a phase mapping."""
    root = Path(args.oc_root).expanduser()
    on_disk = {p.parent.name for p in skills_in(root / "skills")}
    unmapped = sorted(on_disk - set(BUNDLED))
    stale = sorted(set(BUNDLED) - on_disk)
    for name in unmapped:
        print(f"unmapped: skills/{name} has no phase mapping in hooks/skill-catalog.py (BUNDLED)")
    for name in stale:
        print(f"stale: BUNDLED maps '{name}' but skills/{name}/SKILL.md does not exist")
    return 1 if unmapped or stale else 0


# ─── cli ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="discover all skills and write the catalog")
    p.add_argument("--oc-root", required=True, help="OneCommand plugin root")
    p.add_argument("--spec", default=".onecommand-spec.json", help="relative to --project-dir")
    p.add_argument("--home", default=str(Path.home()))
    p.add_argument("--plugin-dir", action="append", default=[],
                   help="extra plugin directory to scan (e.g. plugins loaded with claude --plugin-dir)")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("check", help="merge decisions and verify every skill is considered")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("for-phase", help="print the skills a phase must use")
    p.add_argument("phase", type=int, choices=list(PHASES))
    p.set_defaults(func=cmd_for_phase)

    p = sub.add_parser("show", help="print the plan")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("verify-bundled", help="every bundled skill has a phase mapping (install.sh)")
    p.add_argument("--oc-root", required=True)
    p.set_defaults(func=cmd_verify_bundled)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="[skills] %(levelname)s %(message)s")
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
