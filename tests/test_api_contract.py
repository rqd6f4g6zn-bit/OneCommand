"""hooks/api-contract.py — one shared shape for frontend and backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import py, write_json

CONTRACT = {
    "types_file": "lib/api-contract.ts",
    "types": {"Stage": {"id": "string", "name": "string", "value": "number"},
              "Deal": {"id": "string", "status": "'open'|'won'|'lost'", "closedAt?": "date|null"}},
    "endpoints": [
        {"name": "Dashboard", "method": "GET", "path": "/api/dashboard", "auth": True,
         "response": {"openPipelineValue": "number", "winRate": "number", "stages": "Stage[]",
                      "quota": {"$nullable": True, "target": "number"}},
         "metrics": ["win_rate"]},
        {"name": "GetDeal", "method": "GET", "path": "/api/deals/[id]", "response": "Deal"},
        {"name": "Report", "method": "GET", "path": "/api/reports/winrate", "response": {"rows": [{"rate": "number"}]}},
        {"name": "DeleteDeal", "method": "DELETE", "path": "/api/deals/:id", "response": None},
        {"name": "PublicDeals", "method": "GET", "path": "/api/v1/deals", "consumer": "external", "response": "Deal[]"},
    ],
}
METRICS = [{"id": "win_rate", "label": "Abschlussquote (dieser Monat)", "definition": "won/(won+lost) this month",
            "period": "Dieser Monat", "shown_on": ["/dashboard"]}]


def spec(tmp_path: Path, contract=CONTRACT, metrics=METRICS, **extra) -> Path:
    data = {"project_name": "t", "app_type": "web-app", "build_targets": ["web"], **extra}
    if contract is not None:
        data["api_contract"] = contract
    if metrics is not None:
        data["metrics"] = metrics
    return write_json(tmp_path / ".onecommand-spec.json", data)


def contract(*args: str, **kw):
    return py("api-contract.py", *args, **kw)


# ─── validate ─────────────────────────────────────────────────────────────────

def test_valid_contract(tmp_path):
    r = contract("validate", "--spec", str(spec(tmp_path)))
    assert r.returncode == 0, r.stdout
    assert "5 endpoints, 2 shared types, 1 metrics" in r.stdout


def test_web_app_without_contract_fails_unless_allowed(tmp_path):
    s = str(spec(tmp_path, contract=None, metrics=None))
    r = contract("validate", "--spec", s)
    assert r.returncode == 1 and "no api_contract" in r.stdout
    assert contract("validate", "--spec", s, "--allow-missing").returncode == 0


def test_game_needs_no_contract(tmp_path):
    s = spec(tmp_path, contract=None, metrics=None, app_type="game")
    assert contract("validate", "--spec", str(s)).returncode == 0


@pytest.mark.parametrize("mutate,message", [
    (lambda c: c["endpoints"][0].update(name="dashboard"), "must be PascalCase"),
    (lambda c: c["endpoints"][0].update(method="FETCH"), "method must be one of"),
    (lambda c: c["endpoints"][0].update(path="api/dashboard"), "path must start with /"),
    (lambda c: c["endpoints"][0].pop("response"), "'response' is required"),
    (lambda c: c["endpoints"][0]["response"].update(total="money"), "unknown type 'money'"),
    (lambda c: c["endpoints"][0]["response"].update(items=["Deal", "Stage"]), "exactly one element type"),
    (lambda c: c["endpoints"][1].update(name="Dashboard"), "duplicate name"),
    (lambda c: c["endpoints"][3].update(path="/api/deals/[id]", method="GET"), "is defined twice"),
    (lambda c: c["endpoints"][0].update(metrics=["nope"]), "metric 'nope' is not defined"),
    (lambda c: c["endpoints"][0].update(consumer="mobile"), "consumer must be"),
    (lambda c: c["types"].update(DashboardResponse={"x": "number"}), "collides"),
])
def test_invalid_contracts(tmp_path, mutate, message):
    c = json.loads(json.dumps(CONTRACT))
    mutate(c)
    r = contract("validate", "--spec", str(spec(tmp_path, contract=c)))
    assert r.returncode == 1 and message in r.stdout, r.stdout


def test_every_metric_needs_an_endpoint_and_a_period(tmp_path):
    metrics = METRICS + [{"id": "due_tasks", "label": "Fällige Aufgaben", "definition": "open, due today or earlier"}]
    r = contract("validate", "--spec", str(spec(tmp_path, metrics=metrics)))
    assert r.returncode == 1
    assert "metric 'due_tasks': 'period' is required" in r.stdout
    assert "metric 'due_tasks' is served by no endpoint" in r.stdout


# ─── types ────────────────────────────────────────────────────────────────────

def test_types_generation(tmp_path):
    s = spec(tmp_path)
    assert contract("types", "--spec", str(s), "--project-dir", str(tmp_path)).returncode == 0
    ts = (tmp_path / "lib" / "api-contract.ts").read_text()
    assert "export interface Stage {\n  id: string;\n  name: string;\n  value: number;\n}" in ts
    assert 'status: "open" | "won" | "lost";' in ts and "closedAt?: string | null;" in ts
    assert "stages: Array<Stage>;" in ts
    assert "quota: {\n    target: number;\n  } | null;" in ts
    assert "export type GetDealResponse = Deal;" in ts
    assert "rows: Array<{\n    rate: number;\n  }>;" in ts
    assert "export type DeleteDealResponse = null;" in ts
    assert 'Dashboard: { method: "GET", path: "/api/dashboard" },' in ts
    assert '"win_rate": { label: "Abschlussquote (dieser Monat)", period: "Dieser Monat" },' in ts
    assert "metric win_rate: Abschlussquote (dieser Monat)" in ts


def test_types_check_detects_stale_file(tmp_path):
    s = str(spec(tmp_path))
    assert contract("types", "--spec", s, "--project-dir", str(tmp_path), "--check").returncode == 1  # missing
    contract("types", "--spec", s, "--project-dir", str(tmp_path))
    assert contract("types", "--spec", s, "--project-dir", str(tmp_path), "--check").returncode == 0
    f = tmp_path / "lib" / "api-contract.ts"
    f.write_text(f.read_text().replace("winRate", "closeRate"))
    assert contract("types", "--spec", s, "--project-dir", str(tmp_path), "--check").returncode == 1


def test_types_refuses_an_invalid_contract(tmp_path):
    c = json.loads(json.dumps(CONTRACT))
    c["endpoints"][0]["response"]["x"] = "money"
    r = contract("types", "--spec", str(spec(tmp_path, contract=c)), "--project-dir", str(tmp_path))
    assert r.returncode == 1 and not (tmp_path / "lib" / "api-contract.ts").exists()


def test_types_without_contract_is_not_applicable(tmp_path):
    r = contract("types", "--spec", str(spec(tmp_path, contract=None, metrics=None)), "--project-dir", str(tmp_path))
    assert r.returncode == 3


# ─── check ────────────────────────────────────────────────────────────────────

def write(p: Path, rel: str, text: str) -> None:
    (p / rel).parent.mkdir(parents=True, exist_ok=True)
    (p / rel).write_text(text)


def next_app(tmp_path: Path) -> Path:
    """A Next.js App Router project that follows the contract."""
    spec(tmp_path)
    contract("types", "--project-dir", str(tmp_path), "--spec", str(tmp_path / ".onecommand-spec.json"))
    write(tmp_path, "lib/metrics.ts", 'import type { DashboardResponse } from "./api-contract";\n'
                                      "export async function dashboard(): Promise<DashboardResponse> { return null as any; }\n")
    write(tmp_path, "app/api/dashboard/route.ts", 'import { dashboard } from "@/lib/metrics";\n'
                                                  "export async function GET() { return Response.json(await dashboard()); }\n")
    write(tmp_path, "app/api/deals/[id]/route.ts", 'import type { GetDealResponse } from "@/lib/api-contract";\n'
                                                   "export async function GET() { return Response.json({} satisfies Partial<GetDealResponse>); }\n"
                                                   "export const DELETE = async () => new Response(null, { status: 204 });\n")
    write(tmp_path, "app/api/reports/[type]/route.ts", 'import type { ReportResponse } from "../../../../lib/api-contract";\n'
                                                       "const handler = async () => Response.json({ rows: [] } satisfies ReportResponse);\n"
                                                       "export { handler as GET };\n")
    write(tmp_path, "app/api/v1/[...path]/route.ts", 'import type { PublicDealsResponse } from "@/lib/api-contract";\n'
                                                     "export async function GET() { return Response.json([] satisfies PublicDealsResponse); }\n")
    write(tmp_path, "app/(app)/dashboard/page.tsx", 'import type { DashboardResponse, GetDealResponse, ReportResponse } from "@/lib/api-contract";\n')
    return tmp_path


def check(p: Path):
    return contract("check", "--project-dir", str(p))


def test_check_passes_for_a_project_that_follows_the_contract(tmp_path):
    r = check(next_app(tmp_path))
    assert r.returncode == 0, r.stdout
    assert "5 endpoints match the contract" in r.stdout and "⚠" not in r.stdout


def test_check_reports_missing_handler_and_method(tmp_path):
    p = next_app(tmp_path)
    (p / "app/api/dashboard/route.ts").unlink()
    write(p, "app/api/deals/[id]/route.ts", 'import type { GetDealResponse } from "@/lib/api-contract";\n'
                                            "export async function GET() {}\n")
    r = check(p)
    assert r.returncode == 1
    assert "GET /api/dashboard (Dashboard): no route handler — expected app/api/dashboard/route.ts" in r.stdout
    assert "app/api/deals/[id]/route.ts does not export DELETE" in r.stdout


def test_check_requires_typed_handler_and_typed_ui(tmp_path):
    p = next_app(tmp_path)
    write(p, "app/api/reports/[type]/route.ts", "export async function GET() { return Response.json({ rows: [] }); }\n")
    write(p, "app/(app)/dashboard/page.tsx", 'import type { DashboardResponse } from "@/lib/api-contract";\n')
    r = check(p)
    assert r.returncode == 1
    assert "never uses ReportResponse" in r.stdout
    assert "GET /api/deals/[id] (GetDeal): no page, component or client module uses GetDealResponse" in r.stdout
    # an external endpoint needs no UI consumer
    assert "PublicDealsResponse" not in r.stdout.split("never uses ReportResponse")[1]


def test_check_detects_hand_edited_types(tmp_path):
    p = next_app(tmp_path)
    f = p / "lib/api-contract.ts"
    f.write_text(f.read_text() + "\nexport type Extra = string;\n")
    r = check(p)
    assert r.returncode == 1 and "differs from the contract" in r.stdout


def test_guessed_field_names_are_warnings_with_location(tmp_path):
    p = next_app(tmp_path)
    write(p, "components/kpi.tsx", "const a = 1;\n"
                                   'const rate = pick<number>(dash, ["winRate", "closeRate", "conversionRate"]);\n'
                                   'const keep = lodashPick(user, "id");\n')
    r = check(p)
    assert r.returncode == 0
    assert "⚠ components/kpi.tsx:2: pick(…, [several field names]) guesses the response shape" in r.stdout
    assert r.stdout.count("⚠") == 1


def test_most_specific_route_wins(tmp_path):
    p = next_app(tmp_path)
    write(p, "app/api/reports/winrate/route.ts", "export async function GET() { return Response.json({}); }\n")
    r = check(p)
    assert r.returncode == 1 and "app/api/reports/winrate/route.ts (or a module it imports) never uses ReportResponse" in r.stdout


def test_custom_server_only_needs_the_types_referenced(tmp_path):
    spec(tmp_path)
    contract("types", "--project-dir", str(tmp_path))
    write(tmp_path, "src/server.ts", "// no types used\n")
    r = check(tmp_path)
    assert r.returncode == 1 and "no source file uses DashboardResponse" in r.stdout
    write(tmp_path, "src/server.ts", "import type { DashboardResponse, GetDealResponse, ReportResponse, PublicDealsResponse }"
                                     ' from "../lib/api-contract";\n')
    r = check(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "route existence not checked" in r.stdout


def test_check_without_contract_is_not_applicable(tmp_path):
    spec(tmp_path, contract=None, metrics=None)
    assert check(tmp_path).returncode == 3


def test_missing_spec_is_a_usage_error(tmp_path):
    assert check(tmp_path).returncode == 2
