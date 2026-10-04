#!/usr/bin/env bash
# =============================================================================
# OneCommand — Installer
# USC Software UG — usc-software-ug.de
# =============================================================================
# Idempotent: safe to run multiple times.
# Files are synced by content, so re-running after `git pull` picks up every
# change — even without a version bump — and unchanged files are left alone.
#
# Usage:  ./install.sh [--dry-run] [--verbose] [--help]
# =============================================================================

set -euo pipefail

PLUGIN_NAME="onecommand"
PLUGIN_VERSION="1.5.0"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN=false
VERBOSE=false

# Colors (disabled when stdout is not a terminal)
if [ -t 1 ]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
  CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; RESET=''
fi

# ─── Helpers ──────────────────────────────────────────────────────────────────

info()    { echo -e "${CYAN}  →${RESET} $*"; }
ok()      { echo -e "${GREEN}  ✓${RESET} $*"; }
skip()    { echo -e "${YELLOW}  ○${RESET} $* (already current — skipped)"; }
warn()    { echo -e "${YELLOW}  ⚠${RESET} $*"; }
err()     { echo -e "${RED}  ✗${RESET} $*" >&2; }
debug()   { if [ "$VERBOSE" = true ]; then echo -e "    · $*"; fi; }
section() { echo -e "\n${BOLD}$*${RESET}"; }
box()     { echo "|  $*"; }
tilde()   { case "$1" in "$HOME"*) printf '~%s' "${1#"$HOME"}" ;; *) printf '%s' "$1" ;; esac; }
rule()    { echo "+==============================================================+"; }

usage() {
  cat << USAGE
OneCommand installer v${PLUGIN_VERSION}

Usage: ./install.sh [options]

Options:
  -n, --dry-run   Show what would change without writing anything
  -v, --verbose   Print every file that is created, updated or deleted
  -h, --help      Show this help and exit

Installs OneCommand into Claude Code (~/.claude) and, if the codex CLI is in
PATH, into Codex (~/.codex). Shared memory lives in ~/.onecommand.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    -n|--dry-run) DRY_RUN=true ;;
    -v|--verbose) VERBOSE=true ;;
    -h|--help)    usage; exit 0 ;;
    *)            err "Unknown option: $1"; usage >&2; exit 2 ;;
  esac
  shift
done

# Run a mutating command, or only describe it in dry-run mode.
run() {
  if [ "$DRY_RUN" = true ]; then
    debug "dry-run: $*"
  else
    "$@"
  fi
}

# sync_dir <src/> <dest/> <label> [extra rsync args...]
# Mirrors src into dest and reports whether anything actually changed.
sync_dir() {
  local src="$1" dest="$2" label="$3"
  shift 3
  local -a args=(-a --itemize-changes "$@")
  [ "$DRY_RUN" = true ] && args+=(--dry-run)

  if [ ! -d "$src" ]; then
    err "Source directory missing: $src"
    return 1
  fi
  [ "$DRY_RUN" = true ] || mkdir -p "$dest"

  local output changed
  output="$(rsync "${args[@]}" "$src" "$dest")"
  # Count file-level changes only: lines starting with '.' are attribute-only
  # (timestamps etc.) and '?d' lines are directories.
  local pattern='^([<>ch][^d]|\*deleting)'
  changed="$(printf '%s\n' "$output" | grep -cE "$pattern" || true)"

  if [ "$changed" -eq 0 ]; then
    skip "$label"
  else
    ok "$label — ${changed} file(s) $([ "$DRY_RUN" = true ] && echo "would change" || echo "synced")"
    if [ "$VERBOSE" = true ]; then
      printf '%s\n' "$output" | grep -E "$pattern" | sed 's/^/    · /'
    fi
  fi
}

# install_file <src> <dest> <label> — copies only when content differs.
install_file() {
  local src="$1" dest="$2" label="$3"
  if [ ! -f "$src" ]; then
    err "Source file missing: $src"
    return 1
  fi
  if [ -f "$dest" ] && cmp -s "$src" "$dest"; then
    skip "$label"
    return 0
  fi
  local verb="Installed"
  [ -f "$dest" ] && verb="Updated"
  run mkdir -p "$(dirname "$dest")"
  run cp "$src" "$dest"
  ok "${verb} ${label}"
}

