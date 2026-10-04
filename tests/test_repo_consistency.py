"""Repository invariants that broke silently in the past."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import REPO, py

SKILL_DIRS = sorted(p for p in (REPO / "skills").iterdir() if p.is_dir())


def test_versions_match_everywhere():
    claude = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())["version"]
    codex = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text())["version"]
    installer = re.search(r'^PLUGIN_VERSION="([^"]+)"', (REPO / "install.sh").read_text(), re.M).group(1)
    assert claude == codex == installer


def test_changelog_has_current_version():
    version = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert f"## [{version}]" in (REPO / "CHANGELOG.md").read_text()


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_one_instruction_file_per_skill(skill_dir: Path):
    assert (skill_dir / "SKILL.md").is_file()
    extra = [p.name for p in skill_dir.glob("*.md") if p.name != "SKILL.md" and not p.name.endswith("-global.md")]
    assert not extra, f"second instruction file(s) next to SKILL.md: {extra}"


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_skill_frontmatter(skill_dir: Path):
    text = (skill_dir / "SKILL.md").read_text()
    head = text.split("\n---", 1)[0]
    assert text.startswith("---\n")
    assert re.search(rf"^name: {re.escape(skill_dir.name)}$", head, re.M), "name must match the directory"
    desc = re.search(r"^description: (.+)$", head, re.M)
    assert desc and "model:" not in desc.group(1), "description must not swallow another key"


def test_installer_lists_every_skill():
    listed = set(re.findall(r'^  "([a-z0-9-]+)"$', (REPO / "install.sh").read_text(), re.M))
    assert listed == {p.name for p in SKILL_DIRS}


def test_every_skill_is_mapped_to_a_phase():
    out = py("skill-catalog.py", "verify-bundled", "--oc-root", str(REPO))
    assert out.returncode == 0, out.stdout


def test_spec_analyzer_example_passes_its_own_validator(tmp_path):
    text = (REPO / "skills" / "spec-analyzer" / "SKILL.md").read_text()
    example = re.search(r"```json\n(\{.*?\n\})\n```", text, re.S).group(1)
    spec = tmp_path / "spec.json"
    spec.write_text(example)
    out = py("acceptance-report.py", "validate", "--spec", str(spec))
    assert out.returncode == 0, out.stdout


def test_json_files_are_valid():
    for path in [REPO / ".claude-plugin" / "plugin.json", REPO / ".codex-plugin" / "plugin.json",
                 REPO / "hooks" / "hooks.json"]:
        json.loads(path.read_text())


def test_session_start_hook_runs_the_updater_quietly():
    hooks = json.loads((REPO / "hooks" / "hooks.json").read_text())["hooks"]
    cmd = hooks["SessionStart"][0]["hooks"][0]["command"]
    assert "hooks/update.py" in cmd and "auto" in cmd and "--quiet" in cmd


AGENT_AND_SKILL_FILES = sorted(list((REPO / "agents").glob("*.md")) + [d / "SKILL.md" for d in SKILL_DIRS])


@pytest.mark.parametrize("path", AGENT_AND_SKILL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_models_use_aliases_not_pinned_ids(path: Path):
    head = path.read_text().split("\n---", 1)[0]
    m = re.search(r"^model: (.+)$", head, re.M)
    if m:
        assert m.group(1).strip() in ("opus", "sonnet", "haiku", "inherit"), \
            f"pinned model id '{m.group(1)}' goes stale — use an alias"


def test_no_machine_specific_paths():
    offenders = []
    for path in list(REPO.glob("**/*.md")) + list(REPO.glob("**/*.py")) + list(REPO.glob("**/*.sh")):
        if "docs" in path.parts or "tests" in path.parts or "node_modules" in path.parts:
            continue
        if "/Users/g.urban" in path.read_text(errors="replace"):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, offenders


def test_commands_checked_by_doctor_exist():
    doctor = (REPO / "commands" / "oc-doctor.md").read_text()
    names = re.search(r"required_cmds = \[(.*?)\]", doctor).group(1)
    for name in re.findall(r'"([^"]+\.md)"', names):
        assert (REPO / "commands" / name).exists(), name


SHELL_SCRIPTS = sorted([REPO / "install.sh", *(REPO / "hooks").glob("*.sh")])


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_no_heredoc_inside_command_substitution(script: Path):
    # bash 3.2 (macOS /bin/bash) tracks quotes inside a heredoc that sits in $( … ): a single
    # apostrophe in the embedded Python broke install.sh on macOS. Write to a temp file instead.
    offenders = [f"{script.name}:{n}" for n, line in enumerate(script.read_text().splitlines(), 1)
                 if not line.lstrip().startswith("#") and re.search(r"\$\([^)]*<<", line)]
    assert not offenders, offenders
