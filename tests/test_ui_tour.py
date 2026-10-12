"""hooks/ui-tour.py — spec validation, page planning, verdicts, review checklist.

The browser part runs against a real app in test_gate_e2e.py (stage tour).
"""

from __future__ import annotations

import importlib.util
import json
import re
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
    ({"performance_budget": {"lcp": 2500}}, "performance_budget takes lcp_ms, cls and/or page_kb"),
    ({"performance_budget": {"lcp_ms": -1}}, "non-negative numbers"),
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
                visit(account=None, role=None, path="/login", console_errors=["Failed to load resource: the server responded with a status of 401 ()"]),
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
    (out / "review.md").write_text("# UI review\n\n- [x] 001.png — admin → ok: layout\n- [ ] 002.png — admin\n")
    r = run_tour("review-status", "--project-dir", str(tmp_path))
    assert r.returncode == 1 and "1/2 screenshots reviewed" in r.stdout
    (out / "review.md").write_text("- [x] 001.png — admin → ok: tiles, labels\n- [x] 002.png — admin → see findings\n"
                                   "  - ✗ Abschlussquote 100 % but 5 won, 2 lost\n")
    r = run_tour("review-status", "--project-dir", str(tmp_path))
    assert r.returncode == 1 and "open finding: Abschlussquote 100 %" in r.stdout
    (out / "review.md").write_text("- [x] 001.png — admin → ok: tiles, labels\n- [X] 002.png — admin → ok: fixed\n"
                                   "  - ✓ fixed: tile now uses the monthly counts\n")
    r = run_tour("review-status", "--project-dir", str(tmp_path))
    assert r.returncode == 0 and "2 screenshots reviewed" in r.stdout
    # a tick without a note is not a review
    (out / "review.md").write_text("- [x] 001.png — admin → ok: fine\n- [x] 002.png — admin\n")
    r = run_tour("review-status", "--project-dir", str(tmp_path))
    assert r.returncode == 1 and "not reviewed yet: 002.png" in r.stdout


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


def test_visible_identifiers_are_found():
    import importlib.util
    import shutil
    import subprocess
    from conftest import HOOKS
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    spec = importlib.util.spec_from_file_location("uitour", HOOKS / "ui-tour.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = ("Häufigste Anliegen\ncallback 5\nknowledge_question 3\nIntent: order_status, Konfidenz 96 %\n"
            "max_mustermann@example.com https://x.de/a_b /settings/user_roles token=abc_def\n"
            "Rückruf vereinbaren (Absicht: handover)\nAPI_KEY Snake_Case")
    js = mod.IDENTIFIER_JS + "\nconsole.log(JSON.stringify(findIdentifiers(" + json.dumps(text) + ")));"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["knowledge_question", "order_status"]


# ─── design audit ─────────────────────────────────────────────────────────────

def test_design_findings_open_the_review_until_a_rerun_no_longer_finds_them(tmp_path):
    font = {"kind": "font", "msg": "body text use the system font stack (ui-sans-serif)"}
    table = {"kind": "table", "msg": 'table row lines stop at column 5 ("Aktionen")'}
    visits = [visit(screenshot="001.png", design=[font]), visit(screenshot="002.png", path="/contacts", design=[font, table]),
              visit(screenshot="003.png", viewport="mobile", design=[font])]
    tour.write_reports(tmp_path, SPEC, {"logins": [], "visits": visits}, [], [], [], "admin@x.demo")
    assert tour.design_findings({"visits": visits}) == [
        f"{font['msg']} — on /dashboard (desktop), /contacts (desktop), /dashboard (mobile)",
        f"{table['msg']} — on /contacts (desktop)"]
    review = (tmp_path / "review.md").read_text()
    assert "## Design audit" in review and len(re.findall(r"^  - ✗ ", review, re.M)) == 2
    assert "## Design" in (tmp_path / "report.md").read_text()
    assert len(json.loads((tmp_path / "report.json").read_text())["design"]) == 2
    ticked = review.replace("- [ ] 001.png", "- [x] 001.png").replace(" — admin · desktop · /dashboard", " → ok: x", 1)
    (tmp_path / "review.md").write_text(ticked)
    r = run_tour("review-status", "--project-dir", str(tmp_path), "--out", str(tmp_path))
    assert r.returncode == 1 and "open finding: body text use the system font stack" in r.stdout


BAD_PAGE = """<!doctype html><html><head><style>
  body { margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: #f6f8f8; }
  .shell { display: grid; grid-template-columns: 16rem 1fr; }
  aside { position: sticky; top: 0; height: 100vh; background: #13303a; color: #fff; }
  main { padding: 24px; height: 2000px; }
  h1 { font-family: "Fraunces Display", ui-serif, serif; }
  td { border-bottom: 1px solid #ddd; padding: 8px; }
  td:last-child { border-bottom: 0; }
  .muted { color: #b8c2c2; }
</style></head><body><div class="shell">
  <aside><nav><a href="/">Dashboard</a></nav></aside>
  <main><h1>Dashboard</h1><p class="muted">Kennzahlen der letzten 7 Tage</p>
    <div><span style="font-family: ui-monospace, monospace">callback</span> 5</div>
    <button disabled style="color:#ccc;background:#eee">Senden</button>
    <code>order_status</code>
    <table><thead><tr><th>Titel</th><th>Aktionen</th></tr></thead><tbody>
      <tr><td>Versand</td><td>Bearbeiten</td></tr><tr><td>Zahlung</td><td>Bearbeiten</td></tr>
      <tr><td>Rückgabe</td><td>Bearbeiten</td></tr></tbody></table>
  </main></div></body></html>"""

