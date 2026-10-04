---
description: Diagnose the OneCommand installation. Checks plugin registry, commands, brain, Codex integration. Reports exactly what's broken and how to fix it.
argument-hint: (no arguments needed)
allowed-tools: Bash, Read
---

You are the OneCommand Doctor. Run a complete health check on the OneCommand installation and report a clear pass/fail checklist with concrete fix instructions for any failure.

## Run all checks in one Python block

```bash
python3 << 'EOF'
import json, os, sys, subprocess
from pathlib import Path

HOME = Path.home()
results = []  # (status, label, detail, fix)

def check(label, ok, detail="", fix="", optional=False):
    """optional=True → failures show as ○ (warning), don't count toward fail total."""
    if ok:
        sym = "✓"
    elif optional:
        sym = "○"
    else:
        sym = "✗"
    results.append((sym, label, detail, fix))
    return ok

# ── 1. Repo location ──────────────────────────────────────────────────────────
# Source of truth is the installPath that install.sh wrote into the registry;
# the other locations are fallbacks for manual or partial installs.
def registry_install_path():
    try:
        reg = json.loads((HOME / ".claude" / "plugins" / "installed_plugins.json").read_text())
        entry = reg.get("plugins", {}).get("onecommand@local", [])
        if entry and entry[0].get("installPath"):
            return Path(entry[0]["installPath"]).expanduser()
    except Exception:
        pass
    return None

candidates = [
    Path(os.environ["CLAUDE_PLUGIN_ROOT"]) if os.environ.get("CLAUDE_PLUGIN_ROOT") else None,
    registry_install_path(),
    HOME / "OneCommand",
    HOME / "OneComand",
    HOME / ".claude" / "plugins" / "onecommand",
]
repo = None
for candidate in [c for c in candidates if c is not None]:
    if (candidate / ".claude-plugin" / "plugin.json").exists():
        repo = candidate
        break
check("Repo found", repo is not None,
      f"at {repo}" if repo else "",
      "Clone https://github.com/rqd6f4g6zn-bit/OneCommand and re-run installer")

if not repo:
    print("\n".join(f"  {s} {l}" + (f" — {d}" if d else "") for s,l,d,_ in results))
    sys.exit(1)

# ── 2. Plugin metadata ────────────────────────────────────────────────────────
plugin_json_path = repo / ".claude-plugin" / "plugin.json"
plugin_meta = {}
try:
    plugin_meta = json.loads(plugin_json_path.read_text())
except Exception as e:
    check("plugin.json readable", False, str(e), "Repo corrupted — git pull or re-clone")
expected_version = plugin_meta.get("version", "?")
check("plugin.json version", "version" in plugin_meta,
      f"v{expected_version}",
      "Repo missing .claude-plugin/plugin.json — git pull")

# ── 3. Commands present in repo ───────────────────────────────────────────────
required_cmds = ["onecommand.md", "oc-resume.md", "oc-save.md", "onecommand-status.md", "oc-doctor.md", "oc-update.md"]
cmds_dir = repo / "commands"
missing_cmds = [c for c in required_cmds if not (cmds_dir / c).exists()]
check("All commands in repo", not missing_cmds,
      f"{len(required_cmds)-len(missing_cmds)}/{len(required_cmds)} present",
      f"Missing: {missing_cmds} — git pull or re-run install.sh")

# ── 3b. Quality gate scripts ──────────────────────────────────────────────────
gate_files = ["hooks/quality-gate.sh", "hooks/acceptance-report.py", "hooks/learnings.py",
              "hooks/skill-catalog.py", "hooks/update.py", "hooks/hooks.json", "hooks/checkpoint.py",
              "hooks/playwright-pin.py", "hooks/blueprint.py"]
missing_gate = [g for g in gate_files if not (repo / g).exists()]
check("Build scripts (gate, acceptance, learnings, skills, update, checkpoint)", not missing_gate,
      f"{len(gate_files)}/{len(gate_files)} present" if not missing_gate else "",
      f"Missing: {missing_gate} — git pull (v1.4.0+) and re-run install.sh")

# ── 3c. Auto-update (informational) ───────────────────────────────────────────
try:
    up = subprocess.run([sys.executable, str(repo / "hooks" / "update.py"), "status"],
                        capture_output=True, text=True, timeout=10)
    lines = (up.stdout or up.stderr).strip().splitlines()
    check("Auto-update", up.returncode == 0, " · ".join(lines)[:160],
          "Re-run install.sh", optional=True)
except Exception as e:
    check("Auto-update", False, str(e), "Re-run install.sh", optional=True)

# ── 4. Claude Code: enabledPlugins ────────────────────────────────────────────
settings_path = HOME / ".claude" / "settings.json"
enabled = False
try:
    s = json.loads(settings_path.read_text())
    enabled = s.get("enabledPlugins", {}).get("onecommand@local", False)
except Exception:
    pass
check("Claude settings.json enables onecommand@local", enabled,
      "" if enabled else f"not in {settings_path}",
      'Add to settings.json: "enabledPlugins": {"onecommand@local": true}')

# ── 5. Claude Code: installed_plugins.json registry ───────────────────────────
reg_path = HOME / ".claude" / "plugins" / "installed_plugins.json"
reg_ok, reg_ver, reg_path_val = False, "?", "?"
try:
    reg = json.loads(reg_path.read_text())
    entry = reg.get("plugins", {}).get("onecommand@local", [])
    if entry:
        reg_ver = entry[0].get("version", "?")
        reg_path_val = entry[0].get("installPath", "?")
        reg_ok = (reg_ver == expected_version) and Path(reg_path_val).exists()
except Exception:
    pass
check("installed_plugins.json registry", reg_ok,
      f"v{reg_ver} → {reg_path_val}",
      f"Re-run install.sh (registry says v{reg_ver}, plugin is v{expected_version})")

# ── 6. Brain on disk ──────────────────────────────────────────────────────────
brain_dir = HOME / ".onecommand" / "brain"
brain_files = ["episodic_memory.json", "semantic_memory.json", "pattern_library.json", "user_preferences.json"]
missing_brain = [f for f in brain_files if not (brain_dir / f).exists()]
check("Brain files initialized", not missing_brain,
      f"{len(brain_files)-len(missing_brain)}/{len(brain_files)} present in {brain_dir}",
      f"Missing: {missing_brain} — re-run install.sh")

# ── 7. Active build state (informational) ─────────────────────────────────────
wm_path = brain_dir / "working_memory.json"
if wm_path.exists():
    try:
        wm = json.loads(wm_path.read_text())
        if wm.get("phases_completed"):
            check("Active build", True,
                  f"{wm.get('project_name','?')} — Phase {wm.get('current_phase','?')}/8 (done: {wm.get('phases_completed')})",
                  "")
        else:
            check("Active build", True, "none (clean state)", "")
    except Exception:
        check("Active build", True, "working_memory.json unreadable (ignorable)", "")
else:
    check("Active build", True, "none (clean state)", "")

# ── 8. Codex installation ─────────────────────────────────────────────────────
codex_installed = False
try:
    r = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=3)
    codex_installed = r.returncode == 0
    codex_version = r.stdout.strip() or r.stderr.strip()
except Exception:
    codex_version = ""
check("Codex CLI", codex_installed,
      codex_version if codex_installed else "not in PATH — claude-only mode will be used",
      "Install Codex if you want dual-agent collaboration",
      optional=True)

# ── 9. Codex skills (if Codex installed) ──────────────────────────────────────
if codex_installed:
    codex_skills = HOME / ".codex" / "skills"
    required_codex = ["onecommand", "oc-resume", "oc-save"]
    missing_codex = [s for s in required_codex if not (codex_skills / s).exists()]
    check("Codex skills installed", not missing_codex,
          f"{len(required_codex)-len(missing_codex)}/{len(required_codex)} present",
          f"Re-run install.sh — missing: {missing_codex}")

# ── Print report ──────────────────────────────────────────────────────────────
print("\n┌──────────────────────────────────────────────────────────────┐")
print("│  OneCommand — Doctor Report                                  │")
print("└──────────────────────────────────────────────────────────────┘\n")

for status, label, detail, fix in results:
    line = f"  {status} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if status == "✗" and fix:
        print(f"      → fix: {fix}")

failed   = sum(1 for r in results if r[0] == "✗")
warnings = sum(1 for r in results if r[0] == "○")
passed   = sum(1 for r in results if r[0] == "✓")
total    = len(results)

print(f"\n  {passed}/{total} checks passed", end="")
if warnings: print(f"  ·  {warnings} warning(s)", end="")
if failed:   print(f"  ·  {failed} failure(s)", end="")
print()

if failed == 0:
    msg = "✅ Installation healthy."
    if warnings:
        msg += f" {warnings} optional component(s) missing — see ○ above."
    print(f"\n  {msg}\n  Try: /onecommand \"build me a todo app\"\n")
else:
    print(f"\n  ⚠  {failed} blocking issue(s) — see ✗ fixes above.")
    print(f"  Re-run install.sh from {repo}\n")
    sys.exit(1)
EOF
```

