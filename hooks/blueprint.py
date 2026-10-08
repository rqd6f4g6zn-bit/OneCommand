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
         Without a blueprint, the spec must carry a domain_brief instead
         (business apps): roles, processes linked to features, legal rules,
         deadlines, integrations, glossary and a design direction — so an
         unknown domain (notary, tax office, …) is researched, not guessed.
brief    Print an empty domain_brief to fill in (no blueprint matched).

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
                   "auf max", "maximal", "top-niveau", "top niveau", "high-end", "mandantenfähig", "multi-mandanten",
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


DENSITIES = ("compact", "comfortable", "spacious")
NO_BRIEF_APP_TYPES = ("game", "os", "ml")


def design_problems(design: Any, where: str) -> list[str]:
    """A design direction seeds the build's design brief (skills/oc-frontend-design)."""
    if not isinstance(design, dict):
        return [f"{where}: design direction missing (personality, typefaces, palette, density, signature_ideas, references, avoid)"]
    errors = []
    if not (isinstance(design.get("personality"), list) and len(design["personality"]) >= 3):
        errors.append(f"{where}.personality: three adjectives")
    faces = design.get("typefaces")
    if not (isinstance(faces, dict) and str(faces.get("display", "")).strip() and str(faces.get("text", "")).strip()):
        errors.append(f"{where}.typefaces: display and text face")
    if not str(design.get("palette", "")).strip():
        errors.append(f"{where}.palette: brand hue and mood")
    if design.get("density") not in DENSITIES:
        errors.append(f"{where}.density: one of {', '.join(DENSITIES)}")
    for key, minimum in (("signature_ideas", 1), ("references", 2), ("avoid", 1)):
        if not (isinstance(design.get(key), list) and len(design[key]) >= minimum):
            errors.append(f"{where}.{key}: at least {minimum}")
    return errors


def brief_problems(spec: dict[str, Any]) -> list[str]:
    brief = spec.get("domain_brief")
    if not isinstance(brief, dict):
        return ["no blueprint matched and the spec has no domain_brief — research the domain first "
                "(blueprint.py brief prints the template): roles, processes, legal rules, deadlines, "
                "integrations, glossary, design"]
    errors: list[str] = []
    features = set(spec.get("features") or [])
    criteria = [c for c in spec.get("acceptance_criteria") or [] if isinstance(c, dict)]
    if not str(brief.get("domain", "")).strip():
        errors.append("domain_brief.domain: name the domain (e.g. 'Notariat')")
    roles = brief.get("roles") or []
    if len(roles) < 2 or not all(isinstance(r, dict) and r.get("name") and r.get("can") for r in roles):
        errors.append("domain_brief.roles: at least 2 roles with name and what they can do")
    processes = brief.get("processes") or []
    if len(processes) < 3:
        errors.append("domain_brief.processes: at least 3 core processes of the domain")
    for i, proc in enumerate(processes):
        if not isinstance(proc, dict) or not proc.get("name") or len(proc.get("steps") or []) < 3:
            errors.append(f"domain_brief.processes[{i}]: name and at least 3 steps")
            continue
        feature = proc.get("feature")
        if feature not in features:
            errors.append(f"process '{proc['name']}': feature '{feature}' is not in spec.features — every process is built")
        elif not any(c.get("feature") == feature and c.get("priority", "must") == "must" for c in criteria):
            errors.append(f"process '{proc['name']}': feature '{feature}' has no must-criterion")
    rules = brief.get("rules")
    if not isinstance(rules, list) or (not rules and not str(brief.get("rules_none_reason", "")).strip()):
        errors.append("domain_brief.rules: legal/regulatory duties with their source (§ …), or rules_none_reason")
    else:
        for i, r in enumerate(rules):
            if not (isinstance(r, dict) and r.get("rule") and r.get("source")):
                errors.append(f"domain_brief.rules[{i}]: rule and source")
    if not isinstance(brief.get("deadlines"), list):
        errors.append("domain_brief.deadlines: list (empty when the domain has none)")
    integ = brief.get("integrations")
    if not (isinstance(integ, dict) and all(isinstance(integ.get(k), list) for k in ("connectable", "export_only", "not_possible"))):
        errors.append("domain_brief.integrations: connectable, export_only and not_possible lists — say what the "
                      "app cannot connect to (closed official systems) instead of pretending")
    glossary = brief.get("glossary") or []
    if len(glossary) < 5:
        errors.append("domain_brief.glossary: at least 5 domain terms with meaning (UI wording uses them)")
    errors += design_problems(brief.get("design"), "domain_brief.design")
    return errors


