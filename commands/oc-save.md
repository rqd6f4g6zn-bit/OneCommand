---
description: Save the current OneCommand build state to disk so you can safely run /clear. Run /oc-resume afterwards to continue. Works at any point during a build — not just at phase boundaries.
argument-hint: (no arguments needed)
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

You are the OneCommand manual save handler. Save everything to disk right now so the user can safely run `/clear`.

## Step 1: Check if there is a build to save

```bash
python3 << 'EOF'
import json, os, sys

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm_path   = os.path.join(brain_dir, "working_memory.json")

if not os.path.exists(wm_path):
    print("STATUS: no_build")
    sys.exit(0)

try:
    wm = json.load(open(wm_path))
    print(f"STATUS: ok")
    print(f"PROJECT: {wm.get('project_name', '?')}")
    print(f"PHASE: {wm.get('current_phase', 1)}")
    print(f"DONE: {wm.get('phases_completed', [])}")
except Exception as e:
    print(f"STATUS: error — {e}")
    sys.exit(1)
EOF
```

**If STATUS is `no_build`:**
> "Kein aktiver Build gefunden."
Stop here.

## Step 2: Scan all project files

```bash
python3 << 'EOF'
import json, os
from datetime import datetime

brain_dir = os.path.expanduser("~/.onecommand/brain")
os.makedirs(brain_dir, exist_ok=True)

wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))
project_dir = wm.get("project_dir", os.getcwd())

skip = {'.git', 'node_modules', '.next', '__pycache__', 'build', '.dart_tool', 'ios/Pods'}
generated = []
for root, dirs, files in os.walk(project_dir):
    dirs[:] = [d for d in dirs if d not in skip and not d.startswith('.')]
    for f in files:
        if not f.startswith('.'):
            generated.append(os.path.join(root, f))

manifest = {
    "files": generated,
    "count": len(generated),
    "project_dir": project_dir,
    "saved_at": datetime.now().isoformat()
}
with open(os.path.join(brain_dir, "file_manifest.json"), "w") as fh:
    json.dump(manifest, fh, indent=2)

print(f"✓ Scanned {len(generated)} files in {project_dir}")
EOF
```

## Step 3: Generate resume brief

```bash
python3 << 'EOF'
import json, os
from datetime import datetime

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm        = json.load(open(os.path.join(brain_dir, "working_memory.json")))
spec      = {}
try:
    pdir = wm.get("project_dir", ".")
    spec = json.load(open(os.path.join(pdir, ".onecommand-spec.json")))
except:
    pass

phases_done = wm.get("phases_completed", [])
next_phase  = wm.get("current_phase", 1)
summaries   = wm.get("phase_summaries", {})
decisions   = wm.get("decisions_made", {})

remaining = {
    2: "Frontend + Backend + Mobile generation (parallel)",
    3: "Integration (API verify, Docker, .env) + Marketing",
    4: "Tests + Self-healing",
    5: "Automations (GitHub Actions, git hooks, Makefile)",
    6: "Quality pass (security, dark mode, a11y, store readiness)",
    7: "Self-improvement + Brain reflection",
    8: "Delivery report",
}

brief = f"""# OneCommand — Manual Save
**Saved:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Build ID:** {wm.get('build_id', 'unknown')}
**Status:** Phase {max(phases_done) if phases_done else 0} complete — **NEXT: Phase {next_phase}**

## Project
- **Name:** {wm.get('project_name', spec.get('project_name', '?'))}
- **Type:** {wm.get('app_type', spec.get('app_type', '?'))}
- **Location:** {wm.get('project_dir', os.getcwd())}

## Tech Stack
"""
for k, v in decisions.items():
    brief += f"- **{k}:** {v}\n"
if not decisions:
    for k, v in spec.get("tech_stack", {}).items():
        brief += f"- **{k}:** {v}\n"

brief += "\n## Completed Phases\n"
for p in sorted(phases_done):
    s = summaries.get(str(p), summaries.get(p, "done"))
    brief += f"- ✅ **Phase {p}:** {s}\n"
if not phases_done:
    brief += "- (none yet)\n"

brief += f"\n## Remaining (from Phase {next_phase})\n"
for p in range(next_phase, 9):
    brief += f"- ⏳ **Phase {p}:** {remaining.get(p, '')}\n"

brief += f"\n**Do NOT re-generate Phases {phases_done} — files are on disk.**\n"

brief_path = os.path.join(brain_dir, "resume_brief.md")
with open(brief_path, "w") as f:
    f.write(brief)

print(f"✓ Resume brief saved ({len(brief)} chars)")
print(f"  → {brief_path}")
EOF
```

## Step 4: Create checkpoint

```bash
python3 << 'EOF'
import json, os
from datetime import datetime

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm        = json.load(open(os.path.join(brain_dir, "working_memory.json")))
build_id  = wm.get("build_id", "manual")
phase     = wm.get("current_phase", 1) - 1

cp_dir = os.path.join(brain_dir, "checkpoints", build_id)
os.makedirs(cp_dir, exist_ok=True)

checkpoint = {
    "phase": phase,
    "build_id": build_id,
    "timestamp": datetime.now().isoformat(),
    "saved_manually": True,
    "working_memory": wm
}

cp_path = os.path.join(cp_dir, f"manual_save_{datetime.now().strftime('%H%M%S')}.json")
with open(cp_path, "w") as f:
    json.dump(checkpoint, f, indent=2)

print(f"✓ Checkpoint saved → {cp_path}")
EOF
```

## Step 5: Print confirmation

```bash
python3 << 'EOF'
import json, os

brain_dir  = os.path.expanduser("~/.onecommand/brain")
wm         = json.load(open(os.path.join(brain_dir, "working_memory.json")))
manifest   = json.load(open(os.path.join(brain_dir, "file_manifest.json")))
next_phase = wm.get("current_phase", "?")
name       = wm.get("project_name", "?")
files      = manifest.get("count", 0)

print(f"""
+--------------------------------------------------------------+
|  💾 OneCommand — Build State Saved                          |
+--------------------------------------------------------------+
|                                                              |
|  Project   : {name:<47}|
|  Files     : {files:<3} Dateien gesichert                        |
|  Nächste   : Phase {str(next_phase):<3}/8                                 |
|                                                              |
|  Schritt 1 : Tippe  /clear                                  |
|  Schritt 2 : Tippe  /oc-resume                              |
|                                                              |
|  Kein Datenverlust — alles liegt auf der Festplatte.        |
+--------------------------------------------------------------+
""")
EOF
```