# write_if_missing <dest> <label> — writes stdin to dest unless dest exists.
write_if_missing() {
  local dest="$1" label="$2" content
  content="$(cat)"
  if [ -f "$dest" ]; then
    skip "$label"
    return 0
  fi
  if [ "$DRY_RUN" = false ]; then
    mkdir -p "$(dirname "$dest")"
    printf '%s\n' "$content" > "$dest"
  fi
  ok "Initialized $label"
}

# ─── Banner ───────────────────────────────────────────────────────────────────

echo ""
rule
box "OneCommand — Installer v${PLUGIN_VERSION}"
box "USC Software UG · usc-software-ug.de"
[ "$DRY_RUN" = true ] && box "DRY RUN — nothing will be written"
rule

# ─── Prerequisites ────────────────────────────────────────────────────────────

section "[ 0/4 ] Checking prerequisites"

missing_tools=()
for tool in python3 rsync cmp; do
  if command -v "$tool" &>/dev/null; then
    debug "$tool → $(command -v "$tool")"
  else
    missing_tools+=("$tool")
  fi
done
if [ ${#missing_tools[@]} -gt 0 ]; then
  err "Missing required tools: ${missing_tools[*]}"
  err "macOS: xcode-select --install   ·   Debian/Ubuntu: sudo apt install python3 rsync diffutils"
  exit 1
fi
ok "python3, rsync, cmp available"

for manifest in "$REPO_ROOT/.claude-plugin/plugin.json" "$REPO_ROOT/commands/onecommand.md" \
                "$REPO_ROOT/hooks/quality-gate.sh" "$REPO_ROOT/hooks/acceptance-report.py" \
                "$REPO_ROOT/hooks/learnings.py" "$REPO_ROOT/hooks/skill-catalog.py" \
                "$REPO_ROOT/hooks/update.py" "$REPO_ROOT/hooks/hooks.json" "$REPO_ROOT/hooks/checkpoint.py"; do
  if [ ! -f "$manifest" ]; then
    err "Not a OneCommand checkout: $manifest missing (REPO_ROOT=$REPO_ROOT)"
    exit 1
  fi
done

MANIFEST_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version",""))' \
  "$REPO_ROOT/.claude-plugin/plugin.json")"
if [ "$MANIFEST_VERSION" != "$PLUGIN_VERSION" ]; then
  warn "plugin.json says v${MANIFEST_VERSION}, installer says v${PLUGIN_VERSION} — using v${PLUGIN_VERSION}"
fi

# ─── Shared memory directory ─────────────────────────────────────────────────

section "[ 1/4 ] Setting up shared memory"

ONECOMMAND_HOME="$HOME/.onecommand"
MEMORY_DIR="$ONECOMMAND_HOME/memory"
BRAIN_DIR="$ONECOMMAND_HOME/brain"

for dir in "$MEMORY_DIR" "$BRAIN_DIR/checkpoints" "$BRAIN_DIR/handoff"; do
  if [ -d "$dir" ]; then
    skip "Directory $(tilde "$dir")"
  else
    run mkdir -p "$dir"
    ok "Created $(tilde "$dir")"
  fi
done

write_if_missing "$MEMORY_DIR/cross_learnings.json" "cross_learnings.json" << 'EOF'
{
  "version": "1.0",
  "created": "auto",
  "description": "Shared cross-agent learning memory for OneCommand. Read and written by both Claude Code and Codex.",
  "learnings": []
}
EOF

echo '{"version":"1.0","builds":[]}'        | write_if_missing "$BRAIN_DIR/episodic_memory.json"  "brain: episodic_memory.json"
echo '{"version":"1.0","knowledge":[]}'     | write_if_missing "$BRAIN_DIR/semantic_memory.json"  "brain: semantic_memory.json"
echo '{"version":"1.0","patterns":[]}'      | write_if_missing "$BRAIN_DIR/pattern_library.json"  "brain: pattern_library.json"
echo '{"version":"1.0","preferences":{}}'   | write_if_missing "$BRAIN_DIR/user_preferences.json" "brain: user_preferences.json"

# Learned rules live in ~/.onecommand/memory/evolved_rules.md since v1.4.1. Rebuild it from
# cross_learnings.json so rules promoted by older versions (written into skill files) survive.
if [ "$DRY_RUN" = true ]; then
  debug "dry-run: would rebuild evolved_rules.md from cross_learnings.json"
elif ! evolve_out="$(ONECOMMAND_MEMORY_DIR="$MEMORY_DIR" python3 "$REPO_ROOT/hooks/learnings.py" evolve 2>&1)"; then
  warn "Could not rebuild evolved rules: $evolve_out"
else
  debug "$evolve_out"
  case "$evolve_out" in
    *promoted*) ok "Evolved rules → ~/.onecommand/memory/evolved_rules.md" ;;
    *)          skip "Evolved rules" ;;
  esac
