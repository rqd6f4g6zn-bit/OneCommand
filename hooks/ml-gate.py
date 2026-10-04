#!/usr/bin/env python3
"""OneCommand ML gate — the pass/fail verdict for AI/ML training projects.

quality-gate.sh hands over to this script when the spec's build_targets contain
"ml". A training project is only "done" when it installs, passes lint and tests,
actually trains on the smoke configuration, reaches the smoke threshold of its
metric, writes a model card, and serves predictions through its API.

Spec section (written by spec-analyzer, see skills/ml-builder):

  "ml": {
    "task": "text-classification",            # see ml-builder for the task templates
    "package": "ticket_router",               # Python package under src/
    "base_model": "distilbert-base-multilingual-cased",
    "dataset": {"source": "hf:…", "license": "CC-BY-4.0"},
    "metric": {"name": "macro_f1", "target": 0.85, "smoke_min": 0.4, "higher_is_better": true},
    "metrics_file": "runs/smoke/metrics.json",
    "serve": true,
    "sample_input": {"text": "Mein Passwort funktioniert nicht"},
    "sample_expect_keys": ["label", "score"],
    "commands": {"install": "uv sync", …}       # optional overrides, null skips a step
  }

Steps: install → lint → test → train (smoke) → metric → model-card → serve.
Output: <project>/.onecommand/gate/result.json + errors.txt + <step>.log — the same
format as quality-gate.sh, so test-agent, self-healer and the delivery report
read it unchanged.

Exit codes: 0 passed · 1 failed · 2 usage error · 3 not applicable (no "ml" in the spec)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULTS = {
    "install": "uv sync",
    "lint": "uv run ruff check .",
    "test": "uv run pytest -q",
    "train": "uv run python -m {package}.train --config configs/smoke.yaml",
    "serve": "uv run uvicorn {package}.serve:app --host 127.0.0.1 --port {port}",
}
ERROR_LINE = re.compile(r"(Error|error:|ERROR|Traceback|FAILED|failed|assert|E   )")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Gate:
    def __init__(self, project: Path, out: Path, verbose: bool):
        self.project, self.out, self.verbose = project, out, verbose
        self.steps: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.started = now()
        out.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str) -> None:
        print(f"[ml-gate] {msg}", flush=True)

    def record(self, step: str, status: str, rc: int | None = None, duration: float = 0,
               log: Path | None = None, reason: str | None = None) -> None:
        self.steps.append({"step": step, "status": status, "exit_code": rc, "duration_s": int(duration),
                           "log": str(log) if log else None, "reason": reason})
        mark = {"pass": "✓", "fail": "✗", "warn": "⚠", "skipped": "○"}[status]
        self.log(f"  {mark} {step}" + (f" — {reason}" if reason else ""))

    def fail_text(self, step: str, text: str) -> None:
        self.errors.append(f"===== {step} =====\n{text.rstrip()}\n")

    def run(self, step: str, command: str, timeout: int) -> bool:
        logfile = self.out / f"{step}.log"
        self.log(f"▶ {step}: {command}")
        start = time.monotonic()
        with open(logfile, "w", encoding="utf-8") as fh:
            try:
                rc = subprocess.run(command, shell=True, cwd=self.project, stdout=fh, stderr=subprocess.STDOUT,
                                    timeout=timeout, env={**os.environ, "PYTHONUNBUFFERED": "1"}).returncode
            except subprocess.TimeoutExpired:
                rc = 124
        duration = time.monotonic() - start
        if rc == 0:
            self.record(step, "pass", 0, duration, logfile)
            return True
        reason = f"timed out after {timeout}s" if rc == 124 else f"exit code {rc}"
        self.record(step, "fail", rc, duration, logfile, reason)
        lines = logfile.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [f"{i + 1}:{line}" for i, line in enumerate(lines) if ERROR_LINE.search(line)][:60]
        self.fail_text(f"{step} (full log: {logfile})", "\n".join(hits or lines[-40:]))
        return False

    def write(self, spec_ml: dict[str, Any], passed: bool, metric: dict[str, Any] | None) -> None:
        result = {
            "version": 1, "stage": "ml", "project_dir": str(self.project), "package_manager": "uv",
            "started_at": self.started, "finished_at": now(), "passed": passed, "not_applicable": False,
            "failed_steps": [s["step"] for s in self.steps if s["status"] == "fail"],
            "warnings": [f"{s['step']}: {s['reason']}" for s in self.steps if s["status"] == "warn"],
            "steps": self.steps,
            "ml": {"task": spec_ml.get("task"), "metric": metric},
        }
        tmp = self.out / ".result.json.tmp"
        tmp.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.out / "result.json")
        (self.out / "errors.txt").write_text("\n".join(self.errors), encoding="utf-8")


def command_for(ml: dict[str, Any], step: str, port: int) -> str | None:
    commands = ml.get("commands") or {}
    if step in commands:
        cmd = commands[step]
        if cmd is None:
            return None
    else:
        cmd = DEFAULTS[step]
    # Only these two placeholders — commands may contain other braces (Python dicts, shell ${VAR}).
    return str(cmd).replace("{package}", str(ml.get("package", "app"))).replace("{port}", str(port))


def read_metric(project: Path, ml: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    metric = ml.get("metric") or {}
    path = project / (ml.get("metrics_file") or "runs/smoke/metrics.json")
    if not path.exists():
        return None, f"{path.relative_to(project)} was not written by the smoke training"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, f"{path.relative_to(project)} is not valid JSON: {exc}"
    name = metric.get("name")
    if name not in data or not isinstance(data[name], (int, float)):
        return None, f"{path.relative_to(project)} has no numeric '{name}' (keys: {', '.join(sorted(data)) or 'none'})"
    value = float(data[name])
    higher = metric.get("higher_is_better", True)
    smoke_min = metric.get("smoke_min")
    ok = smoke_min is None or (value >= smoke_min if higher else value <= smoke_min)
    return {"name": name, "value": value, "smoke_min": smoke_min, "target": metric.get("target"),
            "higher_is_better": higher, "smoke_passed": ok, "file": str(path.relative_to(project))}, None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method: str, url: str, body: Any = None, timeout: int = 30) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — local URL
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc)


def serve_check(gate: Gate, ml: dict[str, Any], start_timeout: int) -> bool:
    port = free_port()
    command = command_for(ml, "serve", port)
    if not command:
        gate.record("serve", "skipped", reason="commands.serve is null")
        return True
    logfile = gate.out / "serve.log"
    gate.log(f"▶ serve: {command}")
    started = time.monotonic()
    fh = open(logfile, "w", encoding="utf-8")
    proc = subprocess.Popen(command, shell=True, cwd=gate.project, stdout=fh, stderr=subprocess.STDOUT,
                            start_new_session=True, env={**os.environ, "PORT": str(port)})
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + start_timeout
        status = 0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            status, _ = http("GET", f"{base}/health", timeout=5)
            if status == 200:
                break
            time.sleep(1)
        if status != 200:
            fh.flush()
            tail = "\n".join(logfile.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])
            reason = "server exited" if proc.poll() is not None else f"GET /health did not return 200 within {start_timeout}s"
            gate.record("serve", "fail", proc.returncode, time.monotonic() - started, logfile, reason)
            gate.fail_text("serve", f"{reason}\n{tail}")
            return False
        sample = ml.get("sample_input")
        if sample is None:
            gate.record("serve", "fail", None, time.monotonic() - started, logfile, "spec ml.sample_input is missing")
            gate.fail_text("serve", "Add ml.sample_input (a request body for POST /predict) to the spec.")
            return False
        status, body = http("POST", f"{base}/predict", sample, timeout=120)
        problem = None
        if status != 200:
            problem = f"POST /predict returned {status}: {body[:500]}"
        else:
            try:
                payload = json.loads(body)
            except ValueError:
                payload, problem = None, f"POST /predict did not return JSON: {body[:300]}"
            missing = [k for k in ml.get("sample_expect_keys") or [] if not isinstance(payload, dict) or k not in payload]
            if payload is not None and missing:
                problem = f"POST /predict response lacks {', '.join(missing)}: {body[:300]}"
        if problem:
            gate.record("serve", "fail", None, time.monotonic() - started, logfile, problem.split(":")[0])
            gate.fail_text("serve", problem)
            return False
        gate.record("serve", "pass", 0, time.monotonic() - started, logfile)
        return True
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        fh.close()


def model_card_check(gate: Gate, ml: dict[str, Any]) -> None:
    card = gate.project / "MODEL_CARD.md"
    if not card.exists():
        gate.record("model-card", "warn", reason="MODEL_CARD.md is missing (intended use, data, license, metrics, limits)")
        return
    text = card.read_text(encoding="utf-8", errors="replace").lower()
    wanted = {"dataset": ("dataset", "daten"), "license": ("license", "lizenz"),
              "metric": (str((ml.get("metric") or {}).get("name", "metric")).lower(),),
              "limitations": ("limitation", "grenzen", "einschränk")}
    missing = [k for k, words in wanted.items() if not any(w in text for w in words)]
    if missing:
        gate.record("model-card", "warn", reason=f"MODEL_CARD.md does not cover: {', '.join(missing)}")
    else:
        gate.record("model-card", "pass")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--spec", default=".onecommand-spec.json")
    parser.add_argument("--out", help="default <project>/.onecommand/gate")
    parser.add_argument("--step-timeout", type=int, default=int(os.environ.get("OC_GATE_STEP_TIMEOUT", 900)))
    parser.add_argument("--train-timeout", type=int, default=int(os.environ.get("OC_ML_TRAIN_TIMEOUT", 1800)),
                        help="seconds for the smoke training (default 1800)")
    parser.add_argument("--serve-timeout", type=int, default=180)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ml-gate] project directory not found: {project}", file=sys.stderr)
        return 2
    spec_path = Path(args.spec) if os.path.isabs(args.spec) else project / args.spec
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[ml-gate] cannot read spec {spec_path}: {exc}", file=sys.stderr)
        return 2
    ml = spec.get("ml")
    if not isinstance(ml, dict):
        print("[ml-gate] spec has no 'ml' section — not an ML project")
        return 3
    gate = Gate(project, Path(args.out).resolve() if args.out else project / ".onecommand" / "gate", args.verbose)
    gate.log(f"Project: {project} · task: {ml.get('task', '?')} · package: {ml.get('package', '?')}")

    ok = True
    for step in ("install", "lint", "test"):
        command = command_for(ml, step, 0)
        if command is None:
            gate.record(step, "skipped", reason=f"commands.{step} is null")
            continue
        if not gate.run(step, command, args.step_timeout):
            ok = False
            if step == "install":
                gate.write(ml, False, None)
                gate.log(f"❌ ML GATE FAILED — errors: {gate.out / 'errors.txt'}")
                return 1

    metric = None
    command = command_for(ml, "train", 0)
    if command is None:
        gate.record("train", "skipped", reason="commands.train is null")
    elif gate.run("train", command, args.train_timeout):
        metric, problem = read_metric(project, ml)
        if problem:
            gate.record("metric", "fail", reason=problem)
            gate.fail_text("metric", problem)
            ok = False
        elif not metric["smoke_passed"]:
            cmp = ">=" if metric["higher_is_better"] else "<="
            reason = f"{metric['name']} = {metric['value']:.4f}, smoke threshold {cmp} {metric['smoke_min']}"
            gate.record("metric", "fail", reason=reason)
            gate.fail_text("metric", f"{reason} — the model does not learn on the smoke data (check labels, "
                                     f"learning rate, data split, preprocessing)")
            ok = False
        else:
            target = f", full-training target {metric['target']}" if metric.get("target") is not None else ""
            gate.record("metric", "pass", reason=f"{metric['name']} = {metric['value']:.4f}{target}")
    else:
        ok = False

    model_card_check(gate, ml)
    if ml.get("serve", True):
        ok = serve_check(gate, ml, args.serve_timeout) and ok
    else:
        gate.record("serve", "skipped", reason="ml.serve is false")

    gate.write(ml, ok, metric)
    gate.log(f"✅ ML GATE PASSED — {gate.out / 'result.json'}" if ok else f"❌ ML GATE FAILED — errors: {gate.out / 'errors.txt'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
