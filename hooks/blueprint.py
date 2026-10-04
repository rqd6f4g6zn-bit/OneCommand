#!/usr/bin/env python3
"""OneCommand domain blueprints.

A one-line prompt like "CRM auf höchstem Niveau" should produce what a
professional expects from a CRM — contacts, companies, pipeline, activities,
roles, reports, imports, GDPR … — without the user listing every feature.
Blueprints (skills/domain-blueprints/blueprints/*.json) hold that domain
knowledge as data: modules with features and concrete acceptance criteria,
entities, roles and pages, tiered mvp ⊂ pro ⊂ enterprise.

Subcommands
-----------
list     Show the available blueprints.
detect   Match a prompt to blueprints and choose the tier from its wording.
show     Print the modules of a blueprint up to a tier.
expand   Write a draft spec (features, pages, entities, roles, metrics, demo
         logins, acceptance criteria with ids, production dependencies) for
         spec-analyzer to adapt.
check    Verify a spec still covers its blueprint: every module of the tier is a
         feature (or explicitly excluded with a reason), every blueprint
         criterion is still present (matched by its "source" tag) and every
         blueprint metric is still defined.

Exit codes: 0 ok · 1 check failed / nothing detected · 2 usage error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT_DIR = ROOT / "skills" / "domain-blueprints" / "blueprints"
TIERS = ("mvp", "pro", "enterprise")

# Wording that selects a tier. Checked enterprise first: "höchstes Niveau" beats "einfach".
TIER_WORDS = {
    "enterprise": ["höchstem niveau", "höchsten niveau", "höchstes niveau", "hoechstem niveau", "höstem", "hösterm",
                   "enterprise", "konzern", "wie salesforce", "wie hubspot", "wie sap", "alle funktionen",
                   "auf max", "maximal", "top-niveau", "top niveau", "high-end", "mandantenfähig", "mandanten",
                   "skalierbar für", "profi-niveau", "auf profi", "100k", "100 k", "100.000", "premium",
                   "agenturniveau", "agentur-niveau", "award", "awwwards", "luxus"],
    # Not plain "einfach": "einfach zu bedienen" describes usability, not scope.
    "mvp": ["mvp", "prototyp", "prototype", "minimal", "basic", "nur das nötigste", "erste version",
            "einfache version", "einfaches crm", "kleine version", "schlanke version"],
}


def load(blueprint_id: str) -> dict[str, Any]:
    path = BLUEPRINT_DIR / f"{blueprint_id}.json"
    if not path.exists():
        known = ", ".join(sorted(p.stem for p in BLUEPRINT_DIR.glob("*.json")))
        raise SystemExit(f"[blueprint] unknown blueprint '{blueprint_id}' — known: {known}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"[blueprint] {path} is not valid JSON: {exc}") from None


def all_blueprints() -> list[dict[str, Any]]:
    return [load(p.stem) for p in sorted(BLUEPRINT_DIR.glob("*.json"))]


def upto(tier: str) -> tuple[str, ...]:
    return TIERS[: TIERS.index(tier) + 1]


def in_tier(item: dict[str, Any], tier: str, default: str = "mvp") -> bool:
    return item.get("tier", default) in upto(tier)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


# ─── detect ───────────────────────────────────────────────────────────────────

def detect(prompt: str) -> dict[str, Any]:
    text = f" {norm(prompt)} "
    matches = []
    for bp in all_blueprints():
        hits = [a for a in bp["aliases"] if re.search(rf"(?<![a-zäöüß]){re.escape(a.lower())}(?![a-zäöüß])", text)]
        if hits:
            matches.append({"id": bp["id"], "name": bp["name"], "score": len(hits), "matched": hits})
    matches.sort(key=lambda m: m["score"], reverse=True)
    tier, reason = "pro", "default — no tier wording in the prompt"
    for candidate in ("enterprise", "mvp"):
        words = [w for w in TIER_WORDS[candidate] if w in text]
        if words:
            tier, reason = candidate, f"prompt says: {', '.join(words)}"
            break
    return {"matches": matches, "tier": tier, "tier_reason": reason}


def cmd_detect(args: argparse.Namespace) -> int:
    result = detect(args.prompt)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if not result["matches"]:
            print("[blueprint] no blueprint matches — spec-analyzer derives features from the prompt alone")
        for m in result["matches"]:
            print(f"[blueprint] {m['id']} ({m['name']}) — matched: {', '.join(m['matched'])}")
        print(f"[blueprint] tier: {result['tier']} ({result['tier_reason']})")
    return 0 if result["matches"] else 1


# ─── show / list ──────────────────────────────────────────────────────────────

def cmd_list(args: argparse.Namespace) -> int:
    for bp in all_blueprints():
        counts = {t: sum(1 for m in bp["modules"] if m["tier"] == t) for t in TIERS}
        print(f"{bp['id']:<18} {bp['name']}  ·  modules mvp {counts['mvp']} / pro +{counts['pro']} / "
              f"enterprise +{counts['enterprise']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    bp = load(args.id)
    print(f"{bp['name']} — tier {args.tier}\n{bp['summary']}\n")
    for m in bp["modules"]:
        if in_tier(m, args.tier):
            print(f"[{m['tier']}] {m['id']}: {m['name']} — {len(m['criteria'])} criteria")
            for f in m["features"]:
                print(f"    · {f}")
    return 0


# ─── expand ───────────────────────────────────────────────────────────────────

def expand(bp: dict[str, Any], tier: str, exclude: dict[str, str], project_name: str | None) -> dict[str, Any]:
    modules = [m for m in bp["modules"] if in_tier(m, tier) and m["id"] not in exclude]
    criteria = []
    for m in modules:
        for i, c in enumerate(m["criteria"]):
            crit = {"id": f"AC-{len(criteria) + 1:03d}", "feature": m["id"], "priority": c.get("priority", "must"),
                    "source": f"blueprint:{bp['id']}/{m['id']}/{i}"}
            crit.update({k: v for k, v in c.items() if k != "priority"})
            criteria.append(crit)
    pages = [p for t in upto(tier) for p in bp.get("pages", {}).get(t, [])]
    roles = [r for r in bp.get("roles", []) if in_tier(r, tier)]
    metrics = [{k: v for k, v in m.items() if k != "tier"} for m in bp.get("metrics", []) if in_tier(m, tier)]
    login = next((p for p in pages if "login" in p), None)
    extra: dict[str, Any] = {}
    if bp.get("performance_budget", {}).get(tier):
        extra["performance_budget"] = bp["performance_budget"][tier]
    if bp.get("voice"):
        voice = {k: v for k, v in bp["voice"].items() if k != "intents"}
        voice["intents"] = [i for t in upto(tier) for i in bp["voice"].get("intents", {}).get(t, [])]
        extra["voice"] = voice
    videos = [v for t in upto(tier) for v in bp.get("media", {}).get(t, [])]
    if videos:
        extra["media"] = {"videos": videos, "raw_dir": "assets/raw"}
    return {
        "project_name": project_name or bp["id"].upper(),
        "app_type": bp.get("app_type", "web-app"),
        "build_targets": bp.get("build_targets", ["web"]),
        "ui_language": bp.get("ui_language", "en"),
        "blueprint": {"id": bp["id"], "version": bp.get("version", 1), "tier": tier, "excluded_modules": exclude},
        "features": [m["id"] for m in modules],
        "module_features": {m["id"]: m["features"] for m in modules},
        "pages": pages,
        "db_schema": [e["name"] for e in bp.get("entities", []) if in_tier(e, tier)],
        "entities": [e for e in bp.get("entities", []) if in_tier(e, tier)],
        "roles": roles,
        "non_functional": [n["text"] for n in bp.get("non_functional", []) if in_tier(n, tier)],
        "metrics": metrics,
        # One demo login per role; the full demo seed gives each of them data on every page (ui-tour checks it).
        "demo": {
            "seed_command": "npm run db:seed",
            "login_path": login,
            "accounts": [{"role": r["id"], "email": f"{r['id']}@demo.example", "password": "Demo1234!"} for r in roles],
        },
        "production_dependencies": bp.get("production_dependencies", {}).get(tier, []),
        "acceptance_criteria": criteria,
        **extra,
    }


def parse_excludes(values: list[str]) -> dict[str, str]:
    result = {}
    for v in values:
        module, _, reason = v.partition("=")
        if not reason.strip():
            raise SystemExit(f"[blueprint] --exclude needs a reason: {module}=<why> (got '{v}')")
        result[module.strip()] = reason.strip()
    return result


def cmd_expand(args: argparse.Namespace) -> int:
    bp = load(args.id)
    exclude = parse_excludes(args.exclude)
    unknown = sorted(set(exclude) - {m["id"] for m in bp["modules"]})
    if unknown:
        print(f"[blueprint] unknown module(s) to exclude: {', '.join(unknown)}", file=sys.stderr)
        return 2
    draft = expand(bp, args.tier, exclude, args.project_name)
    out = json.dumps(draft, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"[blueprint] {bp['id']} ({args.tier}): {len(draft['features'])} modules, "
              f"{len(draft['acceptance_criteria'])} acceptance criteria, {len(draft['db_schema'])} entities → {args.out}")
    else:
        print(out, end="")
    return 0


# ─── check ────────────────────────────────────────────────────────────────────

def check(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    ref = spec.get("blueprint")
    if not ref:
        return errors, ["spec has no blueprint — nothing to check"]
    bp = load(ref["id"])
    tier = ref.get("tier", "pro")
    if tier not in TIERS:
        return [f"blueprint tier '{tier}' is not one of {TIERS}"], notes
    excluded = ref.get("excluded_modules") or {}
    if isinstance(excluded, list):
        errors.append("blueprint.excluded_modules must map module → reason")
        excluded = {}
    features = set(spec.get("features") or [])
    criteria = spec.get("acceptance_criteria") or []
    sources = {c.get("source") for c in criteria if isinstance(c, dict)}
    for module in (m for m in bp["modules"] if in_tier(m, tier)):
        mid = module["id"]
        if mid in excluded:
            if not str(excluded[mid]).strip():
                errors.append(f"module '{mid}' excluded without a reason")
            else:
                notes.append(f"module '{mid}' excluded: {excluded[mid]}")
            continue
        if mid not in features:
            errors.append(f"module '{mid}' ({module['name']}, {module['tier']}) is missing from features "
                          f"— add it or exclude it with a reason")
            continue
        for i, _ in enumerate(module["criteria"]):
            source = f"blueprint:{bp['id']}/{mid}/{i}"
            if source not in sources:
                errors.append(f"criterion {source} ({module['criteria'][i]['title'][:70]}) was dropped "
                              f"— keep it (wording may change, the 'source' tag must stay)")
        if not any(c.get("feature") == mid and c.get("priority") == "must" for c in criteria if isinstance(c, dict)):
            errors.append(f"module '{mid}' has no must-criterion")
    have = {m.get("id") for m in spec.get("metrics") or [] if isinstance(m, dict)}
    for metric in (m for m in bp.get("metrics", []) if in_tier(m, tier)):
        if metric["id"] not in have:
            errors.append(f"metric '{metric['id']}' ({metric['label']}) was dropped from spec.metrics — keep its "
                          f"definition and period so every page computes and labels it the same way")
    return errors, notes


def cmd_check(args: argparse.Namespace) -> int:
    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[blueprint] cannot read spec {args.spec}: {exc}", file=sys.stderr)
        return 2
    errors, notes = check(spec)
    for n in notes:
        print(f"  ○ {n}")
    for e in errors:
        print(f"  ✗ {e}")
    if errors:
        print(f"[blueprint] spec does NOT cover its blueprint — {len(errors)} problem(s)")
        return 1
    ref = spec.get("blueprint")
    if ref:
        print(f"[blueprint] spec covers {ref['id']} ({ref.get('tier')}) — {len(spec.get('features') or [])} modules, "
              f"{len(spec.get('acceptance_criteria') or [])} criteria")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    p = sub.add_parser("detect")
    p.add_argument("--prompt", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("show")
    p.add_argument("id")
    p.add_argument("--tier", choices=TIERS, default="pro")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("expand")
    p.add_argument("id")
    p.add_argument("--tier", choices=TIERS, default="pro")
    p.add_argument("--project-name")
    p.add_argument("--exclude", action="append", default=[], metavar="MODULE=REASON",
                   help="leave a module out (the user asked for it); the reason is kept in the spec")
    p.add_argument("--out", help="write the draft spec here (default: stdout)")
    p.set_defaults(func=cmd_expand)

    p = sub.add_parser("check")
    p.add_argument("--spec", default=".onecommand-spec.json")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
