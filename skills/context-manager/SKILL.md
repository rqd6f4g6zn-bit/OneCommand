---
name: context-manager
description: Automatically compresses the conversation context to save tokens without losing any project state. Saves all phase outputs to disk, enforces a 500-token budget per phase in the conversation, detects when /compact is safe, and can resume interrupted builds from checkpoints.
model: claude-opus-4-7
---

# Context Manager

This skill solves the core problem of long multi-phase builds: an 8-phase build generates tens of thousands of tokens of conversation history. Without compression, the context window fills up, slowing responses, increasing costs, and eventually failing.

The solution is architectural: **ALL state lives on disk. The conversation is just the current phase.**

## Fundamental Principle

| Layer | Role | Contents |
|---|---|---|
| **Disk** | Source of truth | `working_memory.json`, phase checkpoints, all generated files |
| **Conversation** | Current phase only | Max ~500 tokens of previous context |

After every phase, Claude compresses the phase output to a one-line summary, saves the full output to disk, and the conversation history stays small. After 8 phases, context is still clean — growing by ~100 tokens per phase instead of ~5000.

---

## Available Modes

| Mode | When to Run | Purpose |
|---|---|---|
| `BUDGET` | Start of each phase | Print compact phase header — suppress verbose history |
| `CHECKPOINT` | End of each phase | Save full phase state to disk |
| `COMPRESS` | Any time | Print one-line summaries of all completed phases |
| `SUGGEST_COMPACT` | Phase 2, 4, 6 boundaries | Tell user it's safe to run `/compact` |
| `RESUME` | Build interrupted | Restore working memory from last checkpoint |
| `STATUS` | On demand | Show context health dashboard |

---

## MODE: BUDGET

**When**: Called at the START of each phase to print a minimal context header instead of repeating verbose history.

**Why**: Enforces the 500-token budget. After printing this header, Claude must NOT repeat file contents or verbose outputs that are already on disk — reference files by path only.

```bash
python3 << 'EOF'
import json, os

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm_path = os.path.join(brain_dir, "working_memory.json")

try:
    wm = json.load(open(wm_path))
except:
    wm = {"project_name": "unknown", "current_phase": 1, "phases_completed": []}

completed = wm.get("phases_completed", [])
current = wm.get("current_phase", 1)
summaries = wm.get("phase_summaries", {})

# Print ultra-compact status line
print(f"\n[build:{wm.get('project_name','?')}] Phase {current}/8 | Completed: {completed}")
if summaries:
    for p in sorted(completed):
        s = summaries.get(str(p), summaries.get(p, "done"))
        print(f"  ✓ P{p}: {s}")
print()
EOF
```

**Token budget rule**: The BUDGET header gives Claude everything it needs to continue. Claude must not re-read or re-print files — cite their path and move on.

---

## MODE: CHECKPOINT

**When**: Called immediately after every phase completes, before moving to the next.

**Why**: Saves the complete project state — files on disk, working memory snapshot, timestamps — so the build can survive a `/compact`, a crash, or a context reset.

```bash
python3 << 'EOF'
import json, os, sys
from datetime import datetime

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm_path = os.path.join(brain_dir, "working_memory.json")

try:
    wm = json.load(open(wm_path))
except:
    print("[context-manager] No working memory found — skipping checkpoint")
    sys.exit(0)

build_id = wm.get("build_id", "unknown")
phase = wm.get("current_phase", 1) - 1  # just completed phase

cp_dir = os.path.join(brain_dir, "checkpoints", build_id)
os.makedirs(cp_dir, exist_ok=True)

# Count generated files in project
generated_files = []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '.next', '__pycache__', '.flutter']]
    for f in files:
        if not f.startswith('.'):
            generated_files.append(os.path.join(root, f)[2:])  # strip ./

checkpoint = {
    "phase": phase,
    "build_id": build_id,
    "timestamp": datetime.now().isoformat(),
    "project_dir": os.getcwd(),
    "files_generated": generated_files,
    "file_count": len(generated_files),
    "working_memory": wm
}

cp_path = os.path.join(cp_dir, f"phase_{phase}.json")
json.dump(checkpoint, open(cp_path, "w"), indent=2)

print(f"[context-manager:CHECKPOINT] ✓ Phase {phase} saved")
print(f"  Files on disk : {len(generated_files)}")
print(f"  Checkpoint    : {cp_path}")
print(f"  Safe to /compact now — all state is on disk")
EOF
```

