#!/usr/bin/env bash
# =============================================================================
# OneCommand — Installer v1.1.2
# USC Software UG — usc-software-ug.de
# =============================================================================
# Idempotent: safe to run multiple times.
# Already installed components are skipped — nothing is downloaded twice.
# =============================================================================

set -euo pipefail

PLUGIN_NAME="onecommand"
PLUGIN_VERSION="1.3.5"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ─── Helpers ──────────────────────────────────────────────────────────────────

info()    { echo -e "${CYAN}  →${RESET} $*"; }
ok()      { echo -e "${GREEN}  ✓${RESET} $*"; }
skip()    { echo -e "${YELLOW}  ○${RESET} $* (already installed — skipped)"; }
warn()    { echo -e "${YELLOW}  ⚠${RESET} $*"; }
err()     { echo -e "${RED}  ✗${RESET} $*"; }
section() { echo -e "\n${BOLD}$*${RESET}"; }

# ─── Banner ───────────────────────────────────────────────────────────────────

echo ""
echo "+==============================================================+"
echo "|         OneCommand — Installer v${PLUGIN_VERSION}                     |"
echo "|          USC Software UG · usc-software-ug.de               |"
echo "+==============================================================+"
echo ""

# ─── Shared memory directory ─────────────────────────────────────────────────

section "[ 1/4 ] Setting up shared memory"

MEMORY_DIR="$HOME/.onecommand/memory"

if [ -d "$MEMORY_DIR" ]; then
  skip "Memory directory $MEMORY_DIR"
else
  mkdir -p "$MEMORY_DIR"
  ok "Created $MEMORY_DIR"
fi

LEARNINGS_FILE="$MEMORY_DIR/cross_learnings.json"
if [ -f "$LEARNINGS_FILE" ]; then
  skip "cross_learnings.json (preserving existing learnings)"
else
  cat > "$LEARNINGS_FILE" << 'EOF'
{
  "version": "1.0",
  "created": "auto",
  "description": "Shared cross-agent learning memory for OneCommand. Read and written by both Claude Code and Codex.",
  "learnings": []
}
EOF
  ok "Initialized cross_learnings.json"
fi

# Brain directories
BRAIN_DIR="$HOME/.onecommand/brain"
if [ -d "$BRAIN_DIR" ]; then
  skip "Brain directory $BRAIN_DIR"
else
  mkdir -p "$BRAIN_DIR/checkpoints" "$BRAIN_DIR/handoff"
  ok "Created brain directory structure"
fi

for brain_file in "episodic_memory.json" "semantic_memory.json" "pattern_library.json" "user_preferences.json"; do
  brain_path="$BRAIN_DIR/$brain_file"
  if [ -f "$brain_path" ]; then
    skip "Brain: $brain_file"
  else
    case "$brain_file" in
      episodic_memory.json)   echo '{"version":"1.0","builds":[]}' > "$brain_path" ;;
      semantic_memory.json)   echo '{"version":"1.0","knowledge":[]}' > "$brain_path" ;;
      pattern_library.json)   echo '{"version":"1.0","patterns":[]}' > "$brain_path" ;;
      user_preferences.json)  echo '{"version":"1.0","preferences":{}}' > "$brain_path" ;;
    esac
    ok "Initialized brain: $brain_file"
  fi
done

CONFIG_FILE="$HOME/.onecommand/config.json"
if [ -f "$CONFIG_FILE" ]; then
  skip "~/.onecommand/config.json (preserving existing config)"
else
  cat > "$CONFIG_FILE" << 'EOF'
{
  "version": "1.3.0",
  "installed_at": "auto",
  "plan": "unknown"
}
EOF
  ok "Created config.json"
fi

# ─── Claude Code installation ────────────────────────────────────────────────

section "[ 2/4 ] Installing into Claude Code"

CLAUDE_DIR="$HOME/.claude"
CLAUDE_PLUGINS_DIR="$CLAUDE_DIR/plugins"
OC_CLAUDE_DIR="$CLAUDE_PLUGINS_DIR/onecommand"
CLAUDE_COMMANDS_DIR="$CLAUDE_DIR/commands"
OC_PLUGIN_COMMANDS_DIR="$OC_CLAUDE_DIR/commands"

mkdir -p "$CLAUDE_PLUGINS_DIR" "$CLAUDE_COMMANDS_DIR"

