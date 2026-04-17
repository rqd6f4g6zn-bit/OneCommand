---
name: brain-agent
description: OneCommand's intelligence orchestrator. Runs at build start (READ memories, detect similar projects), after each phase (CHECKPOINT + pattern update), and at build end (REFLECT, update episodic memory, evolve skill patterns). Also handles Claude+Codex collaboration detection and task distribution.
model: claude-opus-4-7
tools: Read, Write, Edit, Bash, Glob, Grep
skills:
  - brain-core
  - context-manager
  - cross-agent-sync
---

## Step 1: Detect available agents
```bash
python3 << 'EOF'
import subprocess, json, os

agents = {}

# Check Claude Code (we're running inside it — always available)
agents["claude"] = True

# Check Codex
try:
    r = subprocess.run(["codex", "--version"], capture_output=True, timeout=5)
    agents["codex"] = r.returncode == 0
except:
    agents["codex"] = False

# Save to working config
config_dir = os.path.expanduser("~/.onecommand")
os.makedirs(config_dir, exist_ok=True)
collab = {
    "claude_available": agents["claude"],
    "codex_available": agents["codex"],
    "mode": "dual" if agents["codex"] else "claude_only"
}
json.dump(collab, open(os.path.join(config_dir, "collaboration.json"), "w"), indent=2)

print(f"[brain-agent] Agent detection:")
print(f"  Claude Code : ✓ (active)")
print(f"  Codex       : {'✓ available' if agents['codex'] else '○ not found (Claude handles everything)'}")
print(f"  Mode        : {collab['mode']}")
EOF
```

## Step 2: Load brain memories (READ mode)
Invoke `brain-core` skill in READ mode.
Invoke `context-manager` skill in BUDGET mode.

## Step 3: Find similar past project (RECALL mode)
Invoke `brain-core` skill in RECALL mode.
If similar project found, load its lessons and pre-apply patterns.

## Step 4: Set collaboration plan based on available agents

```bash
python3 << 'EOF'
import json, os

collab_path = os.path.expanduser("~/.onecommand/collaboration.json")
collab = json.load(open(collab_path))

wm_path = os.path.expanduser("~/.onecommand/brain/working_memory.json")
try:
    wm = json.load(open(wm_path))
except:
    wm = {}

if collab["mode"] == "dual":
    plan = {
        "claude": ["spec", "frontend", "integration", "marketing", "self-improve", "delivery"],
        "codex": ["backend", "tests", "automations"],
        "shared": ["brain", "memory"]
    }
    print("[brain-agent] Dual-agent mode:")
    print(f"  Claude handles : {plan['claude']}")
    print(f"  Codex handles  : {plan['codex']}")
else:
    plan = {
        "claude": ["spec", "frontend", "backend", "integration", "marketing",
                   "tests", "automations", "self-improve", "delivery"],
        "codex": [],
        "shared": ["brain", "memory"]
    }
    print("[brain-agent] Claude-only mode (full functionality — Codex not required)")

wm["collaboration_plan"] = plan
json.dump(wm, open(wm_path, "w"), indent=2)
EOF
```

## Step 5: Phase checkpoint writer (called after each phase)

After each phase completes, the brain-agent runs this:
```bash
python3 << 'EOF'
import json, os, sys
from datetime import datetime

brain_dir = os.path.expanduser("~/.onecommand/brain")
wm_path = os.path.join(brain_dir, "working_memory.json")
wm = json.load(open(wm_path))

# The phase summary should be passed as a compact string
# It's extracted from the phase output by Claude
# Format: "Phase N: [one-line summary of what was built]"
phase_done = wm.get("current_phase", 1) - 1
print(f"[brain-agent] Checkpointing phase {phase_done}...")
EOF
```

Then invoke `context-manager` in CHECKPOINT mode.
Then invoke `context-manager` in SUGGEST_COMPACT mode (at phases 2, 4, 6).

## Step 6: Post-build reflection (run after Phase 8)

1. Invoke `brain-core` in REFLECT mode
2. Invoke `brain-core` in PREFER mode (update user preferences from decisions made)
3. Invoke `cross-agent-sync` in EVOLVE mode (auto-patch skills with 3+ confirmations)
4. Print brain growth report:

```bash
python3 << 'EOF'
import json, os

brain_dir = os.path.expanduser("~/.onecommand/brain")

episodes = json.load(open(os.path.join(brain_dir, "episodic_memory.json")))
patterns = json.load(open(os.path.join(brain_dir, "pattern_library.json")))
knowledge = json.load(open(os.path.join(brain_dir, "semantic_memory.json")))
prefs = json.load(open(os.path.join(brain_dir, "user_preferences.json")))

total_builds = len(episodes.get("builds", []))
avg_quality = 0
if total_builds > 0:
    scores = [b.get("quality_score", 0) for b in episodes["builds"]]
    avg_quality = sum(scores) / len(scores)

print(f"""
[brain-agent] ===== Brain Growth Report =====
  Total builds in memory : {total_builds}
  Average quality score  : {avg_quality:.0f}/100
  Patterns learned       : {len(patterns.get('patterns', []))}
  Facts in knowledge base: {len(knowledge.get('knowledge', []))}
  User preferences known : {len([v for v in prefs.get('preferences', {}).values() if v is not None])}
  Brain is growing ↑
[brain-agent] =================================
""")
EOF
```
