"""install.sh — fresh install, idempotent re-run, upgrade, safety guards.

Runs the real installer against a throwaway HOME. On macOS CI this also covers
the system bash 3.2.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import REPO, require, run, write_json

require("rsync")


def install(home: Path, fake_bin: Path, *args: str, codex: bool = True):
    path = f"{fake_bin}:{os.environ['PATH']}" if codex else "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
    return run(["bash", str(REPO / "install.sh"), *args], env={"HOME": str(home), "PATH": path}, timeout=300)


def plugin_version() -> str:
    return json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())["version"]


def test_fresh_install(home, fake_bin):
    out = install(home, fake_bin)
    assert out.returncode == 0, out.stdout + out.stderr
    assert (home / ".claude" / "plugins" / "onecommand" / "hooks" / "quality-gate.sh").exists()
    assert (home / ".claude" / "commands" / "oc-resume.md").exists()
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    assert settings["enabledPlugins"]["onecommand@local"] is True
    entry = json.loads((home / ".claude" / "plugins" / "installed_plugins.json").read_text())["plugins"]["onecommand@local"][0]
    assert entry["version"] == plugin_version() and entry["installPath"] == str(REPO)
    cfg = json.loads((home / ".onecommand" / "config.json").read_text())
    assert cfg["auto_update"] is True and cfg["update_branch"] == "main"
    for f in ("episodic_memory.json", "semantic_memory.json", "pattern_library.json", "user_preferences.json"):
        assert (home / ".onecommand" / "brain" / f).exists()
    assert (home / ".codex" / "skills" / "onecommand" / "hooks" / "update.py").exists()
    assert (home / ".codex" / "skills" / "acceptance-tester" / "SKILL.md").exists()
    assert "⚠" not in out.stdout, out.stdout
    plugin = home / ".claude" / "plugins" / "onecommand"
    for dev_only in ("tests", ".github", "docs", ".git", "install.sh"):
        assert not (plugin / dev_only).exists(), f"{dev_only} must not be installed"


def test_rerun_changes_nothing(home, fake_bin):
    install(home, fake_bin)
    out = install(home, fake_bin)
    assert out.returncode == 0
    assert "synced" not in out.stdout and "Installed" not in out.stdout and "Updated" not in out.stdout


def test_upgrade_syncs_changed_and_removes_obsolete_files(home, fake_bin):
    install(home, fake_bin)
    plugin = home / ".claude" / "plugins" / "onecommand"
    (plugin / "commands" / "onecommand.md").write_text("stale")
    (plugin / "commands" / "obsolete.md").write_text("old")
    (home / ".codex" / "skills" / "self-healer" / "self-healer.md").write_text("pre-1.4.1 duplicate")
    write_json(home / ".onecommand" / "config.json", {"version": "1.0.0", "auto_update": False, "plan": "pro"})
    out = install(home, fake_bin, "--verbose")
    assert out.returncode == 0, out.stderr
    assert (plugin / "commands" / "onecommand.md").read_text() == (REPO / "commands" / "onecommand.md").read_text()
    assert not (plugin / "commands" / "obsolete.md").exists()
    assert not (home / ".codex" / "skills" / "self-healer" / "self-healer.md").exists()
    cfg = json.loads((home / ".onecommand" / "config.json").read_text())
    assert cfg["version"] == plugin_version()
    assert cfg["auto_update"] is False and cfg["plan"] == "pro"  # user choices preserved


def test_promoted_learnings_are_migrated_to_rules(home, fake_bin):
    write_json(home / ".onecommand" / "memory" / "cross_learnings.json", {"version": "1.0", "learnings": [
        {"error_pattern": "Cannot find module 'x'", "fix": "npm i x", "description": "x missing",
         "confirmations": 3, "confirmed_by": ["claude", "codex", "claude"], "applied_to_skill": True}]})
    assert install(home, fake_bin).returncode == 0
    assert "x missing" in (home / ".onecommand" / "memory" / "evolved_rules.md").read_text()


def test_unparseable_settings_are_never_overwritten(home, fake_bin):
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text('{"theme": "dark", broken')
    out = install(home, fake_bin)
    assert out.returncode == 1
    assert (home / ".claude" / "settings.json").read_text() == '{"theme": "dark", broken'
    assert "could not be parsed" in out.stderr


def test_existing_settings_are_preserved(home, fake_bin):
    write_json(home / ".claude" / "settings.json", {"theme": "dark", "enabledPlugins": {"other@x": True}})
    assert install(home, fake_bin).returncode == 0
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    assert settings["theme"] == "dark"
    assert settings["enabledPlugins"] == {"other@x": True, "onecommand@local": True}


def test_dry_run_writes_nothing(home, fake_bin):
    out = install(home, fake_bin, "--dry-run")
    assert out.returncode == 0, out.stderr
    assert list(home.iterdir()) == []


def test_without_codex_skips_codex_install(home, fake_bin):
    out = install(home, fake_bin, codex=False)
    if out.returncode != 0 and "Missing required tools" in out.stderr:
        pytest.skip("restricted PATH lacks rsync/python3 on this machine")
    assert out.returncode == 0, out.stderr
    assert "Codex not found" in out.stdout
    assert not (home / ".codex").exists()


def test_unknown_option(home, fake_bin):
    assert install(home, fake_bin, "--nope").returncode == 2
