"""hooks/ml-gate.py — verdict for AI/ML training projects.

A stdlib-only project trains a real (tiny) nearest-centroid classifier, writes its
metrics and serves /health and /predict, so the whole gate runs offline in seconds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import py, write_json

PY = sys.executable

TRAIN = '''
import json, random, sys
from pathlib import Path

def data(n, seed):
    rnd = random.Random(seed)
    rows = []
    for _ in range(n):
        label = rnd.randint(0, 1)
        rows.append(([rnd.gauss(2.0 * label, NOISE), rnd.gauss(-2.0 * label, NOISE)], label))
    return rows

def centroids(rows):
    out = {}
    for label in (0, 1):
        pts = [x for x, y in rows if y == label]
        out[label] = [sum(p[i] for p in pts) / len(pts) for i in range(2)]
    return out

def predict(c, x):
    return min(c, key=lambda k: sum((x[i] - c[k][i]) ** 2 for i in range(2)))

NOISE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
model = centroids(data(200, 1))
test = data(100, 2)
acc = sum(predict(model, x) == y for x, y in test) / len(test)
Path("runs/smoke").mkdir(parents=True, exist_ok=True)
Path("runs/smoke/metrics.json").write_text(json.dumps({"accuracy": acc}))
Path("model.json").write_text(json.dumps(model))
print("accuracy", acc)
'''

SERVE = '''
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

model = json.load(open("model.json"))

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        self.reply(200, {"status": "ok"}) if self.path == "/health" else self.reply(404, {})
    def do_POST(self):
        x = json.loads(self.rfile.read(int(self.headers["content-length"])))["features"]
        label = min(model, key=lambda k: sum((x[i] - model[k][i]) ** 2 for i in range(2)))
        self.reply(200, {KEYS})

HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
'''


def project(tmp_path: Path, *, noise: float = 0.5, response: str = '"label": int(label), "score": 1.0',
            smoke_min: float = 0.8, commands: dict | None = None, card: bool = True) -> Path:
    p = tmp_path / "ml"
    p.mkdir(parents=True)
    (p / "train.py").write_text(TRAIN)
    (p / "serve.py").write_text(SERVE.replace("{KEYS}", "{" + response + "}"))
    if card:
        (p / "MODEL_CARD.md").write_text("# Model card\nDataset: synthetic. License: MIT. accuracy on test. Limitations: toy.\n")
    cmds = {"install": f"{PY} -c 'print(\"deps ok\")'", "lint": None, "test": f"{PY} -c 'assert 1 + 1 == 2'",
            "train": f"{PY} train.py {noise}", "serve": f"{PY} serve.py"}
    cmds.update(commands or {})
    write_json(p / ".onecommand-spec.json", {
        "project_name": "Tiny", "app_type": "ml", "build_targets": ["ml"],
        "ml": {"task": "tabular-classification", "package": "tiny",
               "metric": {"name": "accuracy", "target": 0.95, "smoke_min": smoke_min},
               "metrics_file": "runs/smoke/metrics.json",
               "sample_input": {"features": [2.0, -2.0]}, "sample_expect_keys": ["label", "score"],
               "commands": cmds}})
    return p


def gate(p: Path, *args: str):
    return py("ml-gate.py", "--project-dir", str(p), *args, timeout=300)


def result(p: Path) -> dict:
    return json.loads((p / ".onecommand" / "gate" / "result.json").read_text())


def test_trained_and_served_model_passes(tmp_path):
    p = project(tmp_path)
    r = gate(p)
    assert r.returncode == 0, r.stdout + (p / ".onecommand/gate/errors.txt").read_text()
    res = result(p)
    steps = {s["step"]: s["status"] for s in res["steps"]}
    assert steps == {"install": "pass", "lint": "skipped", "test": "pass", "train": "pass", "metric": "pass",
                     "model-card": "pass", "serve": "pass"}
    assert res["passed"] and res["ml"]["metric"]["value"] > 0.8 and res["ml"]["metric"]["target"] == 0.95
    assert "full-training target 0.95" in r.stdout


def test_model_that_does_not_learn_fails_on_the_metric(tmp_path):
    p = project(tmp_path, noise=8.0)  # classes overlap completely
    r = gate(p)
    assert r.returncode == 1
    assert result(p)["failed_steps"] == ["metric"]
    assert "does not learn on the smoke data" in (p / ".onecommand/gate/errors.txt").read_text()


def test_lower_is_better_metrics(tmp_path):
    p = project(tmp_path, smoke_min=0.5)
    spec = json.loads((p / ".onecommand-spec.json").read_text())
    spec["ml"]["metric"].update(higher_is_better=False, smoke_min=0.05)
    write_json(p / ".onecommand-spec.json", spec)
    assert gate(p).returncode == 1 and result(p)["failed_steps"] == ["metric"]


def test_missing_metric_file_or_key(tmp_path):
    p = project(tmp_path, commands={"train": f"{PY} -c 'print(1)'"})
    r = gate(p)
    assert r.returncode == 1 and "was not written by the smoke training" in r.stdout
    p2 = project(tmp_path / "b", commands={"train": f"{PY} -c \"import os,json; os.makedirs('runs/smoke'); "
                                                    f"json.dump({{'loss': 1}}, open('runs/smoke/metrics.json','w'))\""})
    r = gate(p2)
    assert r.returncode == 1 and "has no numeric 'accuracy' (keys: loss)" in r.stdout


def test_prediction_without_expected_keys_fails(tmp_path):
    p = project(tmp_path, response='"prediction": int(label)')
    r = gate(p)
    assert r.returncode == 1 and result(p)["failed_steps"] == ["serve"]
    assert "lacks label, score" in (p / ".onecommand/gate/errors.txt").read_text()


def test_server_that_crashes_is_reported(tmp_path):
    p = project(tmp_path, commands={"serve": f"{PY} -c 'raise SystemExit(\"ImportError: no module named fastapi\")'"})
    r = gate(p, "--serve-timeout", "20")
    assert r.returncode == 1 and "server exited" in r.stdout
    assert "no module named fastapi" in (p / ".onecommand/gate/errors.txt").read_text()


def test_failed_install_stops_the_gate(tmp_path):
    p = project(tmp_path, commands={"install": f"{PY} -c 'raise SystemExit(\"error: resolution failed\")'"})
    assert gate(p).returncode == 1
    assert [s["step"] for s in result(p)["steps"]] == ["install"]


def test_failing_tests_are_extracted(tmp_path):
    p = project(tmp_path, commands={"test": f"{PY} -c \"print('FAILED tests/test_data.py::test_split - assert 0.7 == 0.8'); raise SystemExit(1)\""})
    assert gate(p).returncode == 1
    assert "FAILED tests/test_data.py::test_split" in (p / ".onecommand/gate/errors.txt").read_text()


def test_missing_model_card_is_a_warning(tmp_path):
    p = project(tmp_path, card=False)
    assert gate(p).returncode == 0
    assert any(w.startswith("model-card: MODEL_CARD.md is missing") for w in result(p)["warnings"])


def test_spec_without_ml_is_not_applicable(tmp_path):
    write_json(tmp_path / ".onecommand-spec.json", {"project_name": "web"})
    assert gate(tmp_path).returncode == 3


def test_missing_spec_is_a_usage_error(tmp_path):
    assert gate(tmp_path).returncode == 2


def test_quality_gate_hands_ml_projects_to_the_ml_gate(tmp_path):
    from conftest import HOOKS, run
    p = project(tmp_path)
    out = run(["bash", str(HOOKS / "quality-gate.sh"), "--project-dir", str(p), "--stage", "all"], timeout=300)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "ML GATE PASSED" in out.stdout and result(p)["stage"] == "ml"
