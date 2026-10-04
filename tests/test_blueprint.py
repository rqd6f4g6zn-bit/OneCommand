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


def test_spec_without_blueprint_passes_check(tmp_path):
    spec = write_json(tmp_path / "spec.json", {"features": ["notes"]})
    assert bp("check", "--spec", str(spec)).returncode == 0


def test_unknown_blueprint_is_a_usage_error():
    assert bp("show", "erp").returncode == 2
