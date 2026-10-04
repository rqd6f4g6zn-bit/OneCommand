"""hooks/quality-gate.sh — static stage, exit codes, error extraction, env handling.

The static tests use a dependency-free Node project, so they run offline in a
few seconds. The full e2e run against a real app lives in test_gate_e2e.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import HOOKS, require, run, write_json

require("node")
require("npm")
GATE = str(HOOKS / "quality-gate.sh")
OK = 'node -e "process.exit(0)"'


def project(tmp_path: Path, **scripts: str) -> Path:
    p = tmp_path / "app"
    p.mkdir()
    base = {"build": OK, "lint": OK, "test": OK}
    base.update(scripts)
    write_json(p / "package.json", {"name": "app", "version": "1.0.0", "private": True,
                                    "scripts": {k: v for k, v in base.items() if v is not None}})
    (p / ".gitignore").write_text("node_modules/\n")
    return p


def gate(p: Path, *args: str):
    return run(["bash", GATE, "--project-dir", str(p), *args], timeout=600)


def result(p: Path) -> dict:
    return json.loads((p / ".onecommand" / "gate" / "result.json").read_text())


def test_all_static_steps_pass(tmp_path):
    p = project(tmp_path)
    out = gate(p, "--stage", "static")
    assert out.returncode == 0, out.stdout + out.stderr
    r = result(p)
    assert r["passed"] is True and r["failed_steps"] == []
    steps = {s["step"]: s["status"] for s in r["steps"]}
    assert steps.pop("audit") in ("pass", "skipped")  # skipped when the registry is unreachable
    assert steps == {"install": "pass", "prisma": "skipped", "typecheck": "skipped",
                     "lint": "pass", "build": "pass", "unit": "pass"}
    assert ".onecommand/" in (p / ".gitignore").read_text()


def test_failing_step_fails_the_gate_with_real_exit_code(tmp_path):
    # The pre-v1.4 test-agent ran `cmd | tee log; $?` and saw tee's 0 here.
    p = project(tmp_path, build='node -e "console.error(\'Error: Module not found: ./missing\'); process.exit(1)"')
    out = gate(p, "--stage", "static")
    assert out.returncode == 1
    r = result(p)
    assert r["passed"] is False and r["failed_steps"] == ["build"]
    build = next(s for s in r["steps"] if s["step"] == "build")
    assert build["exit_code"] == 1
    errors = (p / ".onecommand" / "gate" / "errors.txt").read_text()
    assert "===== build" in errors and "Module not found: ./missing" in errors


def test_lint_errors_fail_the_gate(tmp_path):
    p = project(tmp_path, lint='node -e "console.log(\'12:5  error  no-unused-vars\'); process.exit(1)"')
    out = gate(p, "--stage", "static")
    assert out.returncode == 1
    assert result(p)["failed_steps"] == ["lint"]


def test_npm_placeholder_test_script_counts_as_no_tests(tmp_path):
    p = project(tmp_path, test='echo "Error: no test specified" && exit 1')
    out = gate(p, "--stage", "static")
    assert out.returncode == 0, out.stdout
    unit = next(s for s in result(p)["steps"] if s["step"] == "unit")
    assert unit["status"] == "skipped"


def test_install_is_cached_until_manifests_change(tmp_path):
    p = project(tmp_path)
    assert gate(p, "--stage", "static").returncode == 0
    gate(p, "--stage", "static")
    assert next(s for s in result(p)["steps"] if s["step"] == "install")["status"] == "skipped"
    data = json.loads((p / "package.json").read_text())
    data["description"] = "changed"
    write_json(p / "package.json", data)
    gate(p, "--stage", "static")
    assert next(s for s in result(p)["steps"] if s["step"] == "install")["status"] == "pass"


def test_all_stage_skips_e2e_when_static_fails(tmp_path):
    p = project(tmp_path, build='node -e "process.exit(2)"')
    out = gate(p, "--stage", "all")
    assert out.returncode == 1
    e2e = next(s for s in result(p)["steps"] if s["step"] == "e2e")
    assert e2e["status"] == "skipped"


def test_e2e_without_playwright_config_fails_with_guidance(tmp_path):
    p = project(tmp_path)
    write_json(p / ".onecommand-spec.json", {"acceptance_criteria": []})
    out = gate(p, "--stage", "e2e")
    assert out.returncode == 1
    assert "acceptance-tester" in (p / ".onecommand" / "gate" / "errors.txt").read_text()


def test_no_package_json_is_not_applicable(tmp_path):
    out = gate(tmp_path, "--stage", "static")
    assert out.returncode == 3
    assert result(tmp_path)["not_applicable"] is True


@pytest.mark.parametrize("args", [["--stage", "nope"], ["--bogus"], ["--project-dir", "/does/not/exist"]])
def test_usage_errors(tmp_path, args):
    assert run(["bash", GATE, *args]).returncode == 2


# ─── DATABASE_URL resolution ──────────────────────────────────────────────────

def resolve_db_url(tmp_path: Path, files: dict[str, str], preset: str | None = None) -> str:
    for name, content in files.items():
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    fn = run(["sed", "-n", "/^ensure_database_url()/,/^}/p", GATE]).stdout
    script = fn + '\ndebug(){ :; }\nensure_database_url\nprintf "%s" "${DATABASE_URL:-<unset>}"\n'
    env = {"DATABASE_URL": preset} if preset is not None else {}
    cmd = ["bash", "-c", script] if preset is not None else ["env", "-u", "DATABASE_URL", "bash", "-c", script]
    return run(cmd, cwd=tmp_path, env=env).stdout


@pytest.mark.parametrize("files,expected", [
    ({".env.local": 'DATABASE_URL="file:./dev.db"\n'}, "file:./dev.db"),
    ({".env": "export DATABASE_URL='postgresql://u:p@h:5432/x'\n"}, "postgresql://u:p@h:5432/x"),
    ({".env": "FOO=1\nDATABASE_URL = mysql://a\n"}, "mysql://a"),
    ({".env.local": "DATABASE_URL=file:local.db\n", ".env": "DATABASE_URL=file:env.db\n"}, "file:local.db"),
    ({"prisma/schema.prisma": 'datasource db {\n  provider = "sqlite"\n}\n'}, "<unset>"),
    ({"prisma/schema.prisma": 'datasource db {\n  provider = "postgresql"\n}\n'},
     "postgresql://postgres:postgres@localhost:5432/devdb"),
])
def test_database_url_resolution(tmp_path, files, expected):
    assert resolve_db_url(tmp_path, files) == expected


def test_preset_database_url_wins(tmp_path):
    assert resolve_db_url(tmp_path, {".env": "DATABASE_URL=file:x.db\n"}, preset="postgresql://keep") == "postgresql://keep"


def test_audit_can_be_disabled(tmp_path):
    p = project(tmp_path)
    assert gate(p, "--stage", "static", "--no-audit").returncode == 0
    assert next(s for s in result(p)["steps"] if s["step"] == "audit")["status"] == "skipped"


@pytest.mark.skipif(os.environ.get("ONECOMMAND_E2E_TESTS") != "1", reason="needs the npm registry")
def test_unreachable_registry_skips_audit_without_leaving_errors(tmp_path):
    # Without dependencies npm audit never contacts the registry, so use a tiny clean one.
    p = project(tmp_path)
    data = json.loads((p / "package.json").read_text())
    data["dependencies"] = {"is-number": "7.0.0"}
    write_json(p / "package.json", data)
    assert gate(p, "--stage", "static").returncode == 0  # install once while the registry is reachable
    out = run(["bash", GATE, "--project-dir", str(p), "--stage", "static"],
              env={"npm_config_registry": "http://127.0.0.1:9"}, timeout=600)
    assert out.returncode == 0, out.stdout
    audit = next(s for s in result(p)["steps"] if s["step"] == "audit")
    assert audit["status"] == "skipped"
    assert "audit" not in (p / ".onecommand" / "gate" / "errors.txt").read_text()


def with_dependency(tmp_path: Path, deps: dict) -> Path:
    p = project(tmp_path)
    data = json.loads((p / "package.json").read_text())
    data["dependencies"] = deps
    write_json(p / "package.json", data)
    return p


@pytest.mark.skipif(os.environ.get("ONECOMMAND_E2E_TESTS") != "1", reason="needs the npm registry")
def test_critical_advisory_fails_the_gate(tmp_path):
    p = with_dependency(tmp_path, {"lodash": "4.17.11"})  # prototype pollution, critical
    out = gate(p, "--stage", "static")
    assert out.returncode == 1
    assert result(p)["failed_steps"] == ["audit"]
    assert "lodash:critical" in (p / ".onecommand" / "gate" / "errors.txt").read_text()


@pytest.mark.skipif(os.environ.get("ONECOMMAND_E2E_TESTS") != "1", reason="needs the npm registry")
def test_high_advisory_warns_by_default_and_blocks_at_level_high(tmp_path):
    p = with_dependency(tmp_path, {"prisma": "6.19.3"})  # deepmerge-ts via @prisma/config: high
    assert gate(p, "--stage", "static").returncode == 0
    r = result(p)
    assert next(s for s in r["steps"] if s["step"] == "audit")["status"] == "warn"
    assert any("deepmerge-ts:high" in w for w in r["warnings"])
    assert gate(p, "--stage", "static", "--audit-level", "high").returncode == 1


def test_invalid_audit_level_is_a_usage_error(tmp_path):
    assert gate(project(tmp_path), "--audit-level", "low").returncode == 2
