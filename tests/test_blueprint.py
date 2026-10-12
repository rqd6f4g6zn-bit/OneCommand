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
    assert w["design_direction"]["typefaces"] == restaurant["design"]["typefaces"] and w["compliance"]
    assert not any(c["source"].startswith("blueprint:restaurant/") for c in w["acceptance_criteria"])  # no kitchen display


def test_industry_website_gets_the_guest_facing_modules_not_the_back_office(tmp_path):
    """'Webseite für unser Restaurant': menu with allergens, opening hours, table request — not an agency site
    with case studies, and not the duties of the restaurant's cash register."""
    out = tmp_path / "web.json"
    assert bp("expand", "website", "--context", "restaurant", "--tier", "pro", "--out", str(out)).returncode == 0
    spec = json.loads(out.read_text())
    assert {"speisekarte", "oeffnungszeiten", "reservierung", "feiern"} <= set(spec["features"])
    assert "case-studies" not in spec["features"] and "case-studies" in spec["blueprint"]["excluded_modules"]
    assert {"/speisekarte", "/reservierung", "/feiern", "/journal"} <= set(spec["pages"])
    assert not {"/leistungen", "/referenzen", "/blog", "/kontakt"} & set(spec["pages"])
    assert any(c["source"].startswith("blueprint:restaurant.website/speisekarte/") for c in spec["acceptance_criteria"])
    sources = " ".join(r["source"] for r in spec["compliance"])
    assert "LMIV" in sources and "PAngV" in sources                      # the menu's duties
    assert "KassenSichV" not in sources and "ArbZG" not in sources       # the software's duties
    design = spec["design_direction"]
    assert design["motion"].startswith("emil") and "Tischplan" not in " ".join(design["signature_ideas"])
    assert "Template-Hero mit Stockfoto" in design["avoid"] and "rote Gefahren-Symbole für Allergene" in design["avoid"]
    assert not any("Kasse" in x for x in spec["integrations"]["connectable"])
    assert bp("check", "--spec", str(out)).returncode == 0
    spec["acceptance_criteria"] = [c for c in spec["acceptance_criteria"] if "restaurant.website/speisekarte" not in c["source"]]
    out.write_text(json.dumps(spec))
    r = bp("check", "--spec", str(out))
    assert r.returncode == 1 and "speisekarte" in r.stdout          # website-block criteria are covered too
    # the software build of the same industry is unchanged
    soft = json.loads(bp("expand", "restaurant", "--tier", "pro").stdout)
    assert "KassenSichV" in " ".join(r["source"] for r in soft["compliance"]) and "speisekarte" not in soft["features"]


INDUSTRIES = [p.stem for p in BLUEPRINTS if json.loads(p.read_text()).get("kind") == "industry"]


@pytest.mark.parametrize("industry", INDUSTRIES)
def test_every_industry_has_a_website_block_that_expands(tmp_path, industry):
    data = json.loads((REPO / "skills/domain-blueprints/blueprints" / f"{industry}.json").read_text())
    block = data.get("website")
    assert block, f"{industry}: no website block — 'Webseite für …' would get a generic agency site"
    website = json.loads((REPO / "skills/domain-blueprints/blueprints/website.json").read_text())
    site_ids = {m["id"] for m in website["modules"]}
    assert set(block.get("exclude") or {}) <= site_ids and all(str(v).strip() for v in (block.get("exclude") or {}).values())
    assert set(block.get("page_map") or {}) <= {p for t in website["pages"].values() for p in t}
    ids = [m["id"] for m in block["modules"]]
    assert len(ids) == len(set(ids)) and not set(ids) & site_ids
    assert sum(m["tier"] == "mvp" for m in block["modules"]) >= 2
    for m in block["modules"]:
        assert m["features"] and m["criteria"], m["id"]
        for c in m["criteria"]:
            assert c["verification"] in ("e2e", "api", "manual") and c["steps"] and c["expected"]
    for r in data.get("compliance", []):
        assert r.get("scope", "all") in ("all", "software", "website"), r
    for tier in TIERS:
        for platform in ([], ["--platform", "wordpress"]):
            out = tmp_path / f"{tier}-{len(platform)}.json"
            r = bp("expand", "website", "--context", industry, "--tier", tier, *platform, "--out", str(out))
            assert r.returncode == 0, r.stderr
            for script, cmd in (("blueprint.py", "check"), ("acceptance-report.py", "validate"), ("ui-tour.py", "validate")):
                v = py(script, cmd, "--spec", str(out))
                assert v.returncode == 0, (industry, tier, platform, script, v.stdout[-800:])
            assert "vague wording" not in py("acceptance-report.py", "validate", "--spec", str(out)).stdout


