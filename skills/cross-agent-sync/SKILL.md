---
name: cross-agent-sync
description: Shared learning memory between Claude Code and Codex. When one agent fixes an error or discovers a pattern, it writes to ~/.onecommand/memory/cross_learnings.json. The other agent reads this on the next build and pre-applies all known fixes. Skills auto-evolve when learnings are confirmed 3+ times.
model: claude-opus-4-7
---

You are the Cross-Agent Sync system for OneCommand. You make Claude Code and Codex share knowledge — if one knows something, both know it.

## How it works

All agents write to and read from the same file: `~/.onecommand/memory/cross_learnings.json`

This file lives on the local machine. Both Claude Code and Codex access it. When Claude Code fixes a TypeScript error, Codex knows about it next build. When Codex discovers a better package version, Claude Code uses it next time.

---

## Mode 1: READ — Load learnings at build start

Run at the beginning of every build (Phase 1):

```bash
python3 << 'EOF'
import json, os, datetime

memory_path = os.path.expanduser("~/.onecommand/memory/cross_learnings.json")

if not os.path.exists(memory_path):
    print("Cross-agent memory: empty (first build)")
else:
    try:
        data = json.load(open(memory_path))
        learnings = data.get("learnings", [])
        if not learnings:
            print("Cross-agent memory: no learnings yet")
        else:
            print(f"Cross-agent memory: {len(learnings)} learnings loaded")
            print("\nKnown patterns from previous builds:")
            for l in learnings[-10:]:  # show last 10
                src = l.get("source_agent", "?")
                cat = l.get("category", "?")
                conf = l.get("confirmations", 1)
                desc = l.get("description", l.get("error_pattern", "?"))[:80]
                print(f"  [{src}][{cat}][x{conf}] {desc}")
    except Exception as e:
        print(f"Cross-agent memory read error: {e}")
EOF
```

**Apply learnings**: For each learning in cross_learnings.json, pre-emptively apply it if it matches the current build context (same stack, same error pattern, same dependency).

---

## Mode 2: WRITE — Save a learning after fixing an error

Call this after self-healer fixes an error:

```bash
python3 << 'PYEOF'
import json, os, datetime, uuid

memory_path = os.path.expanduser("~/.onecommand/memory/cross_learnings.json")
os.makedirs(os.path.dirname(memory_path), exist_ok=True)

# Fill these from the actual error and fix:
learning = {
    "id": str(uuid.uuid4())[:8],
    "source_agent": "AGENT_NAME",        # "claude" or "codex"
    "category": "CATEGORY",              # "error_fix" | "pattern" | "stack_preference" | "dependency"
    "error_pattern": "ERROR_PATTERN",    # e.g. "Cannot find module 'bcryptjs'"
    "fix": "FIX_APPLIED",                # e.g. "npm install bcryptjs --save"
    "stack": "STACK",                    # e.g. "Next.js + Prisma"
    "file_context": "FILE",             # e.g. "lib/auth.ts"
    "description": "DESCRIPTION",        # human-readable summary
    "confidence": 1,
    "confirmations": 1,
    "confirmed_by": ["AGENT_NAME"],
    "date": datetime.date.today().isoformat(),
    "applied_to_skill": False,
}

try:
    data = json.load(open(memory_path))
except:
    data = {"version": "1.0", "learnings": []}

# Check if this error_pattern already exists — if so, increment confirmations
existing = next((l for l in data["learnings"] if l.get("error_pattern") == learning["error_pattern"]), None)
if existing:
    existing["confirmations"] = existing.get("confirmations", 1) + 1
    if learning["source_agent"] not in existing.get("confirmed_by", []):
        existing.setdefault("confirmed_by", []).append(learning["source_agent"])
    print(f"Learning reinforced: '{learning['error_pattern']}' now confirmed {existing['confirmations']} times")
else:
    data["learnings"].append(learning)
    print(f"New learning saved: '{learning['description']}'")

# Keep last 100 learnings
data["learnings"] = data["learnings"][-100:]

json.dump(data, open(memory_path, "w"), indent=2)
PYEOF
```

---

## Mode 3: EVOLVE — Auto-patch skill files when confidence is high

Called by self-improve-agent. When a learning has 3+ confirmations, it gets written into the relevant skill file as a permanent rule.

