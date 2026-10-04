"""quality-gate.sh end to end against a real app: Prisma + SQLite + Playwright.

Needs network (npm ci, browser download) and a few minutes, so it only runs
with ONECOMMAND_E2E_TESTS=1 (set in CI's e2e job).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from conftest import HOOKS, REPO, run

pytestmark = pytest.mark.skipif(os.environ.get("ONECOMMAND_E2E_TESTS") != "1",
                                reason="set ONECOMMAND_E2E_TESTS=1 to run the end-to-end gate test")

FIXTURE = REPO / "tests" / "fixtures" / "notes-app"
IGNORE = shutil.ignore_patterns("node_modules", "dist", ".onecommand", "test-results", "playwright-report", "dev.db*")


@pytest.fixture(scope="module")
def app(tmp_path_factory) -> Path:
    """One installed copy of the fixture, shared by the tests of this module."""
    dest = tmp_path_factory.mktemp("e2e") / "notes-app"
    shutil.copytree(FIXTURE, dest, ignore=IGNORE)
    return dest


def gate(app: Path, *args: str):
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    return run(["bash", str(HOOKS / "quality-gate.sh"), "--project-dir", str(app), *args], env=env, timeout=1800)


def gate_files(app: Path) -> tuple[dict, dict]:
    d = app / ".onecommand" / "gate"
    return json.loads((d / "result.json").read_text()), json.loads((d / "acceptance.json").read_text())


def test_full_gate_passes_on_sqlite_app(app):
    out = gate(app, "--stage", "all")
    assert out.returncode == 0, out.stdout[-4000:] + (app / ".onecommand" / "gate" / "errors.txt").read_text()
    result, acceptance = gate_files(app)
    steps = {s["step"]: s["status"] for s in result["steps"]}
    for step in ("install", "prisma", "contract", "typecheck", "lint", "build", "unit", "database", "seed", "e2e",
                 "acceptance", "tour"):
        assert steps[step] == "pass", (step, steps)
    # prisma's config loader pulls deepmerge-ts with a high advisory: recorded, not blocking.
    assert any("deepmerge-ts" in w for w in result["warnings"])
    # DATABASE_URL came from .env (SQLite) — not the Postgres default the gate used to force.
    assert (app / "prisma" / "dev.db").exists()
    assert acceptance["summary"]["blocking_passed"] == acceptance["summary"]["blocking"] == 3
    assert "ALL BLOCKING CRITERIA PASSED" in (app / ".onecommand" / "gate" / "acceptance.md").read_text()
    # UI tour: demo seed, production server, desktop + mobile screenshot of "/", review checklist.
    tour = app / ".onecommand" / "tour"
    report = json.loads((tour / "report.json").read_text())
    assert report["passed"] and [v["viewport"] for v in report["visits"]] == ["desktop", "mobile"]
    assert len(list(tour.glob("*.png"))) == 2
    assert (tour / "review.md").read_text().count("- [ ] ") == 2


def test_stale_contract_types_block_the_static_stage(app):
    types = app / "src" / "api-contract.ts"
    original = types.read_text()
    types.write_text(original.replace("title: string;\n}", "title: string;\n  pinned: boolean;\n}", 1))
    try:
        out = gate(app, "--stage", "static")
        assert out.returncode == 1
        result = json.loads((app / ".onecommand" / "gate" / "result.json").read_text())
        assert "contract" in result["failed_steps"]
        assert "differs from the contract" in (app / ".onecommand" / "gate" / "errors.txt").read_text()
    finally:
        types.write_text(original)


def test_server_error_on_a_page_fails_the_tour(app):
    server = app / "src" / "server.ts"
    original = server.read_text()
    server.write_text(original.replace('res.writeHead(200, { "content-type": "text/html" }).end(page);',
                                       'res.writeHead(500, { "content-type": "text/html" }).end(page);'))
    try:
        assert gate(app, "--stage", "static").returncode == 0  # rebuild dist/
        out = gate(app, "--stage", "tour")
        assert out.returncode == 1
        report = json.loads((app / ".onecommand" / "tour" / "report.json").read_text())
        assert any("HTTP 500" in b for b in report["blocking"]), report["blocking"]
    finally:
        server.write_text(original)
        gate(app, "--stage", "static")


def test_broken_behaviour_fails_exactly_its_criterion(app):
    server = app / "src" / "server.ts"
    original = server.read_text()
    server.write_text(original.replace("'Title is required'", "'Something went wrong'"))
    try:
        out = gate(app, "--stage", "all")
        assert out.returncode == 1
        _, acceptance = gate_files(app)
        status = {c["id"]: c["status"] for c in acceptance["criteria"]}
        assert status == {"AC-001": "passed", "AC-002": "failed", "AC-003": "passed"}
        errors = (app / ".onecommand" / "gate" / "errors.txt").read_text()
        assert "AC-002 [failed]" in errors and "Title is required" in errors
    finally:
        server.write_text(original)


def test_lint_error_blocks_before_e2e(app):
    server = app / "src" / "server.ts"
    original = server.read_text()
    server.write_text(original + '\nconsole.log("debug");\n')
    try:
        out = gate(app, "--stage", "all")
        assert out.returncode == 1
        result, _ = gate_files(app)
        assert result["failed_steps"] == ["lint"]
        assert next(s for s in result["steps"] if s["step"] == "e2e")["status"] == "skipped"
    finally:
        server.write_text(original)


def test_silent_test_change_is_reported_until_logged(app):
    assert gate(app, "--stage", "e2e").returncode == 0  # baseline exists from the earlier runs
    spec = app / "e2e" / "acceptance" / "notes.spec.ts"
    original = spec.read_text()
    log = app / ".onecommand" / "test-changes.md"
    try:
        spec.write_text(original.replace("toBeVisible();\n  await page.reload();", "toBeVisible();\n\n  await page.reload();"))
        assert gate(app, "--stage", "e2e").returncode == 0  # a warning never fails the gate …
        result, _ = gate_files(app)
        warnings = " ".join(result["warnings"])
        assert "notes.spec.ts" in warnings and "test-changes.md" in warnings  # … but it is reported
        log.write_text("- notes.spec.ts: blank line only, assertion unchanged\n")
        gate(app, "--stage", "e2e")
        result, _ = gate_files(app)
        assert not any("test-changes" in w for w in result["warnings"])
    finally:
        spec.write_text(original)
        log.unlink(missing_ok=True)