def upto(tier: str) -> tuple[str, ...]:
    return TIERS[: TIERS.index(tier) + 1]


def in_tier(item: dict[str, Any], tier: str, default: str = "mvp") -> bool:
    return item.get("tier", default) in upto(tier)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


# ─── detect ───────────────────────────────────────────────────────────────────

# Words that ask for "the software of a business" — then an industry blueprint leads ("Software für unser
# Notariat"); without them a product blueprint leads and the industry adds context ("Webseite für unser
# Restaurant" is a website with a restaurant's look and duties, not a kitchen display).
SYSTEM_WORDS = ("software", "verwaltung", "system", "programm", "app", "plattform", "lösung", "branchensoftware",
                "komplettlösung", "alles")


def kind(bp: dict[str, Any]) -> str:
    return bp.get("kind", "product")


def detect(prompt: str) -> dict[str, Any]:
    text = f" {norm(prompt)} "
    matches = []
    for bp in all_blueprints():
        hits = [a for a in bp["aliases"] if re.search(rf"(?<![a-zäöüß]){re.escape(a.lower())}(?![a-zäöüß])", text)]
        if hits:
            matches.append({"id": bp["id"], "name": bp["name"], "kind": kind(bp), "score": len(hits), "matched": hits})
    matches.sort(key=lambda m: -m["score"])
    products = [m for m in matches if m["kind"] == "product"]
    industries = [m for m in matches if m["kind"] == "industry"]
    system_word = any(re.search(rf"(?<![a-zäöüß]){w}(?![a-zäöüß])", text) for w in SYSTEM_WORDS)
    plan: dict[str, Any] = {"primary": None, "with": [], "context": []}
    if industries and (system_word or not products):
        plan.update(primary=industries[0]["id"], with_=None)
        plan["with"] = [m["id"] for m in products[:2]]          # extra product modules (e.g. Telefon-KI)
        plan["context"] = [m["id"] for m in industries[1:2]]
    elif products:
        plan["primary"] = products[0]["id"]
        plan["with"] = [m["id"] for m in products[1:2]]
        plan["context"] = [m["id"] for m in industries[:1]]     # look, duties, terms of the industry
    plan.pop("with_", None)
    order = [plan["primary"], *plan["with"], *plan["context"]]
    matches.sort(key=lambda m: order.index(m["id"]) if m["id"] in order else len(order))
    tier, reason = "pro", "default — no tier wording in the prompt"
    for candidate in ("enterprise", "mvp"):
        words = [w for w in TIER_WORDS[candidate] if w in text]
        if words:
            tier, reason = candidate, f"prompt says: {', '.join(words)}"
            break
    return {"matches": matches, "plan": plan, "tier": tier, "tier_reason": reason}


def cmd_detect(args: argparse.Namespace) -> int:
    result = detect(args.prompt)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if not result["matches"]:
            print("[blueprint] no blueprint matches — spec-analyzer derives features from the prompt alone")
        for m in result["matches"]:
            print(f"[blueprint] {m['id']} ({m['name']}, {m['kind']}) — matched: {', '.join(m['matched'])}")
        plan = result["plan"]
        if plan["primary"]:
            flags = "".join(f" --with {w}" for w in plan["with"]) + "".join(f" --context {c}" for c in plan["context"])
            print(f"[blueprint] plan: expand {plan['primary']}{flags}")
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

def merged_modules(bp: dict[str, Any], tier: str, exclude: dict[str, str], taken: set[str]) -> list[dict[str, Any]]:
    """Modules of bp in the tier, minus excluded ones and ids another blueprint already supplies (auth …)."""
    return [m for m in bp["modules"] if in_tier(m, tier) and m["id"] not in exclude and m["id"] not in taken]


