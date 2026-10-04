"""bench/run.py — scoring from OneCommand's own artefacts, dry runs, comparisons."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import REPO, run, write_json

BENCH = [sys.executable, str(REPO / "bench" / "run.py")]


def stream_log(path: Path, *, cost: float, agents: list[bool | None], gate_runs: int, terminated: bool = False) -> Path:
    events = []
    for bg in agents:
        inp = {"subagent_type": "onecommand:test-agent", "description": "x"}
        if bg is not None:
            inp["run_in_background"] = bg
        events.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Agent", "input": inp}]}})
    for _ in range(gate_runs):
        events.append({"type": "assistant", "parent_tool_use_id": "sub", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "bash $OC_ROOT/hooks/quality-gate.sh --stage e2e"}}]}})
    events.append({"type": "result", "subtype": "success", "num_turns": 7, "total_cost_usd": cost / 2})
    events.append({"type": "result", "subtype": "success", "num_turns": 3, "total_cost_usd": cost})
    lines = [json.dumps(e) for e in events]
    if terminated:
        lines.append("Background tasks still running after 600s; terminating.")
    path.write_text("\n".join(lines) + "\nclaude exit=0\n")
    return path


def project(tmp_path: Path, *, passed: bool, acc: tuple[int, int], delivery: bool = True) -> Path:
    p = tmp_path / "app"
    write_json(p / ".onecommand" / "gate" / "result.json", {
        "passed": passed, "stage": "all", "failed_steps": [] if passed else ["e2e", "acceptance"],
        "acceptance": {"blocking_passed": acc[0], "blocking": acc[1], "manual": 0, "flaky": 1}})
    if delivery:
        (p / "ONECOMMAND-DELIVERY.md").write_text("# report")
    return p


def collect(project_dir: Path, logs: list[Path], wm: dict, tmp_path: Path):
    wm_path = write_json(tmp_path / "wm.json", wm)
    out = run([*BENCH, "collect", "--project-dir", str(project_dir), "--log", *map(str, logs),
               "--working-memory", str(wm_path), "--minutes", "42"])
    return out, json.loads(out.stdout)


def test_green_finished_build_scores_100(tmp_path):
    p = project(tmp_path, passed=True, acc=(18, 18))
    log = stream_log(tmp_path / "a.log", cost=3.0, agents=[False, False, None], gate_runs=4)
    out, m = collect(p, [log], {"phases_completed": list(range(1, 9))}, tmp_path)
    assert out.returncode == 0
    assert m["score"] == 100.0 and m["finished"] and m["delivery_report"]
    assert m["agents"] == 3 and m["foreground_agents"] == 2 and m["gate_runs"] == 4
    assert m["cost_usd"] == 3.0 and m["turns"] == 10 and m["wall_minutes"] == 42.0
    assert m["terminated"] is False


def test_failed_gate_scores_by_acceptance_ratio(tmp_path):
    p = project(tmp_path, passed=False, acc=(11, 18), delivery=False)
    log = stream_log(tmp_path / "a.log", cost=1.0, agents=[None], gate_runs=1, terminated=True)
    out, m = collect(p, [log], {"phases_completed": [1, 2, 3]}, tmp_path)
    assert out.returncode == 1
    assert m["score"] == round(40 * 11 / 18, 1)
    assert m["terminated"] is True and m["failed_steps"] == ["e2e", "acceptance"]


def test_resumed_build_sums_cost_across_logs(tmp_path):
    p = project(tmp_path, passed=True, acc=(3, 3))
    a = stream_log(tmp_path / "a.log", cost=2.0, agents=[None], gate_runs=1)
    b = stream_log(tmp_path / "b.log", cost=1.5, agents=[False], gate_runs=2)
    _, m = collect(p, [a, b], {"phases_completed": list(range(1, 9))}, tmp_path)
    assert m["cost_usd"] == 3.5 and m["gate_runs"] == 3 and m["agents"] == 2


def test_missing_gate_is_reported(tmp_path):
    p = tmp_path / "app"
    p.mkdir()
    log = stream_log(tmp_path / "a.log", cost=0.5, agents=[], gate_runs=0)
    out, m = collect(p, [log], {}, tmp_path)
    assert out.returncode == 1 and m["score"] == 0 and m["failed_steps"] == ["gate never ran"]


def test_dry_run_writes_commands_and_results(tmp_path):
    out = run([*BENCH, "run", "--dry-run", "--only", "notes", "shop", "--out", str(tmp_path)])
    assert out.returncode == 0, out.stderr
    assert out.stdout.count("claude --plugin-dir") == 2
    assert "--dangerously-skip-permissions" not in out.stdout  # only with --skip-permissions
    assert len(list(tmp_path.glob("*/results.json"))) == 1


def test_unknown_prompt_is_a_usage_error(tmp_path):
    assert run([*BENCH, "run", "--dry-run", "--only", "nope", "--out", str(tmp_path)]).returncode == 2


def test_prompt_sets_reference_existing_prompts():
    data = json.loads((REPO / "bench" / "prompts.json").read_text())
    ids = {p["id"] for p in data["prompts"]}
    assert len(ids) == len(data["prompts"])
    for name, members in data["sets"].items():
        assert set(members) <= ids, name
    assert {p["type"] for p in data["prompts"]} >= {"web", "mobile", "game", "os"}


def build(id_: str, score: float, acc=(3, 3)) -> dict:
    return {"id": id_, "type": "web", "score": score, "acceptance": {"passed": acc[0], "total": acc[1]},
            "wall_minutes": 40, "cost_usd": 3.0}


def test_compare_flags_regressions(tmp_path):
    before = write_json(tmp_path / "b.json", {"run_id": "r1", "plugin_version": "1.5.0", "mean_score": 90,
                                              "builds": [build("notes", 100), build("shop", 80)]})
    after = write_json(tmp_path / "a.json", {"run_id": "r2", "plugin_version": "1.5.1", "mean_score": 85,
                                             "builds": [build("notes", 100), build("shop", 70, (2, 3)), build("new", 50)]})
    out = run([*BENCH, "compare", str(before), str(after)])
    assert out.returncode == 1
    assert "1 regression(s)" in out.stdout and "3/3→2/3" in out.stdout and "new" in out.stdout
    ok = run([*BENCH, "compare", str(after), str(after)])
    assert ok.returncode == 0
