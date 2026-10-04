"""hooks/ui-tour.py — spec validation, page planning, verdicts, review checklist.

The browser part runs against a real app in test_gate_e2e.py (stage tour).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from conftest import HOOKS, py, require, write_json

spec_loader = importlib.util.spec_from_file_location("ui_tour", HOOKS / "ui-tour.py")
tour = importlib.util.module_from_spec(spec_loader)
spec_loader.loader.exec_module(tour)

DEMO = {"seed_command": "npm run db:seed", "login_path": "/login",
        "accounts": [{"role": "admin", "email": "admin@x.demo", "password": "Demo1234!"},
                     {"role": "sales", "email": "sales@x.demo", "password": "Demo1234!"}]}
SPEC = {"project_name": "CRM", "app_type": "web-app", "build_targets": ["web"], "auth_type": "jwt",
        "roles": [{"id": "admin"}, {"id": "sales"}],
        "pages": ["/login", "/dashboard (Übersicht)", "/contacts", "/contacts/[id]", "/contacts/import", "/logout",
                  "/api/health"],
        "demo": DEMO}


def run_tour(*args: str, **kw):
    return py("ui-tour.py", *args, **kw)


def spec_file(tmp_path: Path, **changes) -> Path:
    data = json.loads(json.dumps(SPEC))
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return write_json(tmp_path / ".onecommand-spec.json", data)


# ─── validate ─────────────────────────────────────────────────────────────────

def test_valid_spec(tmp_path):
    r = run_tour("validate", "--spec", str(spec_file(tmp_path)))
    assert r.returncode == 0, r.stdout
    assert "6 pages, 2 demo login(s)" in r.stdout


@pytest.mark.parametrize("changes,message", [
    ({"demo": None}, "spec has no demo section"),
    ({"pages": []}, "spec has no pages"),
    ({"demo": {"accounts": []}}, "the app has a login but demo.accounts is empty"),
    ({"demo": {**DEMO, "login_path": None}}, "demo.login_path is required"),
    ({"demo": {**DEMO, "accounts": DEMO["accounts"][:1]}}, "no demo login for role(s): sales"),
    ({"demo": {**DEMO, "accounts": [{"role": "admin", "email": "a@x"}]}}, "needs email and password"),
    ({"demo": {**DEMO, "seed_command": " "}}, "demo.seed_command is empty"),
])
def test_invalid_specs(tmp_path, changes, message):
    r = run_tour("validate", "--spec", str(spec_file(tmp_path, **changes)))
    assert r.returncode == 1 and message in r.stdout, r.stdout


def test_app_without_login_needs_no_accounts(tmp_path):
    s = spec_file(tmp_path, auth_type="none", roles=[], demo={"seed_command": "npm run db:seed", "accounts": []})
    assert run_tour("validate", "--spec", str(s)).returncode == 0


def test_game_is_not_applicable(tmp_path):
    assert run_tour("validate", "--spec", str(spec_file(tmp_path, app_type="game"))).returncode == 3


# ─── planning ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entry,expected", [
    ("/dashboard (Übersicht)", "/dashboard"), ("/ (landing)", "/"), ({"path": "/x"}, "/x"),
    ("Kontakte: /contacts", "/contacts"), ("no path", None),
])
def test_page_path(entry, expected):
    assert tour.page_path(entry) == expected


def test_pages_are_split_into_public_private_and_dynamic():
    pages = tour.collect_pages(SPEC)
    assert "/api/health" not in pages
    anon, priv = tour.split_pages(pages, "/login", with_accounts=True)
    assert anon == {"static": ["/login"], "dynamic": []}
    assert priv["static"] == ["/dashboard", "/contacts", "/contacts/import"]  # /logout is never visited
    assert [d["path"] for d in priv["dynamic"]] == ["/contacts/[id]"]
    anon, priv = tour.split_pages(pages, None, with_accounts=False)
    assert priv == {"static": [], "dynamic": []} and "/dashboard" in anon["static"]


@pytest.mark.parametrize("pattern,path,match", [
    ("/contacts/[id]", "/contacts/abc123", True), ("/contacts/[id]", "/contacts/abc/notes", False),
    ("/deals/:id/edit", "/deals/7/edit", True), ("/docs/[...slug]", "/docs/a/b", True),
])
def test_pattern_regex(pattern, path, match):
    import re
    assert bool(re.match(tour.pattern_regex(pattern), path)) is match


def test_metric_labels_per_page():
    labels = tour.metric_labels({"metrics": [
        {"id": "win_rate", "label": "Abschlussquote (dieser Monat)", "shown_on": ["/dashboard"]},
        {"id": "open", "label": "Offene Pipeline", "shown_on": ["/dashboard", "/reports", "/deals/[id]"]},
        {"id": "x", "label": "No pages"}]})
    assert labels == {"/dashboard": [{"id": "win_rate", "label": "Abschlussquote (dieser Monat)"},
                                     {"id": "open", "label": "Offene Pipeline"}],
                      "/reports": [{"id": "open", "label": "Offene Pipeline"}]}


def test_production_env_uses_fresh_secrets_and_drops_test_mode(monkeypatch):
    monkeypatch.setenv("ONECOMMAND_E2E", "1")
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    env = tour.production_env("http://127.0.0.1:3210", 3210)
    assert "ONECOMMAND_E2E" not in env and env["NODE_ENV"] == "production" and env["PORT"] == "3210"
    assert len(env["AUTH_SECRET"]) >= 48 and env["APP_URL"] == "http://127.0.0.1:3210"
    assert tour.production_env("u", 1)["AUTH_SECRET"] != env["AUTH_SECRET"]


# ─── verdict ──────────────────────────────────────────────────────────────────

def visit(**kw):
    base = {"account": "admin@x.demo", "role": "admin", "viewport": "desktop", "path": "/dashboard", "status": 200,
            "issues": [], "warnings": [], "console_errors": []}
    return {**base, **kw}


def test_evaluate():
    data = {"logins": [{"account": "sales@x.demo", "role": "sales", "ok": False, "error": "Ungültige Anmeldedaten"}],
            "visits": [
                visit(),
                visit(path="/settings", status=404),
                visit(account="sales@x.demo", role="sales", path="/settings", status=403),
                visit(path="/reports", issues=['visible text shows "NaN"']),
                visit(viewport="mobile", warnings=["page is 212px wider than the 390px viewport (horizontal scrolling)"]),
                visit(path="/contacts", console_errors=["Hydration failed"]),
            ]}
    blocking, warnings, notes = tour.evaluate(data, "admin@x.demo")
    assert blocking == ["login failed for sales@x.demo (sales): Ungültige Anmeldedaten",
                        "admin · desktop · /settings: HTTP 404 — a page of the spec is missing or not reachable",
                        'admin · desktop · /reports: visible text shows "NaN"']
    assert notes == ["sales · desktop · /settings: HTTP 403 (restricted for this role)"]
    assert len(warnings) == 2 and "212px" in warnings[0] and "Hydration failed" in warnings[1]


def test_review_list_covers_first_account_and_landing_pages_of_other_roles(tmp_path):
    visits = [visit(screenshot="001.png", path="/login", account=None, role=None),
              visit(screenshot="002.png"), visit(screenshot="003.png", path="/contacts"),
              visit(screenshot="004.png", viewport="mobile"),
              visit(screenshot="005.png", account="sales@x.demo", role="sales"),
              visit(screenshot="006.png", account="sales@x.demo", role="sales", path="/contacts")]
    tour.write_reports(tmp_path, SPEC, {"logins": [], "visits": visits}, [], [], [], "admin@x.demo")
    review = (tmp_path / "review.md").read_text()
    listed = [line.split()[3] for line in review.splitlines() if line.startswith("- [ ] ")]
    assert listed == ["001.png", "002.png", "003.png", "004.png", "005.png"]
    assert "Numbers agree" in review
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["passed"] is True and len(report["visits"]) == 6


# ─── review-status ────────────────────────────────────────────────────────────

def test_review_status(tmp_path):
    out = tmp_path / ".onecommand" / "tour"
    out.mkdir(parents=True)
    assert run_tour("review-status", "--project-dir", str(tmp_path)).returncode == 1  # no review yet
    (out / "review.md").write_text("# UI review\n\n- [x] 001.png — admin\n- [ ] 002.png — admin\n")
    r = run_tour("review-status", "--project-dir", str(tmp_path))
    assert r.returncode == 1 and "1/2 screenshots reviewed" in r.stdout
    (out / "review.md").write_text("- [x] 001.png — admin\n- [x] 002.png — admin\n"
                                   "  - ✗ Abschlussquote 100 % but 5 won, 2 lost\n")
    r = run_tour("review-status", "--project-dir", str(tmp_path))
    assert r.returncode == 1 and "open finding: Abschlussquote 100 %" in r.stdout
    (out / "review.md").write_text("- [x] 001.png — admin\n- [X] 002.png — admin\n"
                                   "  - ✓ fixed: tile now uses the monthly counts\n")
    r = run_tour("review-status", "--project-dir", str(tmp_path))
    assert r.returncode == 0 and "2 screenshots reviewed" in r.stdout


# ─── run (up to the browser) ──────────────────────────────────────────────────

def project(tmp_path: Path, start: str = 'node -e "process.exit(1)"', with_playwright: bool = True, **spec_changes) -> Path:
    p = tmp_path / "app"
    p.mkdir()
    write_json(p / "package.json", {"name": "app", "private": True, "scripts": {"start": start}})
    if with_playwright:
        write_json(p / "node_modules" / "@playwright" / "test" / "package.json", {"name": "@playwright/test"})
    spec_file(p, **spec_changes)
    return p


def test_run_without_demo_is_not_applicable(tmp_path):
    p = project(tmp_path, demo=None)
    assert run_tour("run", "--project-dir", str(p)).returncode == 3


def test_run_rejects_an_invalid_spec(tmp_path):
    p = project(tmp_path, pages=[])
    r = run_tour("run", "--project-dir", str(p))
    assert r.returncode == 1 and "spec has no pages" in r.stdout


def test_run_needs_playwright(tmp_path):
    p = project(tmp_path, with_playwright=False)
    r = run_tour("run", "--project-dir", str(p))
    assert r.returncode == 1 and "playwright is installed" in r.stdout


def test_failing_demo_seed_stops_the_tour(tmp_path):
    require("node")
    p = project(tmp_path, demo={**DEMO, "seed_command": "echo 'P2002 unique constraint' && exit 4"})
    r = run_tour("run", "--project-dir", str(p))
    assert r.returncode == 1 and "demo seed failed with exit code 4" in r.stdout and "P2002" in r.stdout


def test_seed_runs_in_demo_mode_without_test_mode(tmp_path):
    require("node")
    p = project(tmp_path, demo={**DEMO, "seed_command": 'echo "mode=$SEED_MODE e2e=${ONECOMMAND_E2E:-unset}" > seed.out'})
    run_tour("run", "--project-dir", str(p), env={"ONECOMMAND_E2E": "1"})
    assert (p / "seed.out").read_text().strip() == "mode=demo e2e=unset"


def test_server_that_exits_is_reported_with_its_log(tmp_path):
    require("npm")
    p = project(tmp_path, start="node -e \"console.error('Error: AUTH_SECRET must be set'); process.exit(1)\"")
    r = run_tour("run", "--project-dir", str(p), "--no-seed", "--start-timeout", "60")
    assert r.returncode == 1
    assert "server exited with code 1" in r.stdout and "AUTH_SECRET must be set" in r.stdout