```bash
python3 << 'EOF'
import json, os, datetime

memory_path = os.path.expanduser("~/.onecommand/memory/cross_learnings.json")
plugin_root = os.path.expanduser("~/.onecommand/plugin_root")

# Try to detect plugin root
for candidate in [
    os.path.expanduser("~/OneComand"),
    os.path.expanduser("~/onecommand"),
    "/Users/g.urban/OneComand",
]:
    if os.path.isdir(os.path.join(candidate, "skills")):
        plugin_root = candidate
        break

if not os.path.exists(memory_path):
    print("No memory file yet — nothing to evolve")
    exit()

try:
    data = json.load(open(memory_path))
except:
    print("Memory read error")
    exit()

learnings = data.get("learnings", [])
ready_to_evolve = [l for l in learnings if l.get("confirmations", 0) >= 3 and not l.get("applied_to_skill")]

if not ready_to_evolve:
    print(f"Skill evolution: {len(learnings)} learnings tracked, none ready (need 3+ confirmations)")
else:
    print(f"Skill evolution: {len(ready_to_evolve)} learnings ready to apply to skills")
    
    # Append learnings to self-healer skill as known fixes
    healer_path = os.path.join(plugin_root, "skills", "self-healer", "self-healer.md")
    if os.path.exists(healer_path):
        with open(healer_path, "r") as f:
            healer = f.read()
        
        new_rules = "\n\n## Auto-Evolved Rules (Cross-Agent Learnings)\n\n"
        new_rules += f"*Last updated: {datetime.date.today().isoformat()} — {len(ready_to_evolve)} confirmed patterns*\n\n"
        for l in ready_to_evolve:
            new_rules += f"### [{l.get('category','fix')}] {l.get('description', l.get('error_pattern','?'))}\n"
            new_rules += f"- **Error pattern**: `{l.get('error_pattern','')}`\n"
            new_rules += f"- **Fix**: `{l.get('fix','')}`\n"
            new_rules += f"- **Stack**: {l.get('stack','any')}\n"
            new_rules += f"- **Confirmed by**: {', '.join(l.get('confirmed_by',[]))}\n\n"
        
        # Replace or append the auto-evolved section
        marker = "## Auto-Evolved Rules"
        if marker in healer:
            healer = healer[:healer.index(marker)] + new_rules.lstrip("\n")
        else:
            healer += new_rules
        
        with open(healer_path, "w") as f:
            f.write(healer)
        print(f"Self-healer skill updated with {len(ready_to_evolve)} evolved rules")
    
    # Mark learnings as applied
    for l in ready_to_evolve:
        l["applied_to_skill"] = True
        l["applied_date"] = datetime.date.today().isoformat()
    
    json.dump(data, open(memory_path, "w"), indent=2)
    print("Memory updated — learnings marked as applied to skills")

# Summary stats
total = len(learnings)
applied = len([l for l in learnings if l.get("applied_to_skill")])
pending = len([l for l in learnings if not l.get("applied_to_skill")])
print(f"\nMemory stats: {total} total | {applied} in skills | {pending} pending ({3 - min(3, max(l.get('confirmations',0) for l in learnings) if learnings else 0)} more confirmations needed for next evolution)")
EOF
```

---

## Mode 4: SYNC — Push learnings to both Claude Code and Codex skill files

Called after skill evolution to ensure both systems have the latest:

```bash
python3 << 'EOF'
import os, shutil

# Sync cross_learnings to both systems
src = os.path.expanduser("~/.onecommand/memory/cross_learnings.json")

# Claude Code reads from the same memory path — no extra sync needed
# Codex skill reads the same ~/.onecommand/memory/ path — no extra sync needed

# What we DO sync: if a skill file was evolved, copy it to the Codex skill directory
codex_skill_dir = os.path.expanduser("~/.codex/skills/onecommand/")

for candidate in ["/Users/g.urban/OneComand", os.path.expanduser("~/OneComand")]:
    healer = os.path.join(candidate, "skills", "self-healer", "self-healer.md")
    if os.path.exists(healer):
        dest = os.path.join(codex_skill_dir, "self-healer.md")
        os.makedirs(codex_skill_dir, exist_ok=True)
        shutil.copy2(healer, dest)
        print(f"Synced self-healer to Codex: {dest}")
        break

print("Cross-agent sync complete — both Claude Code and Codex share updated knowledge")
EOF
```

---

## Memory file location

`~/.onecommand/memory/cross_learnings.json`

This is the single source of truth. Both Claude Code and Codex read and write here. No internet required. Works offline. Always available.

## Schema

```json
{
  "version": "1.0",
  "learnings": [
    {
      "id": "a1b2c3d4",
      "source_agent": "claude",
      "category": "error_fix",
      "error_pattern": "Cannot find module 'bcryptjs'",
      "fix": "npm install bcryptjs @types/bcryptjs --save",
      "stack": "Next.js + Prisma",
      "file_context": "lib/auth.ts",
      "description": "bcryptjs missing from dependencies when auth is enabled",
      "confidence": 1,
      "confirmations": 3,
      "confirmed_by": ["claude", "codex", "claude"],
      "date": "2026-04-15",
      "applied_to_skill": true,
      "applied_date": "2026-04-16"
    }
  ]
}
```
