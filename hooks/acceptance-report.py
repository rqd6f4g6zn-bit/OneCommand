#!/usr/bin/env python3
"""OneCommand acceptance report.

Connects the acceptance criteria in .onecommand-spec.json with real test
results, so "done" means "every must-criterion has a passing test" instead of
"the code compiles".

Subcommands
-----------
validate   Check that a spec carries well-formed acceptance criteria that cover
           every feature. Run by spec-analyzer before Phase 2 starts.
report     Map a Playwright JSON report onto the criteria (test titles carry the
           criterion id, e.g. "AC-003: user can log in") and write a verdict
           per criterion plus a Markdown matrix for the delivery report.

Exit codes: 0 ok / all blocking criteria passed · 1 validation or acceptance
failure · 2 usage or input error.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

LOG = logging.getLogger("acceptance-report")

ID_PATTERN = re.compile(r"^AC-\d{3,}$")
ID_IN_TITLE = re.compile(r"\bAC-\d{3,}\b")
PRIORITIES = ("must", "should")
VERIFICATIONS = ("e2e", "api", "manual")
AUTOMATED = ("e2e", "api")
REQUIRED_FIELDS = ("id", "feature", "title", "priority", "verification", "steps", "expected")
# Words that make a criterion untestable; a criterion must name observable outcomes.
VAGUE_WORDS = re.compile(r"\b(works?|properly|correctly|nice(ly)?|good|fast|user[- ]friendly|intuitive|seamless(ly)?)\b", re.I)


# ─── helpers ──────────────────────────────────────────────────────────────────

def load_json(path: str, what: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"[acceptance] {what} not found: {path}") from None
    except ValueError as exc:
        raise SystemExit(f"[acceptance] {what} is not valid JSON ({path}): {exc}") from None


def write_atomic(path: str, content: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".acc-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)


def spec_features(spec: dict) -> list[str]:
    """Feature names a spec declares, across web, game and OS spec shapes."""
    for key in ("features", "game_features", "os_features"):
        value = spec.get(key)
        if isinstance(value, list) and value:
            return [str(v.get("name", v)) if isinstance(v, dict) else str(v) for v in value]
    return []


# ─── validate ─────────────────────────────────────────────────────────────────

def validate_spec(spec: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    criteria = spec.get("acceptance_criteria")

    if not isinstance(criteria, list) or not criteria:
        return ["spec has no acceptance_criteria list"], warnings

    seen: set[str] = set()
    covered_must: set[str] = set()
    for index, crit in enumerate(criteria):
        where = f"acceptance_criteria[{index}]"
        if not isinstance(crit, dict):
            errors.append(f"{where} is not an object")
            continue
        missing = [f for f in REQUIRED_FIELDS if f not in crit or crit[f] in ("", None, [])]
        if missing:
            errors.append(f"{where} ({crit.get('id', '?')}) missing fields: {', '.join(missing)}")
        cid = str(crit.get("id", ""))
        if cid and not ID_PATTERN.match(cid):
            errors.append(f"{where} id '{cid}' must look like AC-001")
        if cid in seen:
            errors.append(f"duplicate criterion id {cid}")
        seen.add(cid)
        if crit.get("priority") not in PRIORITIES:
            errors.append(f"{cid or where}: priority must be one of {PRIORITIES}")
        if crit.get("verification") not in VERIFICATIONS:
            errors.append(f"{cid or where}: verification must be one of {VERIFICATIONS}")
        for list_field in ("steps", "expected"):
            if list_field in crit and not isinstance(crit[list_field], list):
                errors.append(f"{cid or where}: {list_field} must be a list of strings")
        for text in [crit.get("title", "")] + list(crit.get("expected") or []):
            if isinstance(text, str) and VAGUE_WORDS.search(text):
                warnings.append(f"{cid}: vague wording '{VAGUE_WORDS.search(text).group(0)}' in \"{text}\" — name an observable result")
        if crit.get("priority") == "must":
            covered_must.add(str(crit.get("feature", "")))
            if crit.get("verification") == "manual":
                warnings.append(f"{cid}: must-criterion is manual — it will not be verified automatically")

    features = spec_features(spec)
    automated_targets = any(t in ("web", "mobile") for t in spec.get("build_targets", ["web"]))
    for feature in features:
        if feature not in covered_must:
            errors.append(f"feature '{feature}' has no must-criterion")
    referenced = {str(c["feature"]) for c in criteria if isinstance(c, dict) and c.get("feature")}
    unknown = sorted(referenced - set(features)) if features else []
    for feature in unknown:
        warnings.append(f"criteria reference feature '{feature}' which is not in the spec's feature list")
    if automated_targets and not any(isinstance(c, dict) and c.get("verification") in AUTOMATED for c in criteria):
        errors.append("web/mobile build has no automated (e2e/api) criteria")
    return errors, warnings


def cmd_validate(args: argparse.Namespace) -> int:
    spec = load_json(args.spec, "spec")
    errors, warnings = validate_spec(spec)
    for w in warnings:
        print(f"  ⚠ {w}")
    for e in errors:
        print(f"  ✗ {e}")
    count = len(spec.get("acceptance_criteria") or [])
    if errors:
        print(f"[acceptance] spec INVALID — {len(errors)} error(s), {count} criteria")
        return 1
    must = sum(1 for c in spec["acceptance_criteria"] if c.get("priority") == "must")
    print(f"[acceptance] spec OK — {count} criteria ({must} must) covering {len(spec_features(spec))} features")
    return 0


# ─── report ───────────────────────────────────────────────────────────────────

def iter_tests(suite: dict, parents: list[str], file_hint: str):
    """Yield (title_path, file, test) for every test in a Playwright JSON suite tree."""
    file_name = suite.get("file") or file_hint
    path = parents + ([suite["title"]] if suite.get("title") and suite.get("title") != file_name else [])
    for spec in suite.get("specs", []) or []:
        for test in spec.get("tests", []) or []:
            yield path + [spec.get("title", "")], spec.get("file") or file_name, test
    for child in suite.get("suites", []) or []:
        yield from iter_tests(child, path, file_name)


def test_outcome(test: dict) -> tuple[str, str]:
    """Normalise a Playwright test entry to passed/failed/flaky/skipped plus first error."""
    status = test.get("status")
    results = test.get("results", []) or []
    error = ""
    for res in results:
        err = res.get("error") or (res.get("errors") or [None])[0]
        if err:
            error = re.sub(r"\x1b\[[0-9;]*m", "", err.get("message", "") or err.get("value", "")).strip()
            break
    mapping = {"expected": "passed", "unexpected": "failed", "flaky": "flaky", "skipped": "skipped"}
    if status in mapping:
        return mapping[status], error
    # Older reporters: derive from the last result.
    last = results[-1].get("status") if results else "skipped"
    return ("passed" if last == "passed" else "skipped" if last == "skipped" else "failed"), error


def build_report(spec: dict, results: dict | None, strict_flaky: bool) -> dict:
    criteria = [c for c in spec.get("acceptance_criteria", []) if isinstance(c, dict)]
    by_id: dict[str, list[dict]] = {c["id"]: [] for c in criteria if "id" in c}
    unmapped: list[dict] = []
    run_errors: list[str] = []

    if results is None:
        run_errors.append("no Playwright results — the test run crashed or never started (see e2e.log)")
    else:
        for err in results.get("errors", []) or []:
            run_errors.append(re.sub(r"\x1b\[[0-9;]*m", "", err.get("message", str(err)))[:500])
        for suite in results.get("suites", []) or []:
            for title_path, file_name, test in iter_tests(suite, [], suite.get("file", "")):
                title = " › ".join(t for t in title_path if t)
                outcome, error = test_outcome(test)
                entry = {"title": title, "file": file_name, "status": outcome, "error": error[:1000]}
                ids = set(ID_IN_TITLE.findall(title))
                if not ids:
                    unmapped.append(entry)
                for cid in ids:
                    if cid in by_id:
                        by_id[cid].append(entry)
                    else:
                        unmapped.append({**entry, "unknown_id": cid})

    rows = []
    for crit in criteria:
        cid = crit.get("id", "?")
        tests = by_id.get(cid, [])
        verification = crit.get("verification", "e2e")
        statuses = {t["status"] for t in tests}
        if verification == "manual":
            status = "manual"
        elif results is None:
            status = "not_run"
        elif not tests:
            status = "missing"
        elif "failed" in statuses:
            status = "failed"
        elif statuses == {"skipped"}:
            status = "skipped"
        elif "flaky" in statuses:
            status = "failed" if strict_flaky else "flaky"
        elif "passed" in statuses:
            status = "passed"
        else:
            status = "failed"
        blocking = crit.get("priority") == "must" and verification in AUTOMATED
        ok = status == "passed" or (status == "flaky" and not strict_flaky)
        rows.append({
            "id": cid, "feature": crit.get("feature"), "title": crit.get("title"),
            "priority": crit.get("priority"), "verification": verification,
            "status": "passed" if status == "flaky" and ok else status,
            "flaky": status == "flaky", "blocking": blocking, "ok": ok, "tests": tests,
        })

    blocking_rows = [r for r in rows if r["blocking"]]
    summary = {
        "total": len(rows),
        "blocking": len(blocking_rows),
        "passed": sum(1 for r in rows if r["ok"]),
        "failed": sum(1 for r in rows if r["status"] in ("failed", "not_run")),
        "missing": sum(1 for r in rows if r["status"] == "missing"),
        "skipped": sum(1 for r in rows if r["status"] == "skipped"),
        "manual": sum(1 for r in rows if r["status"] == "manual"),
        "flaky": sum(1 for r in rows if r["flaky"]),
        "blocking_passed": sum(1 for r in blocking_rows if r["ok"]),
        "unmapped_tests": len(unmapped),
    }
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": spec.get("project_name"),
        # A crashed run (no results file) can never pass, even with zero blocking rows.
        "passed": results is not None and bool(blocking_rows) and all(r["ok"] for r in blocking_rows),
        "summary": summary,
        "run_errors": run_errors,
        "criteria": rows,
        "unmapped_tests": unmapped,
    }


ICONS = {"passed": "✅", "failed": "❌", "missing": "⛔", "skipped": "⏭️", "manual": "📝", "not_run": "❌"}


def render_markdown(report: dict) -> str:
    s = report["summary"]
    verdict = "✅ ALL BLOCKING CRITERIA PASSED" if report["passed"] else "❌ ACCEPTANCE NOT MET"
    lines = [
        f"### Acceptance Verification — {verdict}",
        "",
        f"**{s['blocking_passed']}/{s['blocking']}** must-criteria verified by automated tests · "
        f"{s['passed']}/{s['total']} criteria passed · {s['manual']} manual · {s['flaky']} flaky",
        "",
        "| ID | Feature | Criterion | Priority | Status | Test |",
        "|----|---------|-----------|----------|--------|------|",
    ]
    for r in report["criteria"]:
        icon = ICONS.get(r["status"], "❔")
        flag = " (flaky)" if r["flaky"] else ""
        test = r["tests"][0]["file"] if r["tests"] else "—"
        title = str(r["title"]).replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['feature']} | {title} | {r['priority']} | {icon} {r['status']}{flag} | `{test}` |")
    if report["run_errors"]:
        lines += ["", "**Run errors:**"] + [f"- {e}" for e in report["run_errors"]]
    if report["unmapped_tests"]:
        lines += ["", f"_{len(report['unmapped_tests'])} test(s) carry no known criterion id._"]
    return "\n".join(lines) + "\n"


def cmd_report(args: argparse.Namespace) -> int:
    spec = load_json(args.spec, "spec")
    errors, _ = validate_spec(spec)
    if errors:
        for e in errors:
            print(f"  ✗ spec: {e}")
        print("[acceptance] spec invalid — fix .onecommand-spec.json before reporting")
        return 2
    results = load_json(args.results, "Playwright results") if os.path.exists(args.results) else None
    report = build_report(spec, results, args.strict_flaky)
    write_atomic(args.out, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    markdown = render_markdown(report)
    if args.markdown:
        write_atomic(args.markdown, markdown)
    print(markdown)
    for r in report["criteria"]:
        if r["blocking"] and not r["ok"]:
            LOG.info("blocking %s %s: %s", r["id"], r["status"], r["title"])
    return 0 if report["passed"] else 1


# ─── cli ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="validate acceptance criteria in a spec")
    p_val.add_argument("--spec", default=".onecommand-spec.json")
    p_val.set_defaults(func=cmd_validate)

    p_rep = sub.add_parser("report", help="map Playwright results onto acceptance criteria")
    p_rep.add_argument("--spec", default=".onecommand-spec.json")
    p_rep.add_argument("--results", default=".onecommand/gate/playwright.json")
    p_rep.add_argument("--out", default=".onecommand/gate/acceptance.json")
    p_rep.add_argument("--markdown", default=".onecommand/gate/acceptance.md")
    p_rep.add_argument("--strict-flaky", action="store_true", help="treat tests that only passed on retry as failures")
    p_rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="[acceptance] %(levelname)s %(message)s")
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