# Install /oc-resume — into plugin commands (primary) AND ~/.claude/commands (fallback)
# Plugin commands load reliably when the plugin is enabled; ~/.claude/commands is a belt-and-suspenders fallback.
OC_RESUME_PLUGIN="$OC_PLUGIN_COMMANDS_DIR/oc-resume.md"
OC_RESUME_GLOBAL="$CLAUDE_COMMANDS_DIR/oc-resume.md"
if [ -f "$OC_RESUME_PLUGIN" ]; then
  skip "/oc-resume plugin command (already installed)"
else
  mkdir -p "$OC_PLUGIN_COMMANDS_DIR"
  cp "${REPO_ROOT}/.claude-plugin/commands/oc-resume.md" "$OC_RESUME_PLUGIN" 2>/dev/null || \
  cp "${REPO_ROOT}/skills/auto-clear/oc-resume-global.md" "$OC_RESUME_PLUGIN" 2>/dev/null || \
  cat > "$OC_RESUME_PLUGIN" << 'CMDEOF'
---
description: Resume an interrupted OneCommand build after /clear. Continues from exactly the last phase — nothing is lost.
argument-hint: (no arguments needed)
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---
Resume the active OneCommand build. Read ~/.onecommand/brain/working_memory.json and ~/.onecommand/brain/resume_brief.md, verify files on disk, then continue building from the phase indicated in working_memory["current_phase"]. Never re-run completed phases. Never re-generate existing files.
CMDEOF
  ok "Installed /oc-resume → plugin commands"
fi
# Also write to ~/.claude/commands as fallback (idempotent)
[ ! -f "$OC_RESUME_GLOBAL" ] && cp "$OC_RESUME_PLUGIN" "$OC_RESUME_GLOBAL" 2>/dev/null && ok "/oc-resume → ~/.claude/commands (fallback)"

# Install /oc-save — same dual-location strategy
OC_SAVE_PLUGIN="$OC_PLUGIN_COMMANDS_DIR/oc-save.md"
OC_SAVE_GLOBAL="$CLAUDE_COMMANDS_DIR/oc-save.md"
if [ -f "$OC_SAVE_PLUGIN" ]; then
  skip "/oc-save plugin command (already installed)"
else
  mkdir -p "$OC_PLUGIN_COMMANDS_DIR"
  cp "${REPO_ROOT}/.claude-plugin/commands/oc-save.md" "$OC_SAVE_PLUGIN" 2>/dev/null || \
  cp "${REPO_ROOT}/skills/auto-clear/oc-save-global.md" "$OC_SAVE_PLUGIN" 2>/dev/null || \
  cat > "$OC_SAVE_PLUGIN" << 'CMDEOF'
---
description: Save the current OneCommand build state so you can safely run /clear. Run /oc-resume afterwards to continue.
argument-hint: (no arguments needed)
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---
Save the active OneCommand build state to disk. Scan all project files, write file_manifest.json, generate resume_brief.md, create a timestamped checkpoint, then print instructions to /clear and /oc-resume.
CMDEOF
  ok "Installed /oc-save → plugin commands"
fi
[ ! -f "$OC_SAVE_GLOBAL" ] && cp "$OC_SAVE_PLUGIN" "$OC_SAVE_GLOBAL" 2>/dev/null && ok "/oc-save → ~/.claude/commands (fallback)"

if [ -d "$OC_CLAUDE_DIR" ]; then
  # Check version
  INSTALLED_VERSION=""
  for vpath in "$OC_CLAUDE_DIR/.claude-plugin/plugin.json" "$OC_CLAUDE_DIR/plugin.json"; do
    if [ -f "$vpath" ]; then
      INSTALLED_VERSION=$(python3 -c "import json; d=json.load(open('$vpath')); print(d.get('version','0'))" 2>/dev/null || echo "0")
      break
    fi
  done
  if [ "$INSTALLED_VERSION" = "$PLUGIN_VERSION" ]; then
    skip "Claude Code plugin (v${INSTALLED_VERSION} already current)"
  else
    info "Upgrading Claude Code plugin: v${INSTALLED_VERSION} → v${PLUGIN_VERSION}"
    rsync -a --delete "${REPO_ROOT}/" "$OC_CLAUDE_DIR/" \
      --exclude='.git' \
      --exclude='install.sh' \
      --exclude='.codex-plugin' \
      --exclude='README.md' \
      --exclude='LICENSE' \
      --exclude='NOTICE' \
      --exclude='docs'
    ok "Upgraded to v${PLUGIN_VERSION}"
  fi
