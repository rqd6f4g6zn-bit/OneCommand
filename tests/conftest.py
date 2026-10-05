"""Shared fixtures for the OneCommand script tests.

Every test runs the real scripts as subprocesses against throwaway directories
(own HOME, own git remotes, own projects) — nothing touches the developer's
~/.claude, ~/.codex or ~/.onecommand.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / "hooks"


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
        timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """Run a command, return the completed process (never raises on exit code)."""
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=True, text=True, timeout=timeout)


def py(script: str, *args: str, **kw) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, str(HOOKS / script), *args], **kw)


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def make_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """An empty HOME directory."""
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    """A bin directory with a fake `codex` CLI, to be prepended to PATH."""
    b = tmp_path / "bin"
    make_executable(b / "codex", "#!/bin/sh\necho codex 0.0-test\n")
    return b


@pytest.fixture
def git_identity() -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
    }


def require(tool: str) -> None:
    if shutil.which(tool) is None:
        pytest.skip(f"{tool} not installed", allow_module_level=True)


VALID_SPEC = {
    "project_name": "Demo",
    "app_type": "web-app",
    "build_targets": ["web"],
    "features": ["auth", "notes"],
    "acceptance_criteria": [
        {"id": "AC-001", "feature": "auth", "title": "Registered user lands on /notes",
         "priority": "must", "verification": "e2e", "start": "/register",
         "steps": ["fill form", "click 'Create account'"], "expected": ["URL is /notes"]},
        {"id": "AC-002", "feature": "notes", "title": "Created note is listed after reload",
         "priority": "must", "verification": "e2e", "start": "/notes",
         "steps": ["click 'New note'", "save"], "expected": ["row 'Milk' visible after reload"]},
        {"id": "AC-003", "feature": "notes", "title": "GET /api/notes without session returns 401",
         "priority": "must", "verification": "api", "steps": ["GET /api/notes"], "expected": ["status 401"]},
        {"id": "AC-004", "feature": "notes", "title": "Print layout shows one note per page",
         "priority": "should", "verification": "manual", "steps": ["print"], "expected": ["one note per page"]},
    ],
}
