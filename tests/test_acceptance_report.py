"""hooks/acceptance-report.py — spec validation and Playwright → criteria mapping."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from conftest import VALID_SPEC, py, write_json


def spec_file(tmp_path: Path, spec: dict) -> Path:
    return write_json(tmp_path / "spec.json", spec)


def pw_spec(title: str, status: str, error: str = "", file: str = "notes.spec.ts") -> dict:
    results = [{"status": "failed", "error": {"message": error}}] if error else [{"status": "passed"}]
    return {"title": title, "file": file, "tests": [{"status": status, "results": results}]}


def pw_report(*specs: dict) -> dict:
    return {"suites": [{"title": "notes.spec.ts", "file": "notes.spec.ts", "specs": list(specs)}], "errors": []}


def report(tmp_path: Path, spec: dict, results: dict | None, *extra: str):
    s = spec_file(tmp_path, spec)
    r = tmp_path / "pw.json"
    if results is not None:
        write_json(r, results)
    out = tmp_path / "acc.json"
    proc = py("acceptance-report.py", "report", "--spec", str(s), "--results", str(r),
              "--out", str(out), "--markdown", str(tmp_path / "acc.md"), *extra)
    data = json.loads(out.read_text()) if out.exists() else None
    return proc, data


# ─── validate ─────────────────────────────────────────────────────────────────

def test_valid_spec_passes(tmp_path):
    proc = py("acceptance-report.py", "validate", "--spec", str(spec_file(tmp_path, VALID_SPEC)))
    assert proc.returncode == 0, proc.stdout
    assert "spec OK — 4 criteria (3 must)" in proc.stdout


def test_missing_criteria_fails(tmp_path):
    spec = {k: v for k, v in VALID_SPEC.items() if k != "acceptance_criteria"}
    proc = py("acceptance-report.py", "validate", "--spec", str(spec_file(tmp_path, spec)))
    assert proc.returncode == 1
    assert "no acceptance_criteria" in proc.stdout


def test_feature_without_must_criterion_fails(tmp_path):
    spec = copy.deepcopy(VALID_SPEC)
    spec["features"].append("search")
    proc = py("acceptance-report.py", "validate", "--spec", str(spec_file(tmp_path, spec)))
    assert proc.returncode == 1
    assert "feature 'search' has no must-criterion" in proc.stdout


def test_malformed_criteria_are_reported(tmp_path):
    spec = copy.deepcopy(VALID_SPEC)
    spec["acceptance_criteria"][0]["id"] = "X1"
    spec["acceptance_criteria"][1]["priority"] = "may"
    spec["acceptance_criteria"][2]["id"] = "AC-001"
    del spec["acceptance_criteria"][3]["expected"]
    proc = py("acceptance-report.py", "validate", "--spec", str(spec_file(tmp_path, spec)))
    assert proc.returncode == 1
    for needle in ("must look like AC-001", "priority must be one of", "missing fields: expected"):
        assert needle in proc.stdout


def test_vague_wording_is_a_warning_not_an_error(tmp_path):
    spec = copy.deepcopy(VALID_SPEC)
    spec["acceptance_criteria"][0]["title"] = "Login works properly"
    proc = py("acceptance-report.py", "validate", "--spec", str(spec_file(tmp_path, spec)))
    assert proc.returncode == 0
    assert "vague wording" in proc.stdout


def test_web_build_needs_automated_criteria(tmp_path):
    spec = copy.deepcopy(VALID_SPEC)
    for c in spec["acceptance_criteria"]:
        c["verification"] = "manual"
    proc = py("acceptance-report.py", "validate", "--spec", str(spec_file(tmp_path, spec)))
    assert proc.returncode == 1
    assert "no automated" in proc.stdout


def test_invalid_json_is_a_usage_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    proc = py("acceptance-report.py", "validate", "--spec", str(bad))
    assert proc.returncode == 2


# ─── report ───────────────────────────────────────────────────────────────────

def all_pass():
    return pw_report(pw_spec("AC-001: lands on notes", "expected"),
                     pw_spec("AC-002: listed after reload", "expected"),
                     pw_spec("AC-003: 401 without session", "expected"))


def test_all_blocking_passed(tmp_path):
    proc, data = report(tmp_path, VALID_SPEC, all_pass())
    assert proc.returncode == 0, proc.stdout
    assert data["passed"] is True
    assert data["summary"]["blocking_passed"] == data["summary"]["blocking"] == 3
    status = {c["id"]: c["status"] for c in data["criteria"]}
    assert status == {"AC-001": "passed", "AC-002": "passed", "AC-003": "passed", "AC-004": "manual"}
    assert "ALL BLOCKING CRITERIA PASSED" in (tmp_path / "acc.md").read_text()


def test_failed_test_fails_the_criterion(tmp_path):
    results = all_pass()
    results["suites"][0]["specs"][1] = pw_spec("AC-002: listed", "unexpected", "\x1b[31mExpected 'Milk'\x1b[0m")
    proc, data = report(tmp_path, VALID_SPEC, results)
    assert proc.returncode == 1
    crit = next(c for c in data["criteria"] if c["id"] == "AC-002")
    assert crit["status"] == "failed"
    assert crit["tests"][0]["error"] == "Expected 'Milk'"  # ANSI colours stripped


def test_missing_test_fails(tmp_path):
    results = pw_report(pw_spec("AC-001: x", "expected"), pw_spec("AC-003: y", "expected"),
                        pw_spec("helper smoke test", "expected"))
    proc, data = report(tmp_path, VALID_SPEC, results)
    assert proc.returncode == 1
    assert next(c for c in data["criteria"] if c["id"] == "AC-002")["status"] == "missing"
    assert data["summary"]["unmapped_tests"] == 1


def test_skipped_only_counts_as_failure(tmp_path):
    results = all_pass()
    results["suites"][0]["specs"][0]["tests"][0]["status"] = "skipped"
    proc, data = report(tmp_path, VALID_SPEC, results)
    assert proc.returncode == 1
    assert next(c for c in data["criteria"] if c["id"] == "AC-001")["status"] == "skipped"


def test_flaky_passes_by_default_but_not_strict(tmp_path):
    results = all_pass()
    results["suites"][0]["specs"][0]["tests"][0]["status"] = "flaky"
    proc, data = report(tmp_path, VALID_SPEC, results)
    assert proc.returncode == 0
    assert data["summary"]["flaky"] == 1
    proc, data = report(tmp_path, VALID_SPEC, results, "--strict-flaky")
    assert proc.returncode == 1


def test_crashed_run_without_results_fails(tmp_path):
    proc, data = report(tmp_path, VALID_SPEC, None)
    assert proc.returncode == 1
    assert data["passed"] is False
    assert {c["status"] for c in data["criteria"] if c["verification"] != "manual"} == {"not_run"}


def test_nested_suites_and_multiple_ids_in_one_title(tmp_path):
    results = {"suites": [{"title": "a.spec.ts", "file": "a.spec.ts", "suites": [
        {"title": "notes", "specs": [pw_spec("AC-001 + AC-002: full flow", "expected", file="a.spec.ts")]}]},
        {"title": "b.spec.ts", "file": "b.spec.ts", "specs": [pw_spec("AC-003: api", "expected", file="b.spec.ts")]}]}
    proc, data = report(tmp_path, VALID_SPEC, results)
    assert proc.returncode == 0, proc.stdout
    assert data["summary"]["blocking_passed"] == 3


def test_report_rejects_invalid_spec(tmp_path):
    spec = copy.deepcopy(VALID_SPEC)
    spec["features"].append("search")
    proc, _ = report(tmp_path, spec, all_pass())
    assert proc.returncode == 2