else
  info "Copying plugin files to $OC_CLAUDE_DIR"
  mkdir -p "$OC_CLAUDE_DIR"
  rsync -a "${REPO_ROOT}/" "$OC_CLAUDE_DIR/" \
    --exclude='.git' \
    --exclude='install.sh' \
    --exclude='.codex-plugin' \
    --exclude='README.md' \
    --exclude='LICENSE' \
    --exclude='NOTICE' \
    --exclude='docs'
  ok "Copied plugin files"
fi

# Register in Claude settings (enabledPlugins) + installed_plugins.json registry
CLAUDE_SETTINGS="$CLAUDE_DIR/settings.json"
INSTALLED_PLUGINS="$CLAUDE_PLUGINS_DIR/installed_plugins.json"

python3 - << PYEOF
import json, os
from datetime import datetime, timezone

# ── 1. settings.json → enabledPlugins ───────────────────────────────────────
settings_path = "$CLAUDE_SETTINGS"
try:
    d = json.load(open(settings_path)) if os.path.exists(settings_path) else {}
except Exception:
    d = {}

ep = d.get("enabledPlugins", {})
if "onecommand@local" in ep:
    print("○ Claude settings (onecommand@local already enabled — skipped)")
else:
    ep["onecommand@local"] = True
    d["enabledPlugins"] = ep
    with open(settings_path, "w") as f:
        json.dump(d, f, indent=2)
    print("✓ Registered onecommand@local in enabledPlugins")

# ── 2. installed_plugins.json → registry ────────────────────────────────────
reg_path = "$INSTALLED_PLUGINS"
try:
    reg = json.load(open(reg_path)) if os.path.exists(reg_path) else {"version": 2, "plugins": {}}
except Exception:
    reg = {"version": 2, "plugins": {}}

existing = reg["plugins"].get("onecommand@local", [{}])[0]
existing_ver = existing.get("version", "0")
if existing_ver == "$PLUGIN_VERSION":
    print(f"○ installed_plugins.json (v{existing_ver} already current — skipped)")
else:
    reg["plugins"]["onecommand@local"] = [{
        "scope": "user",
        "installPath": "$REPO_ROOT",
        "version": "$PLUGIN_VERSION",
        "installedAt": existing.get("installedAt", datetime.now(timezone.utc).isoformat()),
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "gitCommitSha": "local"
    }]
    with open(reg_path, "w") as f:
        json.dump(reg, f, indent=2)
    print(f"✓ installed_plugins.json updated: {existing_ver} → $PLUGIN_VERSION")
PYEOF

# ─── Codex installation ───────────────────────────────────────────────────────

section "[ 3/4 ] Installing into Codex"

CODEX_DIR="$HOME/.codex"
CODEX_SKILLS_DIR="$CODEX_DIR/skills"
OC_CODEX_SKILL_DIR="$CODEX_SKILLS_DIR/onecommand"
CODEX_AGENTS_FILE="$CODEX_DIR/AGENTS.md"

if ! command -v codex &>/dev/null; then
  warn "Codex not found in PATH — skipping Codex installation"
  warn "Install Codex later and re-run this script to register OneCommand"
