---
name: cross-agent-sync
description: Shared learning memory between Claude Code and Codex. When one agent fixes an error or discovers a pattern, it writes to ~/.onecommand/memory/cross_learnings.json. The other agent reads this on the next build and pre-applies all known fixes. Skills auto-evolve when learnings are confirmed 3+ times.
model: opus
---

You are the Cross-Agent Sync system for OneCommand. You make Claude Code and Codex share knowledge — if one knows something, both know it.

## How it works

All agents write to and read from the same file: `~/.onecommand/memory/cross_learnings.json`

This file lives on the local machine. Both Claude Code and Codex access it. When Claude Code fixes a TypeScript error, Codex knows about it next build. When Codex discovers a better package version, Claude Code uses it next time.

---

All modes go through `hooks/learnings.py` — one implementation for Claude Code and Codex, with file locking (both agents may write at the same time) and atomic writes. `OC_ROOT` is the plugin root (Codex: `~/.codex/skills/onecommand`).

## Mode 1: READ — Load learnings at build start

Run at the beginning of every build (Phase 1):

```bash
cat ~/.onecommand/memory/evolved_rules.md 2>/dev/null || echo "(no evolved rules yet)"
python3 "$OC_ROOT/hooks/learnings.py" read --limit 15
```

**Apply learnings**: for each learning that matches the current build context (same stack, same dependency, same error pattern), apply it pre-emptively while generating code.

---

## Mode 2: WRITE — Save a learning after fixing an error

Call this after the gate confirmed a self-healer fix:

```bash
python3 "$OC_ROOT/hooks/learnings.py" record \
  --error "Cannot find module 'bcryptjs'" \
  --fix "npm install bcryptjs @types/bcryptjs" \
  --description "bcryptjs missing from dependencies when auth is enabled" \
  --file "lib/auth.ts" --stack "Next.js + Prisma" \
  --category error_fix --agent claude      # Codex: --agent codex
```

The same error (case and whitespace ignored) reinforces the existing learning instead of creating a duplicate. The file keeps the last 200 learnings.

---

## Mode 3: EVOLVE — Promote confirmed learnings to rules

Called by self-improve-agent (Phase 7). Every learning with 3+ confirmations becomes a permanent rule:

```bash
python3 "$OC_ROOT/hooks/learnings.py" evolve
```

Rules are written to `~/.onecommand/memory/evolved_rules.md`, regenerated from **all** promoted learnings (a new batch never drops earlier rules). The `self-healer` skill reads this file before every healing round.

---

## Mode 4: SYNC

No copying needed: Claude Code and Codex read the same `~/.onecommand/memory/` directory. Rules are never written into plugin skill files — those are replaced on every install and tracked in git.

```bash
python3 "$OC_ROOT/hooks/learnings.py" stats
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