**After this runs**: Claude prints a compact 1–5 line summary of what the phase produced, then stops. No verbose output, no file dumps.

---

## MODE: COMPRESS

**When**: Called any time to replace verbose phase history in the conversation with one-line summaries.

**Why**: If the conversation has grown bloated, this collapses all completed phase outputs into minimal references. The full details remain on disk.

```bash
python3 << 'EOF'
import json, os

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))

summaries = wm.get("phase_summaries", {})

print("\n[context-manager:COMPRESS] ===== Phase Summaries (compressed) =====")
for phase_num in sorted(summaries.keys()):
    summary = summaries[phase_num]
    print(f"  Phase {phase_num}: {summary}")
print("[context-manager:COMPRESS] ==========================================")
print("  Full details available in: ~/.onecommand/brain/checkpoints/")
print("  Current files on disk: use 'ls' or 'find .' to inspect\n")
EOF
```

**After this runs**: Claude treats the printed summaries as the full context for all prior phases. No re-reading of prior outputs.

---

## MODE: SUGGEST_COMPACT

**When**: Called at phase 2, 4, and 6 boundaries — key milestones where the conversation has grown meaningfully but the build still has multiple phases ahead.

**Why**: Proactively tells the user they can safely run `/compact` to free context tokens, with a clear explanation that nothing will be lost.

```bash
python3 << 'EOF'
import json, os

brain_dir = os.path.expanduser("~/.onecommand/brain")
try:
    wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))
    phase = wm.get("current_phase", 1)
    completed = len(wm.get("phases_completed", []))
except:
    phase = 1
    completed = 0

if completed >= 2:
    print(f"""
┌─────────────────────────────────────────────────────────────┐
│  💡 Context Compression Available                           │
│                                                             │
│  {completed} phases complete — all state is saved to disk.           │
│  You can safely run /compact to free up context tokens.     │
│                                                             │
│  Nothing will be lost — the brain remembers everything.     │
│  Next phase ({phase}/8) will resume from working memory.     │
└─────────────────────────────────────────────────────────────┘
""")
else:
    print(f"[context-manager] Phase {phase}/8 — no compression needed yet")
EOF
```

**User action**: The user can type `/compact` at this point. The next phase will begin with a BUDGET header that restores all necessary context from disk.

---

## MODE: RESUME

**When**: A build was interrupted — the user closed Claude, ran `/compact` manually, or the session timed out. Run this at the start of a new session to restore state.

**Why**: Finds the most recent checkpoint on disk, restores working memory to its last known good state, and tells Claude exactly which phase to continue from.

```bash
python3 << 'EOF'
import json, os, glob

brain_dir = os.path.expanduser("~/.onecommand/brain")
cp_base = os.path.join(brain_dir, "checkpoints")

# Find all builds, most recent first
all_cps = glob.glob(os.path.join(cp_base, "*/phase_*.json"))
if not all_cps:
    print("[context-manager:RESUME] No checkpoints found — nothing to resume")
    exit(0)

# Sort by modification time
all_cps.sort(key=os.path.getmtime, reverse=True)
latest = all_cps[0]

cp = json.load(open(latest))
wm = cp.get("working_memory", {})

print(f"\n[context-manager:RESUME] ===== Resumable build found =====")
print(f"  Build ID       : {cp.get('build_id')}")
print(f"  Last checkpoint: Phase {cp.get('phase')}")
print(f"  Saved at       : {cp.get('timestamp')}")
print(f"  Project dir    : {cp.get('project_dir')}")
print(f"  Files on disk  : {cp.get('file_count', 0)}")
print(f"  Phases done    : {wm.get('phases_completed', [])}")
print(f"  Next phase     : {wm.get('current_phase', 1)}")

# Check if project dir still has files
project_dir = cp.get("project_dir", "")
if os.path.exists(project_dir):
    current_files = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in ['.git','node_modules','.next']]
        for f in files:
            if not f.startswith('.'):
                current_files.append(f)
    print(f"  Files still there: {len(current_files)} ✓" if current_files else "  ⚠ Project dir appears empty")

print(f"\nTo resume: the build will continue from Phase {wm.get('current_phase', 1)}")
print(f"Working memory is being restored...")

# Restore working memory
wm_path = os.path.join(brain_dir, "working_memory.json")
json.dump(wm, open(wm_path, "w"), indent=2)
print(f"[context-manager:RESUME] ✓ Working memory restored")
print(f"[context-manager:RESUME] ================================\n")
EOF
```

