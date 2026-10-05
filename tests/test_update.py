"""hooks/update.py — self-update with throttling, guards and rollback.

Each test builds a bare git "remote", publishes a minimal OneCommand checkout
(plugin.json + an install.sh that records each run) and clones it into a
throwaway HOME the way a user would.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import HOOKS, py, require, run, write_json

require("git")

INSTALL_OK = '#!/bin/sh\necho "$(cat .claude-plugin/plugin.json)" >> "$HOME/install-runs.log"\n'
INSTALL_BROKEN = '#!/bin/sh\necho broken install >&2\nexit 7\n'


class Setup:
    def __init__(self, tmp: Path, ident: dict[str, str]):
        self.tmp, self.ident = tmp, ident
        self.home = tmp / "home"
        self.home.mkdir()
        self.remote = tmp / "remote.git"
        self.work = tmp / "work"
        self.checkout = self.home / "OneCommand"
        self.env = {**ident, "HOME": str(self.home), "ONECOMMAND_AUTO_UPDATE": ""}
        self.git(None, "init", "-q", "--bare", str(self.remote))
        self.git(None, "init", "-q", "-b", "main", str(self.work))
        self.publish("1.0.0", INSTALL_OK)
        self.git(None, "clone", "-q", "-b", "main", str(self.remote), str(self.checkout))
        # the update script ships inside the checkout, like in a real install
        (self.checkout / "hooks").mkdir(exist_ok=True)
        write_json(self.home / ".onecommand" / "config.json", {"auto_update": True, "update_branch": "main"})

    def git(self, cwd: Path | None, *args: str) -> str:
        proc = run(["git", *args], cwd=cwd, env=self.ident)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()

    def publish(self, version: str, install_sh: str = INSTALL_OK) -> None:
        write_json(self.work / ".claude-plugin" / "plugin.json", {"name": "onecommand", "version": version})
        (self.work / "install.sh").write_text(install_sh)
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-qm", f"v{version}")
        self.git(self.work, "push", "-q", str(self.remote), "HEAD:refs/heads/main")

    def update(self, *args: str):
        return py("update.py", "--repo", str(self.checkout), *args, env=self.env)

    def version(self) -> str:
        return json.loads((self.checkout / ".claude-plugin" / "plugin.json").read_text())["version"]

    def state(self) -> dict:
        return json.loads((self.home / ".onecommand" / "update-state.json").read_text())

    def running_build(self) -> None:
        write_json(self.home / ".onecommand" / "brain" / "working_memory.json",
                   {"project_name": "Shop", "phases_completed": [1, 2], "current_phase": 3})


@pytest.fixture
def s(tmp_path, git_identity) -> Setup:
    return Setup(tmp_path, git_identity)


def test_up_to_date_is_silent_in_quiet_mode(s):
    out = s.update("auto", "--quiet", "--force")
    assert out.returncode == 0 and out.stdout == ""
    assert s.update("check").stdout.strip() == "OneCommand v1.0.0 is up to date."


def test_check_reports_available_with_exit_10(s):
    s.publish("1.1.0")
    out = s.update("check")
    assert out.returncode == 10
    assert "v1.0.0 → v1.1.0" in out.stdout
    assert s.version() == "1.0.0"  # check never changes anything


def test_auto_installs_update_and_runs_installer(s):
    s.publish("1.1.0")
    out = s.update("auto", "--force")
    assert out.returncode == 0, out.stderr
    assert "updated v1.0.0 → v1.1.0" in out.stdout
    assert s.version() == "1.1.0"
    assert '"1.1.0"' in (s.home / "install-runs.log").read_text()


def test_auto_is_throttled(s):
    s.update("auto", "--force")
    s.publish("1.1.0")
    out = s.update("auto")
    assert "checked recently" in out.stdout
    assert s.version() == "1.0.0"


@pytest.mark.parametrize("guard,expected", [
    ("dirty", "uncommitted changes"),
    ("build", "build in progress: Shop (phase 3/8)"),
    ("branch", "auto-update tracks 'main'"),
    ("disabled", "auto_update is off"),
])
def test_guards_prevent_installing(s, guard, expected):
    s.publish("1.1.0")
    if guard == "dirty":
        (s.checkout / "install.sh").write_text(INSTALL_OK + "# local edit\n")
    elif guard == "build":
        s.running_build()
    elif guard == "branch":
        s.git(s.checkout, "checkout", "-q", "-b", "feature")
    elif guard == "disabled":
        write_json(s.home / ".onecommand" / "config.json", {"auto_update": False})
    out = s.update("auto", "--force")
    assert out.returncode == 0
    assert expected in out.stdout
    assert s.version() == "1.0.0"


def test_env_var_disables_auto_install(s):
    s.publish("1.1.0")
    s.env["ONECOMMAND_AUTO_UPDATE"] = "0"
    assert "auto_update is off" in s.update("auto", "--force").stdout
    assert s.version() == "1.0.0"


def test_abandoned_build_does_not_block_updates(s):
    s.publish("1.1.0")
    s.running_build()
    wm = s.home / ".onecommand" / "brain" / "working_memory.json"
    old = wm.stat().st_mtime - 48 * 3600
    os.utime(wm, (old, old))
    assert "updated" in s.update("auto", "--force").stdout


def test_diverged_checkout_is_left_alone(s):
    s.publish("1.1.0")
    (s.checkout / "local.txt").write_text("x")
    s.git(s.checkout, "add", "local.txt")
    s.git(s.checkout, "commit", "-qm", "local work")
    out = s.update("auto", "--force")
    assert "local commits are not on the remote" in out.stdout


def test_failed_install_rolls_back_and_is_not_retried(s):
    s.publish("1.1.0", INSTALL_BROKEN)
    out = s.update("apply")
    assert out.returncode == 1
    assert "failed and was rolled back to v1.0.0" in out.stdout
    assert s.version() == "1.0.0"
    broken_sha = s.state()["failed_sha"]
    # Following sessions must not retry the same broken commit.
    for _ in range(2):
        quiet = s.update("auto", "--force", "--quiet")
        assert quiet.returncode == 0 and quiet.stdout == ""
    assert s.version() == "1.0.0"
    assert s.state()["failed_sha"] == broken_sha
    # A newer, fixed release is installed and clears the failure marker.
    s.publish("1.1.1", INSTALL_OK)
    assert "updated" in s.update("auto", "--force").stdout
    assert s.version() == "1.1.1"
    assert "failed_sha" not in s.state()


def test_offline_is_silent_in_quiet_mode(s):
    s.git(s.checkout, "remote", "set-url", "origin", str(s.tmp / "does-not-exist.git"))
    out = s.update("auto", "--force", "--quiet")
    assert out.returncode == 0 and out.stdout == ""


def test_missing_checkout_never_blocks_a_session_hook(tmp_path):
    # The script normally lives inside a checkout; a copy outside any checkout with
    # an empty HOME has nothing to update.
    env = {"HOME": str(tmp_path)}
    lone = tmp_path / "lone"
    lone.mkdir()
    (lone / "update.py").write_text((HOOKS / "update.py").read_text())
    out = run(["python3", str(lone / "update.py"), "auto", "--quiet"], env=env)
    assert out.returncode == 0
    loud = run(["python3", str(lone / "update.py"), "check"], env=env)
    assert loud.returncode == 2 and "no OneCommand git checkout found" in loud.stderr
