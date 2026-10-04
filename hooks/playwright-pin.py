#!/usr/bin/env python3
"""OneCommand Playwright pin.

Every @playwright/test version needs one exact browser revision. Sandboxes and
CI images often ship pre-installed browsers (PLAYWRIGHT_BROWSERS_PATH) and block
the browser download — then the latest @playwright/test cannot launch anything
and every acceptance test dies in milliseconds. A real OneCommand build lost
several healing rounds to exactly that (1.63 needed chromium-1243, the machine
had chromium-1194).

`playwright install --dry-run chromium` prints the install locations a version
needs without downloading anything, so the right version can be chosen up front.

Subcommands
-----------
check    Does the project's installed @playwright/test find its browsers?
suggest  Which version to pin: the installed one if its browsers exist, else the
         newest candidate whose browsers are on disk (globally installed
         playwright packages, then --candidates). Prints "PIN <version>" or "NONE".
apply    suggest + `npm install -D --save-exact @playwright/test@<version>` when
         the installed version cannot launch.

Exit codes: 0 ok / browsers present · 1 browsers missing, no pin found · 2 usage error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DRY_RUN_TIMEOUT = 180
LOCATION = re.compile(r"Install location:\s+(\S+)")


def sh(cmd: list[str], cwd: Path, timeout: int = DRY_RUN_TIMEOUT) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return 1, str(exc)


def chromium_locations(output: str) -> list[str]:
    return [loc for loc in LOCATION.findall(output) if "chromium" in Path(loc).name]


def installed_version(project: Path) -> str | None:
    pkg = project / "node_modules" / "@playwright" / "test" / "package.json"
    try:
        return json.loads(pkg.read_text())["version"]
    except (OSError, ValueError, KeyError):
        return None


def browsers_present(project: Path, version: str | None) -> tuple[bool, list[str]]:
    """True when every chromium location the given version needs exists on disk."""
    if version is None:
        cmd = ["npx", "--no-install", "playwright", "install", "--dry-run", "chromium"]
    else:
        cmd = ["npx", "-y", f"playwright@{version}", "install", "--dry-run", "chromium"]
    rc, out = sh(cmd, project)
    locations = chromium_locations(out)
    if rc != 0 or not locations:
        return False, locations
    return all(Path(loc).is_dir() for loc in locations), locations


def global_candidates() -> list[str]:
    """Versions of playwright packages installed globally (they usually match the machine's browsers)."""
    rc, root = sh(["npm", "root", "-g"], Path.cwd(), timeout=30)
    versions: list[str] = []
    if rc == 0:
        for name in ("playwright", "@playwright/test", "playwright-core"):
            try:
                versions.append(json.loads((Path(root.strip()) / name / "package.json").read_text())["version"])
            except (OSError, ValueError, KeyError):
                pass
    return versions


def version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def suggest(project: Path, extra: list[str]) -> tuple[str | None, str]:
    current = installed_version(project)
    if current:
        ok, locs = browsers_present(project, None)
        if ok:
            return current, f"installed @playwright/test {current} finds its browsers ({', '.join(locs)})"
    candidates = sorted(set(global_candidates() + extra) - {current}, key=version_key, reverse=True)
    for v in candidates:
        ok, locs = browsers_present(project, v)
        if ok:
            return v, f"@playwright/test {v} matches pre-installed browsers ({', '.join(locs)})"
    return None, (f"no candidate matches the installed browsers (tried: {', '.join(candidates) or 'none'}); "
                  "allow the browser download: npx playwright install chromium")


def cmd_check(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    current = installed_version(project)
    if not current:
        print("[playwright-pin] @playwright/test is not installed in this project")
        return 1
    ok, locs = browsers_present(project, None)
    print(f"[playwright-pin] @playwright/test {current}: browsers {'present' if ok else 'MISSING'} "
          f"({', '.join(locs) or 'no location reported'})")
    return 0 if ok else 1


def cmd_suggest(args: argparse.Namespace) -> int:
    version, why = suggest(Path(args.project_dir).resolve(), args.candidates)
    print(f"PIN {version}" if version else "NONE")
    print(f"[playwright-pin] {why}", file=sys.stderr)
    return 0 if version else 1


def cmd_apply(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    current = installed_version(project)
    version, why = suggest(project, args.candidates)
    print(f"[playwright-pin] {why}")
    if not version:
        return 1
    if version == current:
        return 0
    rc, out = sh(["npm", "install", "-D", "--save-exact", f"@playwright/test@{version}"], project, timeout=600)
    if rc != 0:
        print(out[-1500:], file=sys.stderr)
        return 1
    print(f"[playwright-pin] pinned @playwright/test {current or '(none)'} → {version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-dir", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check").set_defaults(func=cmd_check)
    for name, func in (("suggest", cmd_suggest), ("apply", cmd_apply)):
        p = sub.add_parser(name)
        p.add_argument("--candidates", nargs="*", default=[], help="extra versions to try")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    if not (Path(args.project_dir) / "package.json").exists():
        print(f"[playwright-pin] no package.json in {args.project_dir}", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    os.environ.setdefault("npm_config_update_notifier", "false")
    sys.exit(main())
