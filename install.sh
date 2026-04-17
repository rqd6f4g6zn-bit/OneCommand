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
PLUGIN_VERSION="1.3.0"
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

mkdir -p "$CLAUDE_PLUGINS_DIR"

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

# Register in Claude settings
CLAUDE_SETTINGS="$CLAUDE_DIR/settings.json"

if [ -f "$CLAUDE_SETTINGS" ]; then
  ALREADY_REG=$(python3 - << PYEOF
import json, sys
try:
    d = json.load(open("$CLAUDE_SETTINGS"))
    plugins = d.get("plugins", [])
    found = any(p.get("name") == "onecommand" for p in plugins) if isinstance(plugins, list) \
            else "onecommand" in plugins if isinstance(plugins, dict) \
            else False
    print("yes" if found else "no")
except:
    print("no")
PYEOF
)
  if [ "$ALREADY_REG" = "yes" ]; then
    skip "Claude Code settings (already registered)"
  else
    python3 - << PYEOF
import json, os
path = "$CLAUDE_SETTINGS"
try:
    d = json.load(open(path))
except Exception:
    d = {}
try:
    plugins = d.get("plugins", [])
    if isinstance(plugins, list):
        plugins.append({"name": "onecommand", "path": "$OC_CLAUDE_DIR"})
        d["plugins"] = plugins
        with open(path, "w") as f:
            json.dump(d, f, indent=2)
        print("registered in Claude settings")
except Exception as e:
    print(f"could not auto-register: {e}")
    print(f"manual step: add onecommand to $CLAUDE_SETTINGS")
PYEOF
  fi
else
  info "Creating Claude settings.json"
  cat > "$CLAUDE_SETTINGS" << JSEOF
{
  "plugins": [
    {
      "name": "onecommand",
      "path": "$OC_CLAUDE_DIR"
    }
  ]
}
JSEOF
  ok "Created settings.json with onecommand registered"
fi

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

AGENTSEOF
    ok "Registered OneCommand in AGENTS.md"
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
