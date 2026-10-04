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
    for step in ("install", "prisma", "typecheck", "lint", "build", "unit", "database", "seed", "e2e", "acceptance"):
        assert steps[step] == "pass", (step, steps)
    # DATABASE_URL came from .env (SQLite) — not the Postgres default the gate used to force.
    assert (app / "prisma" / "dev.db").exists()
    assert acceptance["summary"]["blocking_passed"] == acceptance["summary"]["blocking"] == 3
    assert "ALL BLOCKING CRITERIA PASSED" in (app / ".onecommand" / "gate" / "acceptance.md").read_text()


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