else
  mkdir -p "$CODEX_SKILLS_DIR"

  # Copy the onecommand Codex skill
  CODEX_SKILL_SRC="${REPO_ROOT}/.codex-plugin/skills/onecommand"

  if [ -d "$OC_CODEX_SKILL_DIR" ]; then
    CODEX_VER=""
    if [ -f "$OC_CODEX_SKILL_DIR/SKILL.md" ]; then
      CODEX_VER=$(grep -m1 'version:' "$OC_CODEX_SKILL_DIR/SKILL.md" 2>/dev/null | awk '{print $2}' || echo "")
    fi
    if [ -n "$CODEX_VER" ] && [[ "$CODEX_VER" == *"${PLUGIN_VERSION}"* ]]; then
      skip "Codex onecommand skill (already current)"
    else
      info "Updating Codex onecommand skill"
      rsync -a "${CODEX_SKILL_SRC}/" "$OC_CODEX_SKILL_DIR/"
      ok "Updated Codex skill"
    fi
  else
    info "Installing Codex onecommand skill to $OC_CODEX_SKILL_DIR"
    mkdir -p "$OC_CODEX_SKILL_DIR"
    rsync -a "${CODEX_SKILL_SRC}/" "$OC_CODEX_SKILL_DIR/"
    ok "Installed Codex skill"
  fi

  # Copy all bundled skills to ~/.codex/skills/ as well
  for skill_dir in "${REPO_ROOT}/skills"/*/; do
    skill_name=$(basename "$skill_dir")
    dest="$CODEX_SKILLS_DIR/$skill_name"

    if [ -d "$dest" ]; then
      skip "Codex skill: $skill_name"
    else
      mkdir -p "$dest"
      rsync -a "$skill_dir" "$dest/"
      ok "Installed bundled skill: $skill_name"
    fi
  done

  # Install /oc-resume as global Codex skill
  OC_RESUME_CODEX="$CODEX_SKILLS_DIR/oc-resume"
  if [ -d "$OC_RESUME_CODEX" ]; then
    skip "Codex /oc-resume skill (already installed)"
  else
    mkdir -p "$OC_RESUME_CODEX"
    cat > "$OC_RESUME_CODEX/SKILL.md" << 'SKILLEOF'
---
name: oc-resume
description: Resume an interrupted OneCommand build after /clear. Continues from exactly the last phase — nothing is lost.
model: claude-opus-4-7
---
Resume the active OneCommand build. Read ~/.onecommand/brain/working_memory.json and ~/.onecommand/brain/resume_brief.md, verify files on disk, then continue building from the phase indicated in working_memory["current_phase"]. Never re-run completed phases. Never re-generate existing files.
SKILLEOF
    ok "Installed /oc-resume global Codex skill"
  fi

  # Install /oc-save as global Codex skill
  OC_SAVE_CODEX="$CODEX_SKILLS_DIR/oc-save"
  if [ -d "$OC_SAVE_CODEX" ]; then
    skip "Codex /oc-save skill (already installed)"
  else
    mkdir -p "$OC_SAVE_CODEX"
    cat > "$OC_SAVE_CODEX/SKILL.md" << 'SKILLEOF'
---
name: oc-save
description: Manually save the current OneCommand build state so /clear is safe at any moment. Generates resume_brief.md + file_manifest.json, then prints /clear + /oc-resume instructions.
model: claude-opus-4-7
---
Save the active OneCommand build state to disk. Read ~/.onecommand/brain/working_memory.json, scan all project files into file_manifest.json, write resume_brief.md with current phase/stack/decisions, create a timestamped checkpoint, then print a confirmation box instructing the user to /clear and /oc-resume.
SKILLEOF
    ok "Installed /oc-save global Codex skill"
  fi

  # Register in AGENTS.md
  if [ -f "$CODEX_AGENTS_FILE" ] && grep -q "onecommand" "$CODEX_AGENTS_FILE" 2>/dev/null; then
    skip "Codex AGENTS.md (onecommand already registered)"
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

  # Register in config.toml
  CODEX_CONFIG="${CODEX_DIR}/config.toml"
  if [ -f "$CODEX_CONFIG" ] && grep -q "onecommand" "$CODEX_CONFIG" 2>/dev/null; then
    skip "Codex config.toml (already registered)"
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
)

all_ok=true
for skill in "${BUNDLED_SKILLS[@]}"; do
  skill_path="${REPO_ROOT}/skills/${skill}/SKILL.md"
  if [ -f "$skill_path" ]; then
    ok "Bundled skill: $skill"
  else
    warn "Missing skill file: skills/${skill}/SKILL.md"
    all_ok=false
  fi
done

# ─── Done ─────────────────────────────────────────────────────────────────────

echo ""
if [ "$all_ok" = true ]; then
  echo "+==============================================================+"
  echo "|        ✅ OneCommand v${PLUGIN_VERSION} — Install Complete            |"
  echo "+==============================================================+"
  echo "|                                                              |"
  echo "|  Version : ${PLUGIN_VERSION}                                          |"
  echo "|  Claude Code : ~/.claude/plugins/onecommand/                 |"
  echo "|  Codex       : ~/.codex/skills/onecommand/                   |"
  echo "|  Memory      : ~/.onecommand/memory/                         |"
  echo "|                                                              |"
  echo "|  OneCommand — Built by USC Software UG                       |"
  echo "|  Copyright © 2026 USC Software UG                            |"
  echo "|  Alle Rechte vorbehalten · All rights reserved               |"
  echo "|              >> usc-software-ug.de <<                        |"
  echo "+==============================================================+"
  echo ""
  echo "  Usage in Claude Code:  /onecommand \"your project description\""
  echo "  Usage in Codex:        /einbefehl  \"your project description\""
  echo ""
else
  echo "+==============================================================+"
  echo "|     ⚠ OneCommand — Installed with warnings                  |"
  echo "+==============================================================+"
  echo "|  Some skill files are missing. Re-run after fixing them.     |"
  echo "|  >> usc-software-ug.de <<                                    |"
  echo "+==============================================================+"
  echo ""
fi