GOOD_PAGE = """<!doctype html><html><head><style>
  @font-face { font-family: "Brand Sans"; src: url(/brand.ttf); }
  body { margin: 0; font-family: "Brand Sans", sans-serif; background: #f6f8f8; color: #14232a; }
  .shell { display: grid; grid-template-columns: 16rem 1fr; }
  .col { background: #13303a; color: #fff; }
  aside { position: sticky; top: 0; height: 100vh; }
  main { padding: 24px; height: 2000px; }
  tr { border-bottom: 1px solid #ddd; } table { border-collapse: collapse; }
  tbody tr:last-child { border-bottom: 0; } td { padding: 8px; }
  .muted { color: #56666b; }
</style></head><body><div class="shell">
  <div class="col"><aside><nav><a style="color:#fff" href="/">Dashboard</a></nav></aside></div>
  <main><h1>Dashboard</h1><p class="muted">Kennzahlen der letzten 7 Tage</p>
    <div>Rückruf 5 · Bestellung <span style="font-family: ui-monospace, monospace">NT-4711</span></div>
    <code>order_status</code>
    <table><thead><tr><th>Titel</th><th>Aktionen</th></tr></thead><tbody>
      <tr><td>Versand</td><td>Bearbeiten</td></tr><tr><td>Zahlung</td><td>Bearbeiten</td></tr></tbody></table>
  </main></div></body></html>"""

AUDIT_RUNNER = r"""
import { createRequire } from 'node:module';
import fs from 'node:fs';
const [, , projectDir, fontFile] = process.argv;
const req = createRequire(projectDir + '/package.json');
let pw; try { pw = req('@playwright/test'); } catch { pw = req('playwright'); }
const browser = await pw.chromium.launch();
const result = {};
try {
  for (const name of ['bad', 'good']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.route('**/*', (route) => {
      const u = new URL(route.request().url());
      if (u.pathname === '/brand.ttf') return route.fulfill({ body: fs.readFileSync(fontFile), contentType: 'font/ttf' });
      return route.fulfill({ body: fs.readFileSync(`${process.env.PAGES}/${name}.html`), contentType: 'text/html' });
    });
    await page.goto('http://audit.test/');
    result[name] = await page.evaluate(designAudit);
    await page.close();
  }
} finally { await browser.close(); }
console.log(JSON.stringify(result));
"""


def playwright_project() -> Path | None:
    """A directory whose node_modules hold Playwright: OC_PLAYWRIGHT_PROJECT, else the repo itself."""
    import os
    for candidate in (os.environ.get("OC_PLAYWRIGHT_PROJECT"), str(HOOKS.parent)):
        if candidate and any((Path(candidate) / "node_modules" / m / "package.json").exists()
                             for m in ("@playwright/test", "playwright")):
            return Path(candidate)
    return None


def test_design_audit_in_a_real_browser(tmp_path):
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    project_dir = playwright_project()
    fonts = sorted(Path("/usr/share/fonts").rglob("*.ttf")) if Path("/usr/share/fonts").exists() else []
    if project_dir is None or not fonts:
        pytest.skip("Playwright (OC_PLAYWRIGHT_PROJECT) or a .ttf font not available")
    (tmp_path / "bad.html").write_text(BAD_PAGE)
    (tmp_path / "good.html").write_text(GOOD_PAGE)
    script = tmp_path / "audit.mjs"
    script.write_text(AUDIT_RUNNER + tour.DESIGN_JS)
    import os
    r = subprocess.run(["node", str(script), str(project_dir), str(fonts[0])], capture_output=True, text=True,
                       timeout=120, env={**os.environ, "PAGES": str(tmp_path)})
    assert r.returncode == 0, r.stderr[-2000:]
    result = json.loads(r.stdout.strip().splitlines()[-1])
    bad: dict[str, str] = {}
    for f in result["bad"]:
        bad[f["kind"]] = (bad.get(f["kind"], "") + " | " + f["msg"]).strip(" |")
    assert set(bad) == {"font", "identifier", "contrast", "table", "layout"}, result["bad"]
    assert "system font stack" in bad["font"]
    assert '"callback"' in bad["identifier"] and "order_status" not in bad["identifier"]  # <code> is fine
    assert "Kennzahlen" in bad["contrast"] and "Senden" not in bad["contrast"]  # disabled is exempt
    assert 'column 2 ("Aktionen")' in bad["table"]
    assert "sidebar background ends at 900px" in bad["layout"]
    assert '"Fraunces Display" is not loaded' in bad["font"]
    assert result["good"] == [], result["good"]


def test_missing_design_brief_is_a_design_finding(tmp_path):
    data = {"logins": [], "visits": [visit(screenshot="001.png")],
            "project_design": ["no design brief (.onecommand/design.md) — oc-frontend-design was not applied"]}
    tour.write_reports(tmp_path, SPEC, data, [], [], [], "admin@x.demo")
    review = (tmp_path / "review.md").read_text()
    assert "  - ✗ no design brief (.onecommand/design.md)" in review and review.count("— project") == 1
