"""hooks/skill-catalog.py — every available skill must be considered."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import REPO, py, write_json


def skill(root: Path, name: str, description: str, frontmatter_name: str | None = None) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {frontmatter_name or name}\ndescription: {description}\n---\nbody\n")


@pytest.fixture
def env(tmp_path: Path):
    home = tmp_path / "home"
    project = tmp_path / "proj"
    skill(home / ".claude" / "skills", "pdf-tool", "|\n  Work with PDF files.\n  Merge and split.")
    sp = tmp_path / "superpowers"
    skill(sp / "skills", "frontend-design", '"Distinctive frontend UI"')
    off = tmp_path / "disabled"
    skill(off / "skills", "hidden", "should never appear")
    skill(project / ".claude" / "skills", "house-style", "Project writing style")
    write_json(home / ".claude" / "settings.json",
               {"enabledPlugins": {"superpowers@mk": True, "disabled@mk": False}})
    write_json(home / ".claude" / "plugins" / "installed_plugins.json", {"version": 2, "plugins": {
        "superpowers@mk": [{"installPath": str(sp)}], "disabled@mk": [{"installPath": str(off)}]}})
    write_json(project / ".onecommand-spec.json", {"project_name": "T", "app_type": "web-app", "build_targets": ["web"]})
    return home, project


def cat(project: Path, *args: str):
    return py("skill-catalog.py", "--project-dir", str(project), *args)


def scan(home: Path, project: Path):
    return cat(project, "scan", "--oc-root", str(REPO), "--home", str(home))


def catalog(project: Path) -> dict:
    return json.loads((project / ".onecommand" / "skills-catalog.json").read_text())


def decide(project: Path, decisions: list[dict]) -> None:
    write_json(project / ".onecommand" / "skill-plan.json", {"decisions": decisions})


GOOD = [
    {"skill": "superpowers:frontend-design", "phases": [2, 6], "use": "visual polish"},
    {"skill": "pdf-tool", "phases": [], "reason": "no PDFs in this project"},
    {"skill": "house-style", "phases": [3], "use": "README tone"},
]


def test_scan_finds_bundled_user_project_and_enabled_plugin_skills(env):
    home, project = env
    out = scan(home, project)
    assert out.returncode == 0, out.stderr
    by_name = {s["name"]: s for s in catalog(project)["skills"]}
    assert by_name["pdf-tool"]["source"] == "user"
    assert by_name["pdf-tool"]["description"] == "Work with PDF files. Merge and split."  # block scalar
    assert by_name["superpowers:frontend-design"]["source"] == "plugin:superpowers"
    assert by_name["house-style"]["source"] == "project"
    assert "disabled:hidden" not in by_name  # disabled plugins are ignored
    bundled = [s for s in by_name.values() if s["source"] == "bundled"]
    assert len(bundled) == len(list((REPO / "skills").glob("*/SKILL.md")))


def test_bundled_skills_follow_build_targets(env):
    home, project = env
    scan(home, project)
    status = {s["name"]: s["status"] for s in catalog(project)["skills"]}
    assert status["acceptance-tester"] == "assigned"
    assert status["app-icon-generator"] == "not_used"  # web-only build
    assert status["codex-setup"] == "not_used"  # setup-time skill
    write_json(project / ".onecommand-spec.json", {"app_type": "web-app", "build_targets": ["web", "mobile"]})
    scan(home, project)
    status = {s["name"]: s["status"] for s in catalog(project)["skills"]}
    assert status["app-icon-generator"] == "assigned"
    assert status["store-readiness-checker"] == "assigned"


def test_check_fails_while_external_skills_are_undecided(env):
    home, project = env
    scan(home, project)
    out = cat(project, "check")
    assert out.returncode == 1
    assert out.stdout.count("no decision yet") == 3


def test_check_rejects_malformed_decisions(env):
    home, project = env
    scan(home, project)
    decide(project, GOOD[:2] + [
        {"skill": "house-style", "phases": [3]},              # no "use"
        {"skill": "spec-analyzer", "phases": [1], "use": "x"},  # bundled — mapped automatically
        {"skill": "typo", "phases": [9], "use": "x"},
    ])
    out = cat(project, "check")
    assert out.returncode == 1
    for needle in ("'use' (what it is used for) is empty", "mapped automatically", "not in the catalog"):
        assert needle in out.stdout


def test_complete_plan_and_for_phase(env):
    home, project = env
    scan(home, project)
    decide(project, GOOD)
    out = cat(project, "check")
    assert out.returncode == 0, out.stdout
    assert catalog(project)["complete"] is True
    phase2 = cat(project, "for-phase", "2").stdout
    assert "superpowers:frontend-design" in phase2 and "oc-frontend-design" in phase2
    assert "pdf-tool" not in phase2
    plan = (project / ".onecommand" / "skill-plan.md").read_text()
    assert "pdf-tool (user) — no PDFs in this project" in plan


def test_every_bundled_skill_is_mapped():
    out = py("skill-catalog.py", "verify-bundled", "--oc-root", str(REPO))
    assert out.returncode == 0, out.stdout


def test_verify_bundled_detects_unmapped_skill(tmp_path):
    root = tmp_path / "oc"
    skill(root / "skills", "brand-new-skill", "not mapped yet")
    out = py("skill-catalog.py", "verify-bundled", "--oc-root", str(root))
    assert out.returncode == 1
    assert "unmapped: skills/brand-new-skill" in out.stdout


def test_spec_sections_decide_conditional_skills(env):
    home, project = env
    scan(home, project)
    status = {s["name"]: s["status"] for s in catalog(project)["skills"]}
    assert status["voice-agent"] == "not_used" and status["video-producer"] == "not_used"
    write_json(project / ".onecommand-spec.json", {"app_type": "web-app", "build_targets": ["web"],
                                                   "voice": {"provider": "twilio"}, "media": {"videos": [{"id": "hero"}]}})
    scan(home, project)
    status = {s["name"]: s["status"] for s in catalog(project)["skills"]}
    assert status["voice-agent"] == "assigned" and status["video-producer"] == "assigned"


def test_read_records_and_check_read_enforces_loading(env):
    home, project = env
    scan(home, project)
    decide(project, GOOD)
    assert cat(project, "check").returncode == 0
    phase2 = cat(project, "for-phase", "2").stdout
    assert "read oc-frontend-design --phase 2" in phase2  # the prompt carries the load command
    missing = cat(project, "check-read", "2")
    assert missing.returncode == 1 and "oc-frontend-design: assigned to phase 2 but never loaded" in missing.stdout

    out = cat(project, "read", "oc-frontend-design", "--phase", "2")
    assert out.returncode == 0 and "Visual quality bar" in out.stdout  # the agent gets the full SKILL.md
    reads = json.loads((project / ".onecommand" / "skills-read.json").read_text())["reads"]
    assert reads[0]["skill"] == "oc-frontend-design" and len(reads[0]["sha256"]) == 64
    for name in ("oc-ui-ux", "21st-components", "collab-protocol", "superpowers:frontend-design"):
        assert cat(project, "read", name, "--phase", "2").returncode == 0
    assert cat(project, "check-read", "2").returncode == 0
    assert cat(project, "read", "oc-ui-ux", "--phase", "3").returncode == 0  # phase-specific: does not count for 2
    assert cat(project, "read", "nope", "--phase", "2").returncode == 2


def test_check_read_detects_a_skill_loaded_in_an_older_version(env, tmp_path):
    home, project = env
    scan(home, project)
    decide(project, GOOD)
    cat(project, "check")
    sp_skill = tmp_path / "superpowers" / "skills" / "frontend-design" / "SKILL.md"
    for name in ("oc-frontend-design", "oc-ui-ux", "21st-components", "collab-protocol", "superpowers:frontend-design"):
        cat(project, "read", name, "--phase", "2")
    sp_skill.write_text(sp_skill.read_text() + "new rule\n")
    out = cat(project, "check-read", "2")
    assert out.returncode == 1 and "superpowers:frontend-design: loaded in an older version" in out.stdout


def test_every_agent_loads_its_skills_and_names_only_existing_ones():
    import re
    for agent in sorted((REPO / "agents").glob("*.md")):
        text = agent.read_text()
        front = text.split("\n---", 1)[0]
        listed = re.findall(r"^  - (\S+)$", front.split("skills:", 1)[1], re.M) if "skills:" in front else []
        for name in listed:
            bare = name.removeprefix("onecommand:")
            if ":" not in bare:
                assert (REPO / "skills" / bare / "SKILL.md").exists(), f"{agent.name}: skill {name} does not exist"
                assert f"onecommand:{bare}" in listed and bare in listed, f"{agent.name}: list {bare} bare and namespaced"
        assert "## Step 0 — Load your skills" in text, f"{agent.name}: no skill-loading step"
        assert "check-read" in text
    frontend = (REPO / "agents" / "frontend-agent.md").read_text()
    assert "Invoke frontend-design" not in frontend and "Use the `ui-ux-pro-max` skill" not in frontend
