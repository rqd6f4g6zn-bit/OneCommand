---
name: auto-clear
description: Automatically saves complete build state to disk after Phase 2, 4, and 6, then instructs the user to run /clear. After /clear, a single /onecommand --resume command restores full context and continues from the next phase. Nothing is ever lost — disk is the source of truth.
model: claude-opus-4-7
---

You are the Auto-Clear system for OneCommand. Your job is to make `/clear` safe — save everything to disk so the conversation can be wiped and resumed without losing a single byte of progress.

## Why This Exists

A full 8-phase build accumulates ~40,000–80,000 tokens of conversation. After `/clear` those are gone. Without this skill, that means starting over. With this skill, clearing the conversation costs nothing because **everything important lives on disk**, not in the conversation.

## Two Modes

- **SAVE** — Called after Phase 2, 4, 6. Saves complete state. Instructs user to /clear.
- **RESUME** — Called when `/onecommand --resume` is typed after a /clear. Restores full context.

---

## MODE: SAVE

Run after Phase 2, 4, or 6 completes.

### Step 1: Read all current state

```bash
python3 << 'EOF'
import json, os
from datetime import datetime

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm_path = os.path.join(brain_dir, "working_memory.json")

try:
    wm = json.load(open(wm_path))
except Exception as e:
    print(f"[auto-clear] ERROR: Cannot read working memory: {e}")
    exit(1)

print(f"[auto-clear:SAVE] Build: {wm.get('build_id', '?')}")
print(f"[auto-clear:SAVE] Project: {wm.get('project_name', '?')} ({wm.get('app_type', '?')})")
print(f"[auto-clear:SAVE] Phases done: {wm.get('phases_completed', [])}")
print(f"[auto-clear:SAVE] Next phase: {wm.get('current_phase', '?')}")
EOF
```

### Step 2: Scan all generated files in the project

```bash
python3 << 'EOF'
import os

generated = []
skip_dirs = {'.git', 'node_modules', '.next', '__pycache__', '.flutter',
             'build', '.dart_tool', 'ios/Pods', 'android/.gradle'}

for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
    for f in files:
        if not f.startswith('.'):
            path = os.path.join(root, f)[2:]  # strip ./
            generated.append(path)

print(f"[auto-clear:SAVE] Files on disk: {len(generated)}")
# Write file list to brain
brain_dir = os.path.expanduser("~/.onecommand/brain")
with open(os.path.join(brain_dir, "file_manifest.json"), "w") as fh:
    import json
    json.dump({"files": generated, "count": len(generated),
               "project_dir": os.getcwd()}, fh, indent=2)
print(f"[auto-clear:SAVE] File manifest saved ({len(generated)} files)")
EOF
```

### Step 3: Generate the resume brief — the complete handoff document

This document is what Claude reads after `/clear` to know EXACTLY where to continue.

```bash
python3 << 'EOF'
import json, os
from datetime import datetime

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))
spec = {}
try:
    spec = json.load(open(".onecommand-spec.json"))
except:
    pass

phases_done = wm.get("phases_completed", [])
next_phase = wm.get("current_phase", 1)
summaries = wm.get("phase_summaries", {})
decisions = wm.get("decisions_made", {})
errors_fixed = [e for e in wm.get("errors_log", []) if e.get("fixed")]

# Phase descriptions for remaining phases
remaining_descriptions = {
    3: "Integration (API verify, Docker, .env) + Marketing (README, landing page)",
    4: "Tests + Self-healing (up to 5 iterations)",
    5: "Automations (GitHub Actions CI, git hooks, Makefile)",
    6: "Quality pass (security audit, dark mode, a11y, store readiness)",
    7: "Self-improvement + Brain reflection",
    8: "Delivery report (ONECOMMAND-DELIVERY.md)",
}

# Build the brief
brief = f"""# OneCommand — Resume Brief
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Build ID:** {wm.get('build_id', 'unknown')}
**Status:** Phase {max(phases_done) if phases_done else 0} complete — **NEXT: Phase {next_phase}**

---

## Project
- **Name:** {wm.get('project_name', spec.get('project_name', '?'))}
- **Type:** {wm.get('app_type', spec.get('app_type', '?'))}
- **Location:** {os.getcwd()}

## Tech Stack (decided)
"""
for k, v in decisions.items():
    brief += f"- **{k}:** {v}\n"
if not decisions and spec.get("tech_stack"):
    for k, v in spec.get("tech_stack", {}).items():
        brief += f"- **{k}:** {v}\n"

brief += f"""
## Completed Phases
"""
for p in sorted(phases_done):
    s = summaries.get(str(p), summaries.get(p, "done"))
    brief += f"- ✅ **Phase {p}:** {s}\n"

brief += f"""
## Remaining Phases (continue from Phase {next_phase})
"""
for p in range(next_phase, 9):
    desc = remaining_descriptions.get(p, "")
    brief += f"- ⏳ **Phase {p}:** {desc}\n"

if errors_fixed:
    brief += f"""
## Errors Fixed (do not repeat these mistakes)
"""
    for e in errors_fixed[-5:]:
        brief += f"- {e.get('pattern', e.get('error', '?'))[:80]}: {e.get('fix', '')[:80]}\n"

brief += f"""
## File Count
- **{spec.get('project_name', 'Project')} files on disk:** see ~/.onecommand/brain/file_manifest.json

## Patterns Applied This Build
"""
for p in wm.get("patterns_applied", [])[:5]:
    brief += f"- {p}\n"
if not wm.get("patterns_applied"):
    brief += "- (none yet)\n"

brief += f"""
---
**To continue:** This brief is read automatically by `/onecommand --resume`
**Do NOT re-generate anything from Phases {phases_done} — those files are already on disk.**
"""

brief_path = os.path.join(brain_dir, "resume_brief.md")
with open(brief_path, "w") as f:
    f.write(brief)

print(f"[auto-clear:SAVE] Resume brief saved: {brief_path}")
print(f"[auto-clear:SAVE] Brief size: {len(brief)} chars")
EOF
```