fi

# config.json — create, or bump only the "version" field and keep everything else.
CONFIG_FILE="$ONECOMMAND_HOME/config.json"
CONFIG_RESULT="$(OC_CONFIG="$CONFIG_FILE" OC_VERSION="$PLUGIN_VERSION" OC_DRY="$DRY_RUN" python3 << 'PYEOF'
import json, os, tempfile
from datetime import datetime, timezone

path, version, dry = os.environ["OC_CONFIG"], os.environ["OC_VERSION"], os.environ["OC_DRY"] == "true"
if os.path.exists(path):
    try:
        with open(path) as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print(f"error:config.json unreadable ({e}) — left untouched")
        raise SystemExit(0)
    if not isinstance(cfg, dict):
        print("error:config.json is not a JSON object — left untouched")
        raise SystemExit(0)
    # Auto-update settings (v1.5.0+): add defaults, never override a user's choice.
    defaults = {"auto_update": True, "update_branch": "main", "update_interval_hours": 6}
    missing = {k: v for k, v in defaults.items() if k not in cfg}
    cfg.update(missing)
    if cfg.get("version") == version and not missing:
        print("skip")
        raise SystemExit(0)
    old = cfg.get("version", "?")
    cfg["version"] = version
    cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
    msg = f"updated:v{old} → v{version}"
else:
    cfg = {"version": version, "installed_at": datetime.now(timezone.utc).isoformat(), "plan": "unknown",
           "auto_update": True, "update_branch": "main", "update_interval_hours": 6}
    msg = "created"
if not dry:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".config.", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
print(msg)
PYEOF
)"
case "$CONFIG_RESULT" in
  skip)      skip "config.json in ~/.onecommand" ;;
  created)   ok "Created ~/.onecommand/config.json" ;;
  updated:*) ok "config.json version ${CONFIG_RESULT#updated:}" ;;
  error:*)   warn "${CONFIG_RESULT#error:}" ;;
esac

# ─── Claude Code installation ────────────────────────────────────────────────

section "[ 2/4 ] Installing into Claude Code"

CLAUDE_DIR="$HOME/.claude"
CLAUDE_PLUGINS_DIR="$CLAUDE_DIR/plugins"
OC_CLAUDE_DIR="$CLAUDE_PLUGINS_DIR/$PLUGIN_NAME"
CLAUDE_COMMANDS_DIR="$CLAUDE_DIR/commands"

run mkdir -p "$CLAUDE_PLUGINS_DIR" "$CLAUDE_COMMANDS_DIR"

# Plugin copy — content-synced, so upgrades never depend on a version bump.
sync_dir "${REPO_ROOT}/" "$OC_CLAUDE_DIR/" "Claude Code plugin files → $(tilde "$OC_CLAUDE_DIR")" \
  --delete \
  --exclude='.git' \
  --exclude='.gitignore' \
  --exclude='__pycache__' \
  --exclude='install.sh' \
  --exclude='.codex-plugin' \
  --exclude='README.md' \
  --exclude='LICENSE' \
  --exclude='NOTICE' \
  --exclude='docs'

# /oc-resume and /oc-save also go to ~/.claude/commands as a fallback that
# works even when plugin loading fails. Updated whenever the source changes.
for cmd in oc-resume oc-save; do
  install_file "${REPO_ROOT}/commands/${cmd}.md" "$CLAUDE_COMMANDS_DIR/${cmd}.md" "/${cmd} → ~/.claude/commands (fallback)"
done

# Register in Claude settings (enabledPlugins) + installed_plugins.json registry.
# Paths are passed via environment variables so quotes/spaces cannot break the
# Python source, and files are replaced atomically. A settings.json that does
# not parse is never overwritten — that would wipe the user's other settings.
OC_SETTINGS="$CLAUDE_DIR/settings.json" \
OC_REGISTRY="$CLAUDE_PLUGINS_DIR/installed_plugins.json" \
OC_INSTALL_PATH="$REPO_ROOT" \
OC_VERSION="$PLUGIN_VERSION" \
OC_KEY="${PLUGIN_NAME}@local" \
OC_DRY="$DRY_RUN" \
python3 << 'PYEOF'
import json, os, sys, tempfile
from datetime import datetime, timezone

