---
name: collab-protocol
description: Claude + Codex collaboration protocol. Detects available agents, distributes tasks, creates task handoff files, and merges results. Falls back to Claude-only mode gracefully if Codex is unavailable.
model: claude-opus-4-7
---

## How collaboration works

### Detection
```bash
python3 << 'EOF'
import subprocess, json, os

def check_codex():
    try:
        r = subprocess.run(["codex", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except:
        return False

codex_available = check_codex()
mode = "dual" if codex_available else "claude_only"

print(f"Collaboration mode: {mode}")
print(f"Codex: {'✓' if codex_available else '○ unavailable — Claude handles all phases'}")
EOF
```

### Task distribution (dual mode)

When Codex is available, create a task handoff:
```bash
python3 << 'EOF'
import json, os
from datetime import datetime

handoff_dir = os.path.expanduser("~/.onecommand/handoff")
os.makedirs(handoff_dir, exist_ok=True)

spec = json.load(open(".onecommand-spec.json"))

# Write task for Codex
codex_task = {
    "assigned_to": "codex",
    "assigned_by": "claude",
    "timestamp": datetime.now().isoformat(),
    "tasks": ["backend", "tests", "automations"],
    "spec": spec,
    "working_memory_path": os.path.expanduser("~/.onecommand/brain/working_memory.json"),
    "output_dir": os.getcwd(),
    "status": "pending"
}
json.dump(codex_task, open(os.path.join(handoff_dir, "codex_task.json"), "w"), indent=2)

print("[collab] Task handed to Codex: backend + tests + automations")
print(f"[collab] Handoff file: {os.path.join(handoff_dir, 'codex_task.json')}")
EOF
```

Then run Codex task:
```bash
if command -v codex &>/dev/null; then
    codex --skill onecommand --task backend \
          --input ~/.onecommand/handoff/codex_task.json \
          2>/dev/null &
    CODEX_PID=$!
    echo "[collab] Codex backend generation started (PID: $CODEX_PID)"
    echo "[collab] Claude continuing with frontend in parallel..."
else
    echo "[collab] Codex not available — Claude handling backend"
fi
```

### Result merging
```bash
python3 << 'EOF'
import json, os, glob

handoff_dir = os.path.expanduser("~/.onecommand/handoff")
results = glob.glob(os.path.join(handoff_dir, "*_result.json"))

merged = {}
for result_file in results:
    agent_result = json.load(open(result_file))
    agent = agent_result.get("agent", "unknown")
    merged[agent] = {
        "status": agent_result.get("status"),
        "files_created": agent_result.get("files_created", []),
        "errors": agent_result.get("errors", [])
    }
    print(f"[collab] {agent} result: {agent_result.get('status')} — {len(agent_result.get('files_created', []))} files")

if not merged:
    print("[collab] No Codex results found — Claude handled all tasks")
EOF
```

### Fallback behavior (claude_only mode)
- All phases run in Claude Code
- Same quality as dual mode — Codex is an optimization, not a requirement
- Brain/memory system works identically
- No tasks are skipped or degraded

### Shared brain access
Both agents read/write to the same `~/.onecommand/brain/` directory. This is safe because:
- Each agent writes to its own section
- working_memory.json is locked during writes (file-based mutex)
- cross_learnings.json is append-only during a build

Show the file-based mutex implementation:
```python
import fcntl, json, os

def safe_write_json(path, data):
    """Thread/process-safe JSON write using file locking"""
    lock_path = path + ".lock"
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
```
