---
description: Resume an interrupted OneCommand build. After /clear, type /oc-resume — the build continues from exactly where it left off. No context needed, everything is on disk.
argument-hint: (no arguments needed)
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

You are the OneCommand Resume handler. Restore full build context from disk and continue building from the correct phase — as if `/clear` never happened.

## Step 1: Check for active build

```bash
python3 << 'EOF'
import json, os, sys
from datetime import datetime

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm_path   = os.path.join(brain_dir, "working_memory.json")

if not os.path.exists(wm_path):
    print("STATUS: no_build")
    sys.exit(0)

try:
    wm = json.load(open(wm_path))
except Exception as e:
    print(f"STATUS: error — {e}")
    sys.exit(1)

phases_done = wm.get("phases_completed", [])
next_phase  = wm.get("current_phase", 1)

if not phases_done or next_phase <= 1:
    print("STATUS: no_active_build")
else:
    print(f"STATUS: resume phase={next_phase}")
    print(f"PROJECT: {wm.get('project_name', '?')} ({wm.get('app_type', '?')})")
    print(f"PHASES_DONE: {phases_done}")
    print(f"BUILD_ID: {wm.get('build_id', '?')}")
    pdir = wm.get("project_dir", "")
    if pdir:
        print(f"PROJECT_DIR: {pdir}")
    try:
        started = wm.get("started_at", "")
        elapsed = int((datetime.now() - datetime.fromisoformat(started)).total_seconds() / 60)
        print(f"ELAPSED: {elapsed} min")
    except:
        pass
EOF
```

**If STATUS is `no_build` or `no_active_build`:**
> "Kein aktiver Build gefunden. Starte einen neuen Build mit: `/onecommand \"dein Projekt\"`"

Stop here.

**If STATUS is `resume phase=N`:** continue with Step 2.

## Step 2: Change to project directory

```bash
PROJECT_DIR=$(python3 -c "
import json, os
wm = json.load(open(os.path.expanduser('~/.onecommand/brain/working_memory.json')))
print(wm.get('project_dir', os.getcwd()))
")
echo "Project dir: $PROJECT_DIR"
cd "$PROJECT_DIR" && echo "✓ Changed to project directory: $(pwd)"
```

## Step 3: Print the resume brief

```bash
python3 << 'EOF'
import os, json

brain_dir  = os.path.expanduser("~/.onecommand/brain")
brief_path = os.path.join(brain_dir, "resume_brief.md")

if os.path.exists(brief_path):
    print(open(brief_path).read())
else:
    # Fallback: reconstruct from working memory
    wm   = json.load(open(os.path.join(brain_dir, "working_memory.json")))
    sums = wm.get("phase_summaries", {})
    print(f"Project  : {wm.get('project_name')} ({wm.get('app_type')})")
    print(f"Next     : Phase {wm.get('current_phase')}/8")
    print(f"Done     : {wm.get('phases_completed')}")
    for k in sorted(sums):
        print(f"  Phase {k}: {sums[k]}")
    dec = wm.get("decisions_made", {})
    if dec:
        print("\nStack decisions:")
        for k, v in dec.items():
            print(f"  {k}: {v}")
EOF
```

## Step 4: Verify files on disk

```bash
python3 << 'EOF'
import json, os

brain_dir     = os.path.expanduser("~/.onecommand/brain")
manifest_path = os.path.join(brain_dir, "file_manifest.json")

if not os.path.exists(manifest_path):
    print("○ No file manifest — assuming files intact")
else:
    m           = json.load(open(manifest_path))
    project_dir = m.get("project_dir", os.getcwd())
    expected    = m.get("count", 0)
    skip        = {'.git', 'node_modules', '.next', '__pycache__', 'build', '.dart_tool'}
    current     = 0
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith('.')]
        current += len([f for f in files if not f.startswith('.')])

    pct  = int(current / expected * 100) if expected else 0
    icon = "✓" if pct >= 90 else "⚠"
    print(f"{icon} Files on disk: {current}/{expected} ({pct}%)")
    if pct < 50:
        print(f"⚠  Many files missing. Expected location: {project_dir}")
        print(f"   Run: cd {project_dir}")
EOF
```

## Step 5: Resume banner

```bash
python3 << 'EOF'
import json, os

brain_dir  = os.path.expanduser("~/.onecommand/brain")
wm         = json.load(open(os.path.join(brain_dir, "working_memory.json")))
name       = wm.get("project_name", "?")
next_phase = wm.get("current_phase", "?")
done       = len(wm.get("phases_completed", []))

# pad name to fit box
name_str = name[:44]

print(f"""
+--------------------------------------------------------------+
|  ▶  Resuming OneCommand Build                               |
+--------------------------------------------------------------+
|                                                              |
|  Project    : {name_str:<46}|
|  Next phase : {str(next_phase):<3}/8  — continuing now                    |
|  Done so far: {done:<1}/8 phases complete                         |
|                                                              |
|  All files on disk. No work will be repeated.               |
+--------------------------------------------------------------+
""")
EOF
```

## Step 6: Continue the build

Pick up **exactly** from the phase shown. Execute the remaining phases in order.

| Phase | What it does |
|---|---|
| 3 | Integration (API verify, Docker, .env.example) + Marketing (README, landing page) |
| 4 | Tests + Self-healing (up to 5 auto-iterations, brain logs every fix) |
| 5 | Automations (GitHub Actions CI, git hooks, Makefile) |
| 6 | Quality pass (security audit OWASP, dark mode, a11y, store readiness) |
| 7 | Self-improvement + Brain reflection (episodic memory, preference update) |
| 8 | Delivery report → ONECOMMAND-DELIVERY.md |

**Rules:**
- Skip every phase already in `phases_completed`
- Skip files that already exist on disk — do not overwrite
- Do not ask the user for input — everything is in the resume brief
- After Phase 4 and Phase 6 complete → invoke auto-clear SAVE again