settings_path = os.environ["OC_SETTINGS"]
reg_path      = os.environ["OC_REGISTRY"]
install_path  = os.environ["OC_INSTALL_PATH"]
version       = os.environ["OC_VERSION"]
key           = os.environ["OC_KEY"]
dry           = os.environ["OC_DRY"] == "true"
failed        = False

def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value is not an object")
    return data

def save(path, data):
    if dry:
        return
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".oc-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)

# ── 1. settings.json → enabledPlugins ───────────────────────────────────────
try:
    settings = load(settings_path, {})
    ep = settings.get("enabledPlugins")
    if not isinstance(ep, dict):
        ep = {}
    if ep.get(key) is True:
        print(f"  ○ settings.json ({key} already enabled — skipped)")
    else:
        ep[key] = True
        settings["enabledPlugins"] = ep
        save(settings_path, settings)
        print(f"  ✓ Enabled {key} in settings.json")
except (OSError, ValueError) as e:
    failed = True
    print(f"  ✗ {settings_path} could not be parsed ({e}).", file=sys.stderr)
    print(f'    Left untouched. Fix the JSON, then add "enabledPlugins": {{"{key}": true}} or re-run install.sh.', file=sys.stderr)

# ── 2. installed_plugins.json → registry ────────────────────────────────────
try:
    reg = load(reg_path, {"version": 2, "plugins": {}})
    plugins = reg.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        reg["plugins"] = plugins
    entries = plugins.get(key)
    existing = entries[0] if isinstance(entries, list) and entries and isinstance(entries[0], dict) else {}
    if existing.get("version") == version and existing.get("installPath") == install_path:
        print(f"  ○ installed_plugins.json (v{version} already current — skipped)")
    else:
        now = datetime.now(timezone.utc).isoformat()
        plugins[key] = [{
            "scope": "user",
            "installPath": install_path,
            "version": version,
            "installedAt": existing.get("installedAt", now),
            "lastUpdated": now,
            "gitCommitSha": "local",
        }]
        save(reg_path, reg)
        print(f"  ✓ installed_plugins.json: v{existing.get('version', 'none')} → v{version}")
except (OSError, ValueError) as e:
    failed = True
    print(f"  ✗ {reg_path} could not be parsed ({e}) — left untouched.", file=sys.stderr)

sys.exit(1 if failed else 0)
PYEOF

# ─── Codex installation ───────────────────────────────────────────────────────

section "[ 3/4 ] Installing into Codex"

CODEX_DIR="$HOME/.codex"
CODEX_SKILLS_DIR="$CODEX_DIR/skills"
OC_CODEX_SKILL_DIR="$CODEX_SKILLS_DIR/$PLUGIN_NAME"
CODEX_AGENTS_FILE="$CODEX_DIR/AGENTS.md"
CODEX_CONFIG="$CODEX_DIR/config.toml"

if ! command -v codex &>/dev/null; then
  warn "Codex not found in PATH — skipping Codex installation"
  warn "Install Codex later and re-run this script to register OneCommand"