def unique(items: list[Any], key) -> list[Any]:
    seen, out = set(), []
    for item in items:
        k = key(item)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def expand(bp: dict[str, Any], tier: str, exclude: dict[str, str], project_name: str | None,
           with_bps: list[dict[str, Any]] | None = None, context_bps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    with_bps, context_bps = with_bps or [], context_bps or []
    parts: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    taken: set[str] = set()
    for b in [bp, *with_bps]:
        mods = merged_modules(b, tier, exclude if b is bp else {}, taken)
        taken |= {m["id"] for m in mods}
        parts.append((b, mods))
    modules = [m for _, mods in parts for m in mods]
    criteria = []
    for b, mods in parts:
        for m in mods:
            for i, c in enumerate(m["criteria"]):
                crit = {"id": f"AC-{len(criteria) + 1:03d}", "feature": m["id"], "priority": c.get("priority", "must"),
                        "source": f"blueprint:{b['id']}/{m['id']}/{i}"}
                crit.update({k: v for k, v in c.items() if k != "priority"})
                criteria.append(crit)
    sources = [bp, *with_bps]
    pages = unique([p for b in sources for t in upto(tier) for p in b.get("pages", {}).get(t, [])], key=lambda p: p)
    roles = unique([r for b in sources for r in b.get("roles", []) if in_tier(r, tier)], key=lambda r: r["id"])
    metrics = unique([{k: v for k, v in m.items() if k != "tier"} for b in sources for m in b.get("metrics", [])
                      if in_tier(m, tier)], key=lambda m: m["id"])
    # The industry decides the look and the duties, also when a product blueprint leads.
    industry = next((b for b in [bp, *with_bps, *context_bps] if kind(b) == "industry"), bp)
    entities = unique([e for b in sources for e in b.get("entities", []) if in_tier(e, tier)], key=lambda e: e["name"])
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
        "blueprint": {"id": bp["id"], "version": bp.get("version", 1), "tier": tier, "excluded_modules": exclude,
                      "with": [b["id"] for b in with_bps], "context": [b["id"] for b in context_bps]},
        "features": [m["id"] for m in modules],
        "module_features": {m["id"]: m["features"] for m in modules},
        "pages": pages,
        "db_schema": [e["name"] for e in entities],
        "entities": entities,
        "roles": roles,
        "non_functional": unique([n["text"] for b in sources for n in b.get("non_functional", []) if in_tier(n, tier)],
                                 key=lambda t: t),
        "metrics": metrics,
        # One demo login per role; the full demo seed gives each of them data on every page (ui-tour checks it).
        "demo": {
            "seed_command": "npm run db:seed",
            "login_path": login,
            "accounts": [{"role": r["id"], "email": f"{r['id']}@demo.example", "password": "Demo1234!"} for r in roles],
        },
        "production_dependencies": unique([d for b in sources for d in b.get("production_dependencies", {}).get(tier, [])],
                                          key=lambda d: d),
        # Seeds .onecommand/design.md (oc-frontend-design): adapt to the customer's brand, do not copy blindly.
        "design_direction": industry.get("design") or bp.get("design"),
        "compliance": unique([{k: v for k, v in r.items() if k != "tier"} for b in [*sources, *context_bps]
                              for r in b.get("compliance", []) if in_tier(r, tier)], key=lambda r: r["rule"]),
        "integrations": {k: unique([x for b in [*sources, *context_bps] for x in (b.get("integrations") or {}).get(k, [])],
                                   key=lambda x: x)
                         for k in ("connectable", "export_only", "not_possible")},
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
    with_bps = [load(i) for i in args.with_ if i != bp["id"]]
    context_bps = [load(i) for i in args.context if i != bp["id"]]
    draft = expand(bp, args.tier, exclude, args.project_name, with_bps, context_bps)
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
        targets = set(spec.get("build_targets") or [])
        if spec.get("app_type") in NO_BRIEF_APP_TYPES or (targets and targets <= {"ml"}):
            return errors, ["spec has no blueprint — game/os/ml builds need no domain brief"]
        return brief_problems(spec), ["spec has no blueprint — checked its domain_brief"]
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
    blueprints = [bp] + [load(i) for i in ref.get("with") or []]
    taken: set[str] = set()
    plan = []
    for b in blueprints:
        mods = [m for m in b["modules"] if in_tier(m, tier) and m["id"] not in taken]
        taken |= {m["id"] for m in mods}
        plan += [(b, m) for m in mods]
    for owner, module in plan:
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
            source = f"blueprint:{owner['id']}/{mid}/{i}"
            if source not in sources:
                errors.append(f"criterion {source} ({module['criteria'][i]['title'][:70]}) was dropped "
                              f"— keep it (wording may change, the 'source' tag must stay)")
        if not any(c.get("feature") == mid and c.get("priority") == "must" for c in criteria if isinstance(c, dict)):
            errors.append(f"module '{mid}' has no must-criterion")
    have = {m.get("id") for m in spec.get("metrics") or [] if isinstance(m, dict)}
    for metric in unique([m for b in blueprints for m in b.get("metrics", []) if in_tier(m, tier)], key=lambda m: m["id"]):
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
    if not ref and spec.get("domain_brief"):
        print(f"[blueprint] domain brief complete — {spec['domain_brief'].get('domain')}: "
              f"{len(spec['domain_brief'].get('processes') or [])} processes, "
              f"{len(spec['domain_brief'].get('rules') or [])} rules")
    if ref:
        print(f"[blueprint] spec covers {ref['id']} ({ref.get('tier')}) — {len(spec.get('features') or [])} modules, "
              f"{len(spec.get('acceptance_criteria') or [])} criteria")
    return 0


BRIEF_TEMPLATE = {
    "domain": "<Branche, z. B. Notariat>",
    "sources": ["<what the brief rests on: laws, professional rules, the customer's own words>"],
    "roles": [{"id": "<id>", "name": "<Rolle>", "can": "<was sie darf und tut>"}],
    "processes": [{"name": "<Kernprozess>", "feature": "<feature id in spec.features>",
                   "steps": ["<Schritt 1>", "<Schritt 2>", "<Schritt 3>"]}],
    "rules": [{"rule": "<Pflicht, die die Software erzwingen oder unterstützen muss>", "source": "<§ … Gesetz / Berufsordnung>"}],
    "deadlines": [{"what": "<Frist>", "when": "<Dauer / Auslöser>", "source": "<§ …>"}],
    "integrations": {"connectable": ["<Dienst mit offener API>"], "export_only": ["<System, das nur Export/Import erlaubt>"],
                     "not_possible": ["<geschlossenes System — Grund>"]},
    "glossary": [{"term": "<Fachbegriff>", "meaning": "<Bedeutung>"}],
    "to_verify": ["<Annahme, die der Kunde bestätigen muss>"],
    "design": {"personality": ["<adj>", "<adj>", "<adj>"], "typefaces": {"display": "<face>", "text": "<face>"},
               "palette": "<Markenton + Stimmung>", "density": "compact|comfortable|spacious",
               "signature_ideas": ["<Wiedererkennungsmerkmal mit Bedeutung>"], "references": ["<Produkt>", "<Produkt>"],
               "avoid": ["<was in dieser Branche billig oder unseriös wirkt>"]},
}


def cmd_brief(args: argparse.Namespace) -> int:
    print(json.dumps({"domain_brief": BRIEF_TEMPLATE}, indent=2, ensure_ascii=False))
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
    p.add_argument("--with", dest="with_", action="append", default=[], metavar="ID",
                   help="also build this blueprint's modules (e.g. phone-assistant next to medical-practice)")
    p.add_argument("--context", action="append", default=[], metavar="ID",
                   help="take only look, duties and integrations from this (industry) blueprint")
    p.add_argument("--out", help="write the draft spec here (default: stdout)")
    p.set_defaults(func=cmd_expand)

    sub.add_parser("brief", help="print an empty domain_brief (no blueprint matched)").set_defaults(func=cmd_brief)

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
