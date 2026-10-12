"""hooks/blueprint.py and skills/domain-blueprints — domain knowledge for short prompts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import REPO, py, write_json

BLUEPRINTS = sorted((REPO / "skills" / "domain-blueprints" / "blueprints").glob("*.json"))
TIERS = ("mvp", "pro", "enterprise")


def bp(*args: str):
    return py("blueprint.py", *args)


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.stem)
def test_blueprint_schema(path: Path):
    data = json.loads(path.read_text())
    assert data["id"] == path.stem
    assert data["aliases"] and all(a == a.lower() for a in data["aliases"])
    ids = [m["id"] for m in data["modules"]]
    assert len(ids) == len(set(ids)), "module ids must be unique"
    assert any(m["tier"] == "mvp" for m in data["modules"])
    for m in data["modules"]:
        assert m["tier"] in TIERS and m["features"] and m["criteria"], m["id"]
        for c in m["criteria"]:
            assert c["verification"] in ("e2e", "api", "manual")
            assert c["title"] and c["steps"] and c["expected"], (m["id"], c)
            if c["verification"] == "e2e":
                assert "start" in c, (m["id"], c["title"])
    for e in data.get("entities", []):
        assert e.get("tier", "mvp") in TIERS
    assert set(data.get("pages", {})) <= set(TIERS)
    import importlib.util
    spec = importlib.util.spec_from_file_location("bpmod", REPO / "hooks" / "blueprint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.design_problems(data.get("design"), "design") == [], "every blueprint carries a design direction"
    for r in data.get("compliance", []):
        assert r["rule"] and r["source"] and r.get("tier", "mvp") in TIERS, r
    if "integrations" in data:
        assert set(data["integrations"]) == {"connectable", "export_only", "not_possible"}
    metric_ids = [m["id"] for m in data.get("metrics", [])]
    assert len(metric_ids) == len(set(metric_ids))
    all_pages = {p for tier_pages in data.get("pages", {}).values() for p in tier_pages}
    for m in data.get("metrics", []):
        assert m["tier"] in TIERS and m["label"] and m["definition"] and m["period"], m["id"]
        assert set(m.get("shown_on", [])) <= all_pages, (m["id"], "shown_on must name pages of the blueprint")


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.stem)
@pytest.mark.parametrize("tier", TIERS)
def test_every_expansion_is_a_valid_spec_that_covers_its_blueprint(tmp_path, path, tier):
    out = tmp_path / "spec.json"
    r = bp("expand", path.stem, "--tier", tier, "--out", str(out))
    assert r.returncode == 0, r.stderr
    v = py("acceptance-report.py", "validate", "--spec", str(out))
    assert v.returncode == 0, v.stdout
    assert "vague wording" not in v.stdout, v.stdout
    c = bp("check", "--spec", str(out))
    assert c.returncode == 0, c.stdout
    # The draft's metrics and demo logins pass the contract/tour validators (contract added by spec-analyzer).
    draft = json.loads(out.read_text())
    t = py("ui-tour.py", "validate", "--spec", str(out))
    assert t.returncode == 0, t.stdout
    assert len(draft["demo"]["accounts"]) == len(draft["roles"])


def test_tiers_are_cumulative(tmp_path):
    sizes = []
    for tier in TIERS:
        out = tmp_path / f"{tier}.json"
        bp("expand", "crm", "--tier", tier, "--out", str(out))
        spec = json.loads(out.read_text())
        sizes.append((len(spec["features"]), len(spec["acceptance_criteria"])))
        ids = [c["id"] for c in spec["acceptance_criteria"]]
        assert len(ids) == len(set(ids))
    assert sizes[0] < sizes[1] < sizes[2]


@pytest.mark.parametrize("prompt,blueprint,tier", [
    ("ein crm auf hösterm nivo", "crm", "enterprise"),
    ("CRM auf höchstem Niveau", "crm", "enterprise"),
    ("Kundenverwaltung für mein Team", "crm", "pro"),
    ("CRM, einfach zu bedienen", "crm", "pro"),
    ("ein einfaches CRM als erste Version", "crm", "mvp"),
    ("Online-Shop für Kaffeebohnen", "shop", "pro"),
    ("Terminbuchung für einen Friseursalon", "booking", "pro"),
    ("Ticketsystem für unseren Support", "helpdesk", "pro"),
    ("Projektmanagement wie Trello", "projects", "pro"),
    ("Rechnungsprogramm für Freelancer", "invoicing", "pro"),
    ("Firmenwebseite für einen Handwerksbetrieb", "website", "pro"),
    ("Webseite im 100k Preissegment mit Videos", "website", "enterprise"),
    ("Premium Website für unsere Agentur", "website", "enterprise"),
    ("Software für unser Notariat", "notary", "pro"),
    ("Kanzleisoftware für Anwälte", "law-firm", "pro"),
    ("Software für Steuerberater mit Mandantenportal", "tax-advisor", "pro"),  # Mandant = client, not multi-tenant
    ("Software für meine Arztpraxis", "medical-practice", "pro"),
    ("Software für unsere Hausverwaltung", "property-management", "pro"),
    ("Software für Immobilienmakler", "real-estate-agency", "pro"),
    ("Software für einen Handwerksbetrieb", "trades", "pro"),
    ("Software für unser Restaurant", "restaurant", "pro"),
    ("Bewerbermanagement für unsere Firma", "recruiting", "pro"),
    ("Lagerverwaltung für unser Lager", "warehouse", "pro"),
    ("Webseite für unser Restaurant", "website", "pro"),
])
def test_detect(prompt, blueprint, tier):
    r = bp("detect", "--prompt", prompt, "--json")
    data = json.loads(r.stdout)
    assert data["matches"] and data["matches"][0]["id"] == blueprint, data
    assert data["tier"] == tier, data


def test_no_match_exits_1():
    assert bp("detect", "--prompt", "Notiz-App mit Login").returncode == 1


def draft(tmp_path: Path, *extra: str) -> tuple[Path, dict]:
    out = tmp_path / "spec.json"
    assert bp("expand", "crm", "--tier", "pro", "--out", str(out), *extra).returncode == 0
    return out, json.loads(out.read_text())


def test_check_detects_a_dropped_module(tmp_path):
    out, spec = draft(tmp_path)
    spec["features"].remove("reports")
    write_json(out, spec)
    r = bp("check", "--spec", str(out))
    assert r.returncode == 1 and "module 'reports'" in r.stdout


def test_check_detects_a_dropped_criterion_but_allows_rewording(tmp_path):
    out, spec = draft(tmp_path)
    spec["acceptance_criteria"][0]["title"] = "Anmeldung mit gültigen Daten führt zum Dashboard"  # reworded: fine
    write_json(out, spec)
    assert bp("check", "--spec", str(out)).returncode == 0
    dropped = spec["acceptance_criteria"].pop(3)
    write_json(out, spec)
    r = bp("check", "--spec", str(out))
    assert r.returncode == 1 and dropped["source"] in r.stdout


def test_exclude_requires_and_keeps_the_users_reason(tmp_path):
    out, spec = draft(tmp_path, "--exclude", "products-quotes=Nutzer: keine Angebote nötig")
    assert "products-quotes" not in spec["features"]
    assert spec["blueprint"]["excluded_modules"] == {"products-quotes": "Nutzer: keine Angebote nötig"}
    r = bp("check", "--spec", str(out))
    assert r.returncode == 0 and "excluded: Nutzer: keine Angebote nötig" in r.stdout
    assert bp("expand", "crm", "--exclude", "products-quotes").returncode == 2
    assert bp("expand", "crm", "--exclude", "nope=x").returncode == 2


def test_check_detects_a_dropped_metric(tmp_path):
    out, spec = draft(tmp_path)
    assert [m["id"] for m in spec["metrics"]] == ["open_pipeline", "won_this_month", "win_rate", "due_tasks",
                                                  "weighted_forecast"]
    spec["metrics"] = [m for m in spec["metrics"] if m["id"] != "win_rate"]
    write_json(out, spec)
    r = bp("check", "--spec", str(out))
    assert r.returncode == 1 and "metric 'win_rate' (Abschlussquote (dieser Monat)) was dropped" in r.stdout


def test_crm_metrics_name_their_period(tmp_path):
    out, spec = draft(tmp_path)
    labels = {m["id"]: m["label"] for m in spec["metrics"]}
    assert labels["win_rate"] == "Abschlussquote (dieser Monat)" and labels["won_this_month"] == "Gewonnen (dieser Monat)"
    titles = [c["title"] for c in spec["acceptance_criteria"]]
    assert "Dashboard and reports show the same open pipeline and win rate for 'Dieser Monat'" in titles


BRIEF = {
    "domain": "Notariat",
    "roles": [{"name": "Notar", "can": "beurkundet"}, {"name": "Notarfachangestellte", "can": "bereitet Vorgänge vor"}],
    "processes": [
        {"name": "Grundstückskauf", "feature": "deeds", "steps": ["Datenblatt", "Entwurf versenden", "Beurkundung", "Vollzug"]},
        {"name": "Testament", "feature": "wills", "steps": ["Vorgespräch", "Entwurf", "Beurkundung", "Verwahrung"]},
        {"name": "Kostenrechnung", "feature": "fees", "steps": ["Geschäftswert", "Gebühr nach Tabelle B", "Rechnung"]},
    ],
    "rules": [{"rule": "Entwurf 14 Tage vor Beurkundung an Verbraucher", "source": "§ 17 Abs. 2a BeurkG"}],
    "deadlines": [{"what": "Entwurfsfrist", "when": "14 Tage"}],
    "integrations": {"connectable": [], "export_only": ["XNP"], "not_possible": ["Urkundenarchiv — nur über BNotK"]},
    "glossary": [{"term": t, "meaning": "…"} for t in ("Urkunde", "Vollzug", "Anderkonto", "Beurkundung", "GNotKG")],
    "design": {"personality": ["seriös", "ruhig", "präzise"], "typefaces": {"display": "Newsreader", "text": "IBM Plex Sans"},
               "palette": "Tintenblau", "density": "compact", "signature_ideas": ["Urkunden-Siegel"],
               "references": ["Clio", "DATEV"], "avoid": ["verspielte Illustrationen"]},
}


def brief_spec(tmp_path, brief=BRIEF, **extra):
    criteria = [{"id": f"AC-00{i}", "feature": f, "priority": "must"} for i, f in enumerate(("deeds", "wills", "fees"), 1)]
    return write_json(tmp_path / "spec.json", {"app_type": "web-app", "features": ["deeds", "wills", "fees"],
                                               "acceptance_criteria": criteria, "domain_brief": brief, **extra})


def test_unknown_domain_needs_a_researched_brief(tmp_path):
    spec = write_json(tmp_path / "spec.json", {"app_type": "web-app", "features": ["notes"]})
    r = bp("check", "--spec", str(spec))
    assert r.returncode == 1 and "has no domain_brief" in r.stdout
    r = bp("check", "--spec", str(brief_spec(tmp_path)))
    assert r.returncode == 0, r.stdout
    assert "domain brief complete — Notariat: 3 processes, 1 rules" in r.stdout


def test_domain_brief_problems_are_named(tmp_path):
    thin = {**BRIEF, "processes": BRIEF["processes"][:2] + [{"name": "Vollmacht", "feature": "powers", "steps": ["a", "b", "c"]}],
            "rules": [], "glossary": BRIEF["glossary"][:2], "integrations": {"connectable": []},
            "design": {"personality": ["seriös"]}}
    r = bp("check", "--spec", str(brief_spec(tmp_path, thin)))
    assert r.returncode == 1
    for needle in ("feature 'powers' is not in spec.features", "rules_none_reason", "not_possible", "glossary",
                   "design.typefaces", "design.personality"):
        assert needle in r.stdout, needle


def test_games_and_os_need_no_domain_brief(tmp_path):
    for app_type in ("game", "os"):
        spec = write_json(tmp_path / f"{app_type}.json", {"app_type": app_type, "features": ["levels"]})
        assert bp("check", "--spec", str(spec)).returncode == 0


def test_expand_carries_design_direction_into_the_spec(tmp_path):
    out = tmp_path / "spec.json"
    assert bp("expand", "booking", "--out", str(out)).returncode == 0
    draft = json.loads(out.read_text())
    assert draft["design_direction"]["density"] == "comfortable" and len(draft["design_direction"]["personality"]) == 3
    template = json.loads(bp("brief").stdout)["domain_brief"]
    assert {"roles", "processes", "rules", "deadlines", "integrations", "glossary", "design"} <= set(template)


def test_unknown_blueprint_is_a_usage_error():
    assert bp("show", "erp").returncode == 2


def test_website_carries_performance_budget_media_and_cms_login(tmp_path):
    out = tmp_path / "spec.json"
    assert bp("expand", "website", "--tier", "enterprise", "--out", str(out)).returncode == 0
    spec = json.loads(out.read_text())
    assert spec["performance_budget"] == {"lcp_ms": 2000, "cls": 0.05, "page_kb": 1200}
    assert [v["name"] for v in spec["media"]["videos"]] == ["hero", "imagefilm"]
    assert spec["demo"]["login_path"] == "/admin/login"
    mvp = json.loads(bp("expand", "website", "--tier", "mvp").stdout)
    assert "media" not in mvp and mvp["demo"]["accounts"] == [] and mvp["demo"]["login_path"] is None



@pytest.mark.parametrize("prompt,primary,with_,context", [
    ("Webseite für unser Restaurant", "website", [], ["restaurant"]),            # product leads, industry gives look + duties
    ("Terminbuchung für meine Arztpraxis", "booking", [], ["medical-practice"]),
    ("Praxis-Software für Physiotherapie mit Telefon-KI", "medical-practice", ["phone-assistant"], []),
    ("Software für unser Notariat", "notary", [], []),
])
def test_detect_plans_product_and_industry(prompt, primary, with_, context):
    plan = json.loads(bp("detect", "--prompt", prompt, "--json").stdout)["plan"]
    assert (plan["primary"], plan["with"], plan["context"]) == (primary, with_, context), plan


def test_combined_expansion_is_covered_and_carries_the_industry_look(tmp_path):
    out = tmp_path / "spec.json"
    r = bp("expand", "medical-practice", "--with", "phone-assistant", "--tier", "pro", "--out", str(out))
    assert r.returncode == 0, r.stderr
    spec = json.loads(out.read_text())
    assert spec["blueprint"]["with"] == ["phone-assistant"]
    assert any(s.startswith("blueprint:phone-assistant/") for s in (c["source"] for c in spec["acceptance_criteria"]))
    assert len(spec["features"]) == len(set(spec["features"]))           # shared modules (auth) only once
    medical = json.loads((REPO / "skills/domain-blueprints/blueprints/medical-practice.json").read_text())
    assert spec["design_direction"] == medical["design"]
    assert bp("check", "--spec", str(out)).returncode == 0
    assert py("acceptance-report.py", "validate", "--spec", str(out)).returncode == 0
    # dropping a criterion of the second blueprint is caught too
    spec["acceptance_criteria"] = [c for c in spec["acceptance_criteria"] if not c["source"].startswith("blueprint:phone-assistant/")]
    out.write_text(json.dumps(spec))
    r = bp("check", "--spec", str(out))
    assert r.returncode == 1 and "blueprint:phone-assistant/" in r.stdout

    web = tmp_path / "web.json"
    assert bp("expand", "website", "--context", "restaurant", "--out", str(web)).returncode == 0
    w = json.loads(web.read_text())
    restaurant = json.loads((REPO / "skills/domain-blueprints/blueprints/restaurant.json").read_text())
    assert w["design_direction"] == restaurant["design"] and w["compliance"]
    assert not any(c["source"].startswith("blueprint:restaurant/") for c in w["acceptance_criteria"])  # no kitchen display


def test_every_blueprint_declares_its_kind_and_aliases_are_unique():
    seen = {}
    for path in BLUEPRINTS:
        data = json.loads(path.read_text())
        assert data.get("kind") in ("product", "industry"), path.stem
        for a in data["aliases"]:
            assert a not in seen, f"alias '{a}' in {path.stem} and {seen.get(a)}"
            seen[a] = path.stem