else
  run mkdir -p "$CODEX_SKILLS_DIR"

  sync_dir "${REPO_ROOT}/.codex-plugin/skills/onecommand/" "$OC_CODEX_SKILL_DIR/" "Codex skill: onecommand"
  # Quality gate + acceptance report — the Codex skill calls them from here.
  sync_dir "${REPO_ROOT}/hooks/" "$OC_CODEX_SKILL_DIR/hooks/" "Codex hooks: quality gate" --delete --exclude='__pycache__'

  # Bundled skills — synced by content so upgrades reach existing installs.
  for skill_dir in "${REPO_ROOT}/skills"/*/; do
    skill_name="$(basename "$skill_dir")"
    sync_dir "$skill_dir" "$CODEX_SKILLS_DIR/$skill_name/" "Codex skill: $skill_name"
  done

  # Second instruction files removed in v1.4.1 — the bundled-skill sync above never deletes,
  # so clear the stale copies (and the old self-healer sync target) explicitly.
  for obsolete in self-healer/self-healer.md spec-analyzer/spec-analyzer.md \
                  delivery-reporter/delivery-reporter.md automation-installer/automation-installer.md \
                  demo-cleaner/demo-cleaner.md exceed-expectations/exceed-expectations.md \
                  stack-detector/stack-detector.md store-readiness-checker/store-readiness-checker.md \
                  onecommand/self-healer.md; do
    if [ -f "$CODEX_SKILLS_DIR/$obsolete" ]; then
      run rm -f "$CODEX_SKILLS_DIR/$obsolete"
      ok "Removed obsolete Codex file: $obsolete"
    fi
  done

  # Global /oc-resume and /oc-save Codex skills (user may customise — never overwritten)
  write_if_missing "$CODEX_SKILLS_DIR/oc-resume/SKILL.md" "Codex skill: oc-resume" << 'SKILLEOF'
---
name: oc-resume
description: Resume an interrupted OneCommand build after /clear. Continues from exactly the last phase — nothing is lost.
---
Resume the active OneCommand build. Read ~/.onecommand/brain/working_memory.json and ~/.onecommand/brain/resume_brief.md, verify files on disk, then continue building from the phase indicated in working_memory["current_phase"]. Never re-run completed phases. Never re-generate existing files.
SKILLEOF

  write_if_missing "$CODEX_SKILLS_DIR/oc-save/SKILL.md" "Codex skill: oc-save" << 'SKILLEOF'
---
name: oc-save
description: Manually save the current OneCommand build state so /clear is safe at any moment. Generates resume_brief.md + file_manifest.json, then prints /clear + /oc-resume instructions.
---
Save the active OneCommand build state to disk. Read ~/.onecommand/brain/working_memory.json, scan all project files into file_manifest.json, write resume_brief.md with current phase/stack/decisions, create a timestamped checkpoint, then print a confirmation box instructing the user to /clear and /oc-resume.
SKILLEOF

  # Register in AGENTS.md
  if [ -f "$CODEX_AGENTS_FILE" ] && grep -q "onecommand" "$CODEX_AGENTS_FILE" 2>/dev/null; then
    skip "Codex AGENTS.md registration"
  elif [ "$DRY_RUN" = true ]; then
    ok "Would register OneCommand + oc-resume + oc-save in AGENTS.md"
  else
    cat >> "$CODEX_AGENTS_FILE" << 'AGENTSEOF'

# ── OneCommand ──────────────────────────────────────────────────────────────
# Invocation aliases — all trigger the OneCommand build system
# Aliases: /onecommand, /einbefehl, /one-command, /onecomand (typo-tolerant)
# Natural language: "build me a ...", "erstelle mir ...", "mit einem befehl ..."
# The skill auto-recognizes all name variants incl. translator rewrites.

Use the `onecommand` skill when the user invokes any of:
  /onecommand · /einbefehl · /einkommando · /einzelbefehl · /one-command
  /onecomand · /unikommando · /uni-kommando · /alleinbefehl
  "mit einem befehl" · "single command build" · "one command build"
  "erstelle mir" + project description · "build me" + project description

# ── oc-resume (global) ──────────────────────────────────────────────────────
# Resumes interrupted OneCommand builds after /clear
Use the `oc-resume` skill when the user types:
  /oc-resume · /resume · /weiter · /fortfahren
  "resume build" · "weitermachen" · "wo war ich" · "build fortsetzen"

# ── oc-save (global) ────────────────────────────────────────────────────────
# Manually saves current build state so /clear is safe at any moment
Use the `oc-save` skill when the user types:
  /oc-save · /save · /sichern · /speichern
  "save build" · "build sichern" · "save state" · "alles speichern"

AGENTSEOF
    ok "Registered OneCommand + oc-resume + oc-save in AGENTS.md"
  fi

  # Register in config.toml — append once, then keep the version line current.
  if [ -f "$CODEX_CONFIG" ] && grep -q '^\[plugins\.onecommand\]' "$CODEX_CONFIG" 2>/dev/null; then
    if sed -n '/^\[plugins\.onecommand\]/,/^\[/p' "$CODEX_CONFIG" | grep -q "^version = \"${PLUGIN_VERSION}\"$"; then
      skip "Codex config.toml registration"
    else
      if [ "$DRY_RUN" = false ]; then
        tmp_toml="$(mktemp "${CODEX_DIR}/.config.toml.XXXXXX")"
        awk -v ver="$PLUGIN_VERSION" '
          /^\[/ { in_oc = ($0 == "[plugins.onecommand]") }
          in_oc && /^version = / { print "version = \"" ver "\""; next }
          { print }
        ' "$CODEX_CONFIG" > "$tmp_toml"
        mv "$tmp_toml" "$CODEX_CONFIG"
      fi
      ok "Codex config.toml → v${PLUGIN_VERSION}"
    fi
  elif [ "$DRY_RUN" = true ]; then
    ok "Would register OneCommand in config.toml"
  else
    cat >> "$CODEX_CONFIG" << TOMLEOF

# OneCommand plugin
[plugins.onecommand]
path = "${OC_CODEX_SKILL_DIR}"
version = "${PLUGIN_VERSION}"
TOMLEOF
    ok "Registered in config.toml"
  fi
fi

# ─── Bundled skills verification ─────────────────────────────────────────────

section "[ 4/4 ] Verifying bundled skills"

BUNDLED_SKILLS=(
  "oc-frontend-design"
  "oc-ui-ux"
  "oc-marketing"
  "app-icon-generator"
  "spec-analyzer"
  "stack-detector"
  "self-healer"
  "live-integrations"
  "codex-setup"
  "cross-agent-sync"
  "automation-installer"
  "delivery-reporter"
  "exceed-expectations"
  "demo-cleaner"
  "store-readiness-checker"
  "game-engine-selector"
  "godot-builder"
  "threejs-builder"
  "phaser-builder"
  "asset-generator"
  "os-builder"
  "brain-core"
  "context-manager"
  "collab-protocol"
  "auto-clear"
  "21st-components"
  "acceptance-tester"
)

all_ok=true
for skill in "${BUNDLED_SKILLS[@]}"; do
  if [ -f "${REPO_ROOT}/skills/${skill}/SKILL.md" ]; then
    debug "Bundled skill: $skill"
  else
    warn "Missing skill file: skills/${skill}/SKILL.md"
    all_ok=false
  fi
done
$all_ok && ok "All ${#BUNDLED_SKILLS[@]} bundled skills present"

# Each skill has exactly one instruction file. A second *.md next to SKILL.md is
# never loaded and drifts out of sync — that is how learnings got lost before v1.4.1.
for skill_dir in "${REPO_ROOT}/skills"/*/; do
  for extra in "$skill_dir"*.md; do
    [ -e "$extra" ] || continue
    case "$(basename "$extra")" in
      SKILL.md|*-global.md) ;;   # *-global.md: command templates installed by auto-clear
      *) warn "Second instruction file next to SKILL.md: ${extra#"$REPO_ROOT"/} (merge it into SKILL.md)" ;;
    esac
  done
