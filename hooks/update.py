#!/usr/bin/env python3
"""OneCommand self-update.

Detects when a newer OneCommand is available on the tracked branch of the git
checkout that install.sh registered, and installs it automatically:
fast-forward pull → install.sh → done. A failed install is rolled back to the
previous commit and re-installed, so a broken update never leaves a broken
plugin behind.

Subcommands
-----------
check   Report whether an update is available (no changes).
apply   Install an available update now (ignores the check interval).
auto    What the SessionStart hook and the Codex pre-flight run: honours
        auto_update / update_interval_hours from ~/.onecommand/config.json and
        applies the update when enabled.
status  Print configuration and the result of the last check.

Never updates when: the checkout has uncommitted changes, it is on a different
branch than the tracked one, local commits are not on the remote (diverged),
or a OneCommand build is in progress (resume would mix two versions).

Configuration (~/.onecommand/config.json, created by install.sh):
  "auto_update": true            false → only report, never install
  "update_branch": "main"        branch to track
  "update_interval_hours": 6     minimum time between automatic checks
Environment: ONECOMMAND_AUTO_UPDATE=0 disables automatic installs for one run.

Exit codes: 0 ok (up to date, updated, skipped) · 1 update failed (rolled back)
· 2 usage / setup error · 10 update available (check only)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("update")
HOME = Path.home()
OC_HOME = HOME / ".onecommand"
CONFIG_PATH = OC_HOME / "config.json"
STATE_PATH = OC_HOME / "update-state.json"
DEFAULTS = {"auto_update": True, "update_branch": "main", "update_interval_hours": 6}
FETCH_TIMEOUT = 25
INSTALL_TIMEOUT = 300
BUILD_STALE_HOURS = 24
EXIT_AVAILABLE = 10


class UpdateError(Exception):
    pass


# ─── helpers ──────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    stored = read_json(CONFIG_PATH, {})
    if isinstance(stored, dict):
        cfg.update({k: stored[k] for k in DEFAULTS if k in stored})
    if os.environ.get("ONECOMMAND_AUTO_UPDATE", "").strip() in ("0", "false", "no", "off"):
        cfg["auto_update"] = False
    return cfg


def git(repo: Path, *args: str, timeout: int = 30, check: bool = True) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        raise UpdateError(f"git {' '.join(args)} timed out after {timeout}s") from None
    except FileNotFoundError:
        raise UpdateError("git is not installed") from None
    if check and proc.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout.strip()


def find_repo(explicit: str | None) -> Path:
    """The git checkout install.sh registered (installed copies have no .git)."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(Path(__file__).resolve().parent.parent)
    registry = read_json(HOME / ".claude" / "plugins" / "installed_plugins.json", {})
    try:
        candidates.append(Path(registry["plugins"]["onecommand@local"][0]["installPath"]).expanduser())
    except (KeyError, IndexError, TypeError):
        pass
    candidates += [HOME / "OneCommand", HOME / "OneComand"]
    for c in candidates:
        if (c / ".git").exists() and (c / ".claude-plugin" / "plugin.json").exists():
            return c.resolve()
    raise UpdateError("no OneCommand git checkout found — clone it and run install.sh "
                      "(checked: " + ", ".join(str(c) for c in candidates) + ")")