## What this command checks

| # | Check | Why it matters |
|---|---|---|
| 1 | Repo found (`$CLAUDE_PLUGIN_ROOT` → registry `installPath` → `~/OneCommand` → `~/.claude/plugins/onecommand`) | Plugin can't load if installPath is wrong |
| 2 | `plugin.json` readable + has version | Claude Code reads metadata from here |
| 3 | All 6 commands in `commands/` | `/onecommand`, `/oc-resume`, `/oc-save`, `/onecommand-status`, `/oc-doctor`, `/oc-update` available |
| 3c | Auto-update configuration and last check | Shows whether updates install automatically |
| 3b | `hooks/` build scripts present (gate, acceptance, learnings, skill catalog, update + hooks.json) | Phase 4 verdict and acceptance matrix come from these |
| 4 | `enabledPlugins[onecommand@local] === true` | Plugin must be enabled in settings.json |
| 5 | `installed_plugins.json` version matches | Mismatch causes silent load failure |
| 6 | Brain files initialized | Needed for build state, learning |
| 7 | Active build status | Informational — shows resumable build if any |
| 8 | Codex CLI present | Optional — enables dual-agent mode |
| 9 | Codex skills installed (if Codex present) | `/onecommand`, `/oc-resume`, `/oc-save` work in Codex too |

If any check fails, the report prints the exact fix command. Most failures are resolved by re-running `install.sh`.
