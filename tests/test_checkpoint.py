"""hooks/checkpoint.py — resumable build state, compatible with /oc-resume."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import py, write_json


def cp(home: Path, project: Path, *args: str):
    return py("checkpoint.py", "--project-dir", str(project), *args, env={"HOME": str(home)})


def wm(home: Path) -> dict:
    return json.loads((home / ".onecommand" / "brain" / "working_memory.json").read_text())


def make_project(tmp_path: Path) -> Path:
    p = tmp_path / "Notes"
    (p / "src").mkdir(parents=True)
    (p / "src" / "app.ts").write_text("x")
    (p / "node_modules" / "dep").mkdir(parents=True)
    (p / "node_modules" / "dep" / "index.js").write_text("x")
    write_json(p / ".onecommand-spec.json", {"project_name": "Notes", "app_type": "web-app", "features": ["auth"]})
    return p


def test_start_then_phases_produce_resumable_state(tmp_path, home):
    project = make_project(tmp_path)
    assert cp(home, project, "--oc-root", "/opt/oc", "start").returncode == 0
    state = wm(home)
    assert state["project_name"] == "Notes" and state["current_phase"] == 1
    assert state["plugin_root"] == "/opt/oc" and state["project_dir"] == str(project.resolve())

    out = cp(home, project, "phase", "1", "--summary", "Spec: Notes, 18 criteria")
    assert out.returncode == 0 and "Phase 1 saved" in out.stdout
    cp(home, project, "phase", "2", "--summary", "12 pages", "--status", "warn")
    state = wm(home)
    assert state["phases_completed"] == [1, 2] and state["current_phase"] == 3
    assert state["phase_status"]["2"] == "warn"

    brain = home / ".onecommand" / "brain"
    brief = (brain / "resume_brief.md").read_text()
    assert "NEXT: Phase 3" in brief and "Spec: Notes, 18 criteria" in brief and "⚠️ **Phase 2:**" in brief
    manifest = json.loads((brain / "file_manifest.json").read_text())
    assert manifest["files"] == ["src/app.ts"]  # node_modules and dot-files excluded
    assert any(p.name.endswith("-phase2.json") for p in (brain / "checkpoints").iterdir())


def test_phase_without_start_still_checkpoints(tmp_path, home):
    project = make_project(tmp_path)
    assert cp(home, project, "--oc-root", "/opt/oc", "phase", "3", "--summary", "integration").returncode == 0
    state = wm(home)
    assert state["phases_completed"] == [1, 2, 3] and state["current_phase"] == 4
    assert state["project_name"] == "Notes"


def test_start_continues_an_active_build_for_the_same_project(tmp_path, home):
    project = make_project(tmp_path)
    cp(home, project, "start")
    cp(home, project, "phase", "1", "--summary", "spec")
    build_id = wm(home)["build_id"]
    out = cp(home, project, "start")
    assert "continuing build" in out.stdout
    assert wm(home)["build_id"] == build_id and wm(home)["current_phase"] == 2


def test_finish_marks_build_complete(tmp_path, home):
    project = make_project(tmp_path)
    cp(home, project, "start")
    cp(home, project, "finish")
    state = wm(home)
    assert 8 in state["phases_completed"] and state["finished_at"]
    assert "complete" in (home / ".onecommand" / "brain" / "resume_brief.md").read_text()
    assert "finished" in cp(home, project, "status").stdout


def test_gate_result_appears_in_resume_brief(tmp_path, home):
    project = make_project(tmp_path)
    write_json(project / ".onecommand" / "gate" / "result.json", {
        "passed": False, "stage": "e2e", "failed_steps": ["e2e", "acceptance"],
        "acceptance": {"blocking_passed": 11, "blocking": 18}})
    cp(home, project, "phase", "4", "--summary", "gate failed", "--status", "warn")
    brief = (home / ".onecommand" / "brain" / "resume_brief.md").read_text()
    assert "FAILED (stage e2e, acceptance 11/18, failing: e2e, acceptance)" in brief


def test_corrupt_working_memory_is_reported(tmp_path, home):
    project = make_project(tmp_path)
    (home / ".onecommand" / "brain").mkdir(parents=True)
    (home / ".onecommand" / "brain" / "working_memory.json").write_text("{")
    out = cp(home, project, "status")
    assert out.returncode == 1 and "not valid JSON" in out.stderr