def version_at(repo: Path, ref: str | None) -> str:
    try:
        if ref is None:
            raw = (repo / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        else:
            raw = git(repo, "show", f"{ref}:.claude-plugin/plugin.json")
        return str(json.loads(raw).get("version", "?"))
    except (OSError, ValueError, UpdateError):
        return "?"


def build_in_progress() -> str | None:
    """Name of a running build, or None. Builds untouched for 24h count as abandoned."""
    wm_path = OC_HOME / "brain" / "working_memory.json"
    wm = read_json(wm_path, None)
    if not isinstance(wm, dict):
        return None
    done = wm.get("phases_completed") or []
    if not done or 8 in done or "8" in done:
        return None
    try:
        age_h = (time.time() - wm_path.stat().st_mtime) / 3600
    except OSError:
        return None
    if age_h > BUILD_STALE_HOURS:
        return None
    return f"{wm.get('project_name', '?')} (phase {wm.get('current_phase', '?')}/8)"


# ─── core ─────────────────────────────────────────────────────────────────────

def inspect(repo: Path, branch: str) -> dict[str, Any]:
    info: dict[str, Any] = {"repo": str(repo), "branch": branch, "checked_at": now_iso()}
    if not git(repo, "remote", check=False):
        raise UpdateError("checkout has no git remote")
    current = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    info["current_branch"] = current
    try:
        git(repo, "fetch", "--quiet", "origin", branch, timeout=FETCH_TIMEOUT)
    except UpdateError as exc:
        info.update(status="offline", detail=str(exc))
        return info
    local = git(repo, "rev-parse", "HEAD")
    remote = git(repo, "rev-parse", f"origin/{branch}")
    info.update(local_sha=local[:12], remote_sha=remote[:12],
                local_version=version_at(repo, None), remote_version=version_at(repo, f"origin/{branch}"))
    if current != branch:
        info.update(status="other_branch", detail=f"checkout is on '{current}', auto-update tracks '{branch}'")
    elif local == remote:
        info.update(status="up_to_date")
    elif subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", "HEAD", f"origin/{branch}"]).returncode == 0:
        behind = git(repo, "rev-list", "--count", f"HEAD..origin/{branch}")
        info.update(status="available", commits=int(behind or 0))
    else:
        info.update(status="diverged", detail="local commits are not on the remote — update manually")
    return info


def run_install(repo: Path) -> tuple[bool, str]:
    try:
        proc = subprocess.run(["bash", str(repo / "install.sh")], cwd=repo, capture_output=True, text=True,
                              timeout=INSTALL_TIMEOUT, env={**os.environ, "ONECOMMAND_AUTO_UPDATE": "0"})
    except subprocess.TimeoutExpired:
        return False, f"install.sh timed out after {INSTALL_TIMEOUT}s"
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


def apply_update(repo: Path, info: dict[str, Any], force: bool) -> dict[str, Any]:
    dirty = git(repo, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        info.update(status="skipped_dirty", detail="uncommitted changes in the checkout")
        return info
    running = build_in_progress()
    if running and not force:
        info.update(status="skipped_build_running", detail=f"build in progress: {running} — updates after it finishes")
        return info

    old_sha = git(repo, "rev-parse", "HEAD")
    git(repo, "merge", "--ff-only", "--quiet", f"origin/{info['branch']}")
    ok, log = run_install(repo)
    if ok:
        info.update(status="updated", previous_sha=old_sha[:12], installed_version=version_at(repo, None))
        return info

    # Roll back: previous commit + previous install, so the plugin keeps working.
    LOG.warning("install failed — rolling back to %s", old_sha[:12])
    git(repo, "reset", "--keep", old_sha)
    restored, restore_log = run_install(repo)
    info.update(status="failed_rolled_back" if restored else "failed_rollback_incomplete",
                detail=log[-800:], rollback_log=None if restored else restore_log[-800:])
    return info


def message(info: dict[str, Any]) -> str:
    s = info.get("status")
    lv, rv = info.get("local_version", "?"), info.get("remote_version", "?")
    return {
        "up_to_date": f"OneCommand v{lv} is up to date.",
        "available": f"OneCommand update available: v{lv} → v{rv} ({info.get('commits', '?')} commit(s)).",
        "updated": f"✅ OneCommand updated v{lv} → v{info.get('installed_version', rv)} "
                   f"({info.get('commits', '?')} commit(s)). New commands and agents load in the next session.",
        "offline": "OneCommand update check skipped — remote not reachable.",
        "other_branch": f"OneCommand auto-update skipped — {info.get('detail')}.",
        "diverged": f"OneCommand auto-update skipped — {info.get('detail')}.",
        "skipped_dirty": "OneCommand update available but not installed — the checkout has uncommitted changes.",
        "skipped_build_running": f"OneCommand update v{rv} waits — {info.get('detail')}.",
        "disabled": f"OneCommand update available: v{lv} → v{rv} — auto_update is off, run /oc-update to install.",
        "throttled": "OneCommand update check skipped — checked recently.",
        "known_broken": f"OneCommand v{rv} failed to install before — waiting for a newer release (or run /oc-update to retry).",
        "failed_rolled_back": f"⚠ OneCommand update to v{rv} failed and was rolled back to v{lv}. Details: ~/.onecommand/update-state.json",
        "failed_rollback_incomplete": "✗ OneCommand update failed AND rollback failed — run install.sh manually, then /oc-doctor.",
    }.get(s, f"OneCommand update: {s}")


def record(info: dict[str, Any]) -> None:
    state = read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state.update(last_check=info.get("checked_at", now_iso()), last_status=info.get("status"), last=info)
    if info.get("status") == "updated":
        state["last_update"] = now_iso()
        state.pop("failed_sha", None)
    elif str(info.get("status", "")).startswith("failed"):
        state["failed_sha"] = info.get("remote_sha")
    write_json(STATE_PATH, state)


# Statuses a quiet (hook) run stays silent about — nothing for the user to act on.
QUIET = {"up_to_date", "offline", "other_branch", "throttled", "known_broken"}


def emit(info: dict[str, Any], quiet: bool, as_json: bool) -> None:
    if as_json:
        print(json.dumps(info, indent=2))
    elif not (quiet and info.get("status") in QUIET):
        print(message(info))


# ─── commands ─────────────────────────────────────────────────────────────────

def cmd_check(args: argparse.Namespace) -> int:
    info = inspect(find_repo(args.repo), args.branch or config()["update_branch"])
    record(info)
    emit(info, args.quiet, args.json)
    return EXIT_AVAILABLE if info["status"] == "available" else 0


def cmd_apply(args: argparse.Namespace) -> int:
    repo = find_repo(args.repo)
    info = inspect(repo, args.branch or config()["update_branch"])
    if info["status"] == "available":
        info = apply_update(repo, info, force=args.force)
    record(info)
    emit(info, args.quiet, args.json)
    return 1 if str(info["status"]).startswith("failed") else 0


def cmd_auto(args: argparse.Namespace) -> int:
    cfg = config()
    state = read_json(STATE_PATH, {}) if STATE_PATH.exists() else {}
    last = state.get("last_check") if isinstance(state, dict) else None
    if last and not args.force:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
            if age_h < float(cfg["update_interval_hours"]):
                emit({"status": "throttled"}, args.quiet, args.json)
                return 0
        except ValueError:
            pass
    repo = find_repo(args.repo)
    info = inspect(repo, cfg["update_branch"])
    failed_sha = state.get("failed_sha") if isinstance(state, dict) else None
    if info["status"] == "available" and failed_sha and failed_sha == info.get("remote_sha"):
        # Same commit already failed to install — wait for a newer one instead of retrying every session.
        info["status"] = "known_broken"
    elif info["status"] == "available":
        if cfg["auto_update"]:
            info = apply_update(repo, info, force=False)
        else:
            info["status"] = "disabled"
    record(info)
    emit(info, args.quiet, args.json)
    return 1 if str(info["status"]).startswith("failed") else 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = config()
    state = read_json(STATE_PATH, {})
    try:
        repo = str(find_repo(args.repo))
    except UpdateError as exc:
        repo = f"not found ({exc})"
    print(f"auto_update: {cfg['auto_update']} · branch: {cfg['update_branch']} · "
          f"interval: {cfg['update_interval_hours']}h · checkout: {repo}")
    if isinstance(state, dict) and state.get("last"):
        print(f"last check: {state.get('last_check')} → {message(state['last'])}")
    else:
        print("last check: never")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", help="OneCommand git checkout (default: auto-detect)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, hlp in (("check", cmd_check, "report only"), ("apply", cmd_apply, "install now"),
                            ("auto", cmd_auto, "hook mode: throttled, honours config"),
                            ("status", cmd_status, "show configuration and last result")):
        p = sub.add_parser(name, help=hlp)
        p.set_defaults(func=func)
        if name != "status":
            p.add_argument("--quiet", action="store_true", help="print nothing when there is nothing to act on")
            p.add_argument("--json", action="store_true", help="machine-readable output")
        if name in ("check", "apply"):
            p.add_argument("--branch", help="override update_branch for this run")
        if name in ("apply", "auto"):
            p.add_argument("--force", action="store_true",
                           help="apply: also during a running build · auto: ignore the check interval")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="[update] %(levelname)s %(message)s")
    try:
        return args.func(args)
    except UpdateError as exc:
        if getattr(args, "quiet", False):
            LOG.debug("update skipped: %s", exc)
            return 0  # a SessionStart hook must never block the session
        print(f"[update] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