### Step 4: Print the auto-clear instruction box

```bash
python3 << 'EOF'
import json, os

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))
next_phase = wm.get("current_phase", 1)
phases_done = len(wm.get("phases_completed", []))

print(f"""
+--------------------------------------------------------------+
|  🧹 AUTO-CLEAR — Phase {phases_done}/8 abgeschlossen                   |
+--------------------------------------------------------------+
|                                                              |
|  Alles gesichert. Kontext kann jetzt geleert werden.         |
|  Kein Datenverlust — alles liegt auf der Festplatte.         |
|                                                              |
|  Schritt 1: Tippe  /clear                                    |
|  Schritt 2: Tippe  /onecommand --resume                      |
|                                                              |
|  Phase {next_phase}/8 startet dann automatisch weiter.              |
+--------------------------------------------------------------+
""")
EOF
```

---

## MODE: RESUME

Called when `$ARGUMENTS` contains `--resume` or starts with `--resume`.

### Step 1: Check for active build

```bash
python3 << 'EOF'
import json, os, sys

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm_path = os.path.join(brain_dir, "working_memory.json")

if not os.path.exists(wm_path):
    print("[auto-clear:RESUME] No active build found.")
    print("Start a new build with: /onecommand \"describe your project\"")
    sys.exit(0)

wm = json.load(open(wm_path))
build_id = wm.get("build_id", "unknown")
project = wm.get("project_name", "unknown")
next_phase = wm.get("current_phase", 1)
phases_done = wm.get("phases_completed", [])

if not phases_done:
    print("[auto-clear:RESUME] No phases completed yet — start fresh with /onecommand")
    sys.exit(0)

print(f"[auto-clear:RESUME] Active build found: {project} (ID: {build_id})")
print(f"[auto-clear:RESUME] Phases done: {phases_done}")
print(f"[auto-clear:RESUME] Resuming from: Phase {next_phase}/8")
EOF
```

### Step 2: Load and display the resume brief

```bash
python3 << 'EOF'
import os

brain_dir = os.path.expanduser("~/.onecommand/brain")
brief_path = os.path.join(brain_dir, "resume_brief.md")

if os.path.exists(brief_path):
    brief = open(brief_path).read()
    print(brief)
else:
    # Fallback: reconstruct from working memory
    import json
    wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))
    print(f"[auto-clear:RESUME] Resuming {wm.get('project_name')} from Phase {wm.get('current_phase')}")
    print(f"[auto-clear:RESUME] Phases completed: {wm.get('phases_completed')}")
EOF
```

### Step 3: Verify project files are still on disk

```bash
python3 << 'EOF'
import json, os

brain_dir = os.path.expanduser("~/.onecommand/brain")
manifest_path = os.path.join(brain_dir, "file_manifest.json")

if os.path.exists(manifest_path):
    manifest = json.load(open(manifest_path))
    project_dir = manifest.get("project_dir", os.getcwd())
    expected = manifest.get("count", 0)

    # Count current files
    current = 0
    skip_dirs = {'.git', 'node_modules', '.next', '__pycache__'}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        current += len([f for f in files if not f.startswith('.')])

    pct = int((current / expected * 100)) if expected > 0 else 0
    status = "✓" if pct >= 90 else "⚠"
    print(f"[auto-clear:RESUME] {status} Files on disk: {current}/{expected} ({pct}%)")
    if pct < 90:
        print(f"[auto-clear:RESUME] ⚠ Some files seem missing — check {project_dir}")
else:
    print(f"[auto-clear:RESUME] File manifest not found — files assumed intact")
EOF
```

### Step 4: Set working directory to project location

```bash
python3 << 'EOF'
import json, os

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))

# The project dir is the current dir when the build started
# Print it so the user can cd if needed
project_dir = wm.get("project_dir", os.getcwd())
print(f"[auto-clear:RESUME] Project directory: {project_dir}")
if os.getcwd() != project_dir:
    print(f"[auto-clear:RESUME] Note: run 'cd {project_dir}' if not already there")
EOF
```

### Step 5: Announce resume and continue

Print exactly what is happening and jump to the correct phase:

```bash
python3 << 'EOF'
import json, os

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))
next_phase = wm.get("current_phase", 1)
project = wm.get("project_name", "?")

print(f"""
+--------------------------------------------------------------+
|  ▶  Resuming: {project:<46}|
|     Continuing from Phase {next_phase}/8                            |
|     All previous work preserved on disk.                     |
+--------------------------------------------------------------+
""")
EOF
```

After this output, **immediately continue building from the phase indicated** in the resume brief. Do NOT re-run any already-completed phase. Do NOT ask the user to repeat anything. Just pick up exactly where the build left off.

---

## Integration Rules

### When SAVE runs:
- After Phase 2 completes
- After Phase 4 completes
- After Phase 6 completes

### When RESUME runs:
- When `$ARGUMENTS` contains `--resume`
- When `$ARGUMENTS` is empty AND a `working_memory.json` with `phases_completed` exists

### What is NEVER re-generated:
- Any file already on disk from a completed phase
- The spec (already in `.onecommand-spec.json`)
- The DB schema (already migrated)
- Any test that already passed

### Token budget after resume:
After RESUME, the conversation context is empty (after /clear). The resume brief loads ~200 tokens. Each subsequent phase adds ~300 tokens (via context-manager BUDGET). A complete build from Phase 3 to 8 uses only ~1,800 tokens of context — compared to ~30,000 without auto-clear.