**After this runs**: Claude runs BUDGET mode to print the compact phase header, then continues the build from the restored phase — no re-generating completed work.

---

## MODE: STATUS

**When**: Called on demand when the user or Claude wants a health check on context usage.

**Why**: Gives a clear dashboard of how many checkpoints are saved, how much brain data is on disk, and reassures that `/compact` is always safe.

```bash
python3 << 'EOF'
import json, os, glob

brain_dir = os.path.expanduser("~/.onecommand/brain")

# Count checkpoints
build_cps = glob.glob(os.path.join(brain_dir, "checkpoints", "*/phase_*.json"))

# Load working memory
try:
    wm = json.load(open(os.path.join(brain_dir, "working_memory.json")))
    phases_done = len(wm.get("phases_completed", []))
    project = wm.get("project_name", "unknown")
except:
    phases_done = 0
    project = "no active build"

# Count brain files size
brain_size = sum(
    os.path.getsize(os.path.join(brain_dir, f))
    for f in os.listdir(brain_dir)
    if os.path.isfile(os.path.join(brain_dir, f))
)

print(f"""
[context-manager:STATUS]
  Active build     : {project}
  Phases complete  : {phases_done}/8
  Checkpoints saved: {len(build_cps)}
  Brain size       : {brain_size/1024:.1f} KB on disk
  Working memory   : ~/.onecommand/brain/working_memory.json
  Tip              : All state is on disk — /compact is always safe during a build
""")
EOF
```

---

## Integration Rule

**Every phase in `onecommand.md` must follow this exact pattern:**

```
1. BUDGET mode     → print compact phase header (not verbose history)
2. Run phase work  → generate files, update working_memory.json
3. CHECKPOINT mode → save full state to disk
4. Print 1–5 line summary ONLY — not full file contents
5. SUGGEST_COMPACT → at the end of phases 2, 4, and 6
```

This keeps conversation growth at ~100 tokens per phase instead of ~5000. After 8 phases, the context window is still clean and responsive.

### Why this works

- **Files are on disk** — Claude never needs to reprint them. A path reference costs 5 tokens; printing a 200-line file costs 2,000.
- **Working memory is on disk** — `/compact` cannot erase it. The next phase always starts from the checkpoint, not from conversation history.
- **Summaries replace outputs** — `"Phase 3: Generated auth module (6 files)"` conveys everything Claude needs to continue. The actual files are at the path.
- **RESUME handles the worst case** — even if Claude crashes mid-phase, the last checkpoint is intact. The build picks up from there.

### Disk layout

```
~/.onecommand/brain/
  working_memory.json              ← live build state
  checkpoints/
    {build_id}/
      phase_1.json                 ← full snapshot after phase 1
      phase_2.json                 ← full snapshot after phase 2
      ...
```

### Token budget accounting

| Event | Tokens added to conversation |
|---|---|
| BUDGET header | ~30 tokens |
| Phase work (files, reasoning) | ~200–400 tokens |
| CHECKPOINT output | ~10 tokens |
| Phase summary | ~20 tokens |
| SUGGEST_COMPACT box | ~40 tokens |
| **Total per phase** | **~300–500 tokens** |
| **8 phases total** | **~2,400–4,000 tokens** |

Without this skill, 8 phases accumulate 40,000–80,000 tokens of conversation history. With it, the entire build fits comfortably in a single context window.