done

# Every bundled skill needs a phase mapping, otherwise no build would ever use it.
if ! mapping_out="$(python3 "$REPO_ROOT/hooks/skill-catalog.py" verify-bundled --oc-root "$REPO_ROOT" 2>&1)"; then
  while IFS= read -r line; do warn "Skill plan: $line"; done <<< "$mapping_out"
  all_ok=false
else
  ok "All bundled skills mapped to build phases"
fi

# Skills on disk that the list above does not know about.
for skill_dir in "${REPO_ROOT}/skills"/*/; do
  skill_name="$(basename "$skill_dir")"
  if [[ ! " ${BUNDLED_SKILLS[*]} " == *" ${skill_name} "* ]]; then
    warn "Unlisted skill directory: skills/${skill_name} (add it to BUNDLED_SKILLS)"
  fi
done

# ─── Done ─────────────────────────────────────────────────────────────────────

echo ""
rule
if [ "$all_ok" = true ]; then
  if [ "$DRY_RUN" = true ]; then
    box "OneCommand v${PLUGIN_VERSION} — Dry run complete (nothing written)"
  else
    box "OneCommand v${PLUGIN_VERSION} — Install complete"
  fi
  rule
  box ""
  box "Claude Code : ~/.claude/plugins/onecommand/"
  box "Codex       : ~/.codex/skills/onecommand/"
  box "Memory      : ~/.onecommand/memory/"
  box ""
  box "OneCommand — Built by USC Software UG"
  box "Copyright © 2026 USC Software UG"
  box "Alle Rechte vorbehalten · All rights reserved"
  box ">> usc-software-ug.de <<"
  rule
  echo ""
  echo "  Usage in Claude Code:  /onecommand \"your project description\""
  echo "  Usage in Codex:        /einbefehl  \"your project description\""
  echo "  Health check:          /oc-doctor"
  echo "  Updates:               automatic at session start · /oc-update to update now"
  echo ""
else
  box "OneCommand — Installed with warnings"
  rule
  box "Some skill files are missing. Re-run after fixing them."
  box ">> usc-software-ug.de <<"
  rule
  echo ""
  exit 1
fi
