"""hooks/playwright-pin.py — choose the @playwright/test version whose browsers exist."""

from __future__ import annotations

import importlib.util
import os
import shutil

import pytest

from conftest import HOOKS, py, write_json

spec = importlib.util.spec_from_file_location("playwright_pin", HOOKS / "playwright-pin.py")
pin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin)

DRY_RUN = """browser: chromium version 141.0.7390.37
  Install location:    /opt/pw-browsers/chromium-1194
  Download url:        https://cdn.playwright.dev/builds/chromium/1194/chromium-linux.zip

browser: chromium-headless-shell version 141.0.7390.37
  Install location:    /opt/pw-browsers/chromium_headless_shell-1194

browser: ffmpeg
  Install location:    /opt/pw-browsers/ffmpeg-1011
"""


def test_parses_only_chromium_locations():
    assert pin.chromium_locations(DRY_RUN) == ["/opt/pw-browsers/chromium-1194",
                                               "/opt/pw-browsers/chromium_headless_shell-1194"]


def test_version_ordering():
    assert sorted(["1.9.0", "1.56.1", "1.10.2"], key=pin.version_key, reverse=True) == ["1.56.1", "1.10.2", "1.9.0"]


def test_requires_package_json(tmp_path):
    assert py("playwright-pin.py", "--project-dir", str(tmp_path), "check").returncode == 2


def test_check_without_playwright_installed(tmp_path):
    write_json(tmp_path / "package.json", {"name": "x", "version": "1.0.0"})
    out = py("playwright-pin.py", "--project-dir", str(tmp_path), "check")
    assert out.returncode == 1 and "not installed" in out.stdout


@pytest.mark.skipif(os.environ.get("ONECOMMAND_E2E_TESTS") != "1" or shutil.which("npx") is None,
                    reason="needs npm registry access")
def test_suggest_returns_a_version_that_finds_its_browsers(tmp_path):
    write_json(tmp_path / "package.json", {"name": "x", "version": "1.0.0", "private": True})
    out = py("playwright-pin.py", "--project-dir", str(tmp_path), "suggest", "--candidates", "1.56.1", timeout=600)
    # Either a pin was found (browsers present for that version) or the script explains why not.
    assert out.stdout.startswith(("PIN ", "NONE"))
    assert "[playwright-pin]" in out.stderr
