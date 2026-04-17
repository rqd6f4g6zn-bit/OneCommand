---
description: Resume an interrupted OneCommand build. Run /clear first, then /oc-resume — the build continues from exactly where it left off. No context needed, everything is saved on disk.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# OneCommand Resume

You are the OneCommand Resume handler. Your only job: restore full build context from disk and continue building from the correct phase — as if the `/clear` never happened.

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
    print(f"STATUS: error reading working memory: {e}")
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
    started = wm.get("started_at", "")
    if started:
        try:
            elapsed = int((datetime.now() - datetime.fromisoformat(started)).total_seconds() / 60)
            print(f"ELAPSED: {elapsed} min")
        except:
            pass
EOF
```

**If STATUS is `no_build` or `no_active_build`:**
> "Kein aktiver Build gefunden. Starte einen neuen Build mit: `/onecommand \"dein Projekt\"`"
Stop here.

**If STATUS is `resume phase=N`:** continue below.

## Step 2: Print the resume brief

```bash
python3 << 'EOF'
import os

brain_dir  = os.path.expanduser("~/.onecommand/brain")
brief_path = os.path.join(brain_dir, "resume_brief.md")

if os.path.exists(brief_path):
    print(open(brief_path).read())
else:
    # Fallback from working memory
    import json
    wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))
    print(f"Build: {wm.get('project_name')} | Next phase: {wm.get('current_phase')}")
    print(f"Completed: {wm.get('phases_completed')}")
    sums = wm.get("phase_summaries", {})
    for k, v in sorted(sums.items()):
        print(f"  Phase {k}: {v}")
EOF
```

## Step 3: Verify files are on disk

```bash
python3 << 'EOF'
import json, os

brain_dir    = os.path.expanduser("~/.onecommand/brain")
manifest_path = os.path.join(brain_dir, "file_manifest.json")

if not os.path.exists(manifest_path):
    print("File manifest not found — assuming files intact")
else:
    m = json.load(open(manifest_path))
    project_dir = m.get("project_dir", os.getcwd())
    expected    = m.get("count", 0)

    current = 0
    skip    = {'.git', 'node_modules', '.next', '__pycache__', 'build'}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith('.')]
        current += len([f for f in files if not f.startswith('.')])

    pct    = int(current / expected * 100) if expected else 0
    ok     = "✓" if pct >= 90 else "⚠"
    print(f"{ok} Files on disk: {current}/{expected} ({pct}%) — {project_dir}")
    if pct < 50:
        print("⚠  Many files missing — verify you are in the correct directory")
        print(f"   Expected directory: {project_dir}")
EOF
```

## Step 4: Change to project directory

```bash
python3 << 'EOF'
import json, os

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm        = json.load(open(os.path.join(brain_dir, "working_memory.json")))
pdir      = wm.get("project_dir", os.getcwd())
print(pdir)
EOF
```

If the printed directory differs from the current directory, run:
```bash
cd "$(python3 -c "import json,os; print(json.load(open(os.path.expanduser('~/.onecommand/brain/working_memory.json'))).get('project_dir', os.getcwd()))")"
```

## Step 5: Print resume banner and continue

```bash
python3 << 'EOF'
import json, os

brain_dir  = os.path.expanduser("~/.onecommand/brain")
wm         = json.load(open(os.path.join(brain_dir, "working_memory.json")))
name       = wm.get("project_name", "?")
next_phase = wm.get("current_phase", "?")
done_count = len(wm.get("phases_completed", []))

print(f"""
+--------------------------------------------------------------+
|  ▶  Resuming OneCommand Build                               |
|                                                              |
|  Project    : {name:<46}|
|  Next phase : {str(next_phase):<3}/8 — continuing now                     |
|  Done so far: {done_count:<1}/8 phases complete                         |
|                                                              |
|  All files preserved. No work will be repeated.             |
+--------------------------------------------------------------+
""")
EOF
```

## Step 6: Continue the build

Now pick up **exactly** from the phase number shown. Load the OneCommand skill/command context and execute the remaining phases in order.

The phases and what they do:
- **Phase 3**: Integration (API alignment, Docker, .env) + Marketing (README, landing)
- **Phase 4**: Tests + Self-healing (up to 5 iterations, brain learns from errors)
- **Phase 5**: Automations (GitHub Actions, git hooks, Makefile)
- **Phase 6**: Quality pass (security audit, dark mode, a11y, store readiness)
- **Phase 7**: Self-improvement + Brain reflection
- **Phase 8**: Delivery report (ONECOMMAND-DELIVERY.md)

**CRITICAL RULES:**
- Do NOT run any phase that is already in `phases_completed`
- Do NOT re-generate files that already exist on disk
- Do NOT ask the user to repeat anything — everything is in the resume brief
- Continue exactly as if the `/clear` never happened