def test_every_blueprint_declares_its_kind_and_aliases_are_unique():
    seen = {}
    for path in BLUEPRINTS:
        data = json.loads(path.read_text())
        assert data.get("kind") in ("product", "industry"), path.stem
        for a in data["aliases"]:
            assert a not in seen, f"alias '{a}' in {path.stem} and {seen.get(a)}"
            seen[a] = path.stem


def test_wordpress_platform_is_detected_and_expanded(tmp_path):
    plan = json.loads(bp("detect", "--prompt", "Premium WordPress Webseite für unser Restaurant", "--json").stdout)["plan"]
    assert (plan["primary"], plan["context"], plan["platform"]) == ("website", ["restaurant"], "wordpress")
    assert json.loads(bp("detect", "--prompt", "Firmenwebseite für einen Handwerksbetrieb", "--json").stdout)["plan"]["platform"] is None
    out = tmp_path / "wp.json"
    assert bp("expand", "website", "--context", "restaurant", "--platform", "wordpress", "--tier", "pro",
              "--project-name", "Trattoria Luna", "--out", str(out)).returncode == 0
    spec = json.loads(out.read_text())
    assert spec["wordpress"]["theme"] == "trattoria-luna" and spec["wordpress"]["plugins"] == ["trattoria-luna-core"]
    assert spec["blueprint"]["platform"] == "wordpress" and spec["tech_stack"]["cms"] == "wordpress"
    assert {"wp-theme", "wp-editor-experience", "wp-privacy", "wp-security", "wp-performance"} <= set(spec["features"])
    assert "/admin" not in spec["pages"] and "/wp-admin/" not in spec["pages"]   # the back office is not a page
    assert spec["demo"]["login_path"] == "/wp-login.php"
    assert {a["wp_role"] for a in spec["demo"]["accounts"]} == {"administrator", "editor"}
    assert spec["demo"]["accounts"][0]["wp_role"] == "administrator"           # wp-gate installs with the first one
    text = json.dumps(spec["acceptance_criteria"])
    assert "/api/contact" not in text and "rss.xml" not in text and "/wp-admin/admin-post.php" in text and "/feed/" in text
    consent = next(c for c in spec["acceptance_criteria"] if c["source"] == "blueprint:website/legal-consent/0")
    assert "analytics" not in json.dumps(consent).lower() and "Datenschutz-Einstellungen" in json.dumps(consent)
    for tool in ("blueprint.py check", "acceptance-report.py validate", "ui-tour.py validate"):
        script, cmd = tool.split()
        assert py(script, cmd, "--spec", str(out)).returncode == 0, tool
    spec["acceptance_criteria"] = [c for c in spec["acceptance_criteria"] if "wp-privacy" not in c["source"]]
    out.write_text(json.dumps(spec))
    assert "wp-privacy" in bp("check", "--spec", str(out)).stdout          # platform modules are covered too


def test_woocommerce_shop_gets_the_german_legal_module(tmp_path):
    out = tmp_path / "shop.json"
    assert bp("expand", "shop", "--platform", "wordpress", "--out", str(out)).returncode == 0
    spec = json.loads(out.read_text())
    assert "wc-germany" in spec["features"] and spec["wordpress"]["third_party_plugins"] == ["woocommerce", "woocommerce-germanized"]


@pytest.mark.parametrize("prompt,platform,ask", [
    ("Webseite für unser Restaurant", None, ["custom", "wordpress"]),      # open → the orchestrator asks once
    ("Online-Shop für Kaffee", None, ["custom", "wordpress"]),
    ("WordPress Webseite für unser Restaurant", "wordpress", []),
    ("Next.js Webseite für unsere Kanzlei", "custom", []),
    ("Webseite mit eigenem Code für unsere Kanzlei", "custom", []),
    ("CRM auf höchstem Niveau", None, []),                                 # no platform choice for apps
])
def test_platform_question_only_when_the_prompt_leaves_it_open(prompt, platform, ask):
    plan = json.loads(bp("detect", "--prompt", prompt, "--json").stdout)["plan"]
    assert plan["platform"] == platform and plan.get("ask_platform", []) == ask, plan


def test_custom_platform_is_recorded_without_wordpress(tmp_path):
    out = tmp_path / "s.json"
    assert bp("expand", "website", "--platform", "custom", "--out", str(out)).returncode == 0
    spec = json.loads(out.read_text())
    assert spec["blueprint"]["platform"] == "custom" and "wordpress" not in spec
