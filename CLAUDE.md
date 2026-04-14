# OneCommand Plugin

OneCommand is a Claude Code plugin that builds complete, production-ready software systems from a single natural language prompt.

## Plugin Structure

```
.claude-plugin/plugin.json   # Plugin manifest
commands/                    # Slash commands (/onecommand, /onecommand-status)
skills/                      # Reusable skills invoked by agents and commands
agents/                      # Specialized agents for each build phase
hooks/                       # Shell scripts (post-generate.sh)
docs/superpowers/            # Design specs and implementation plans
```

## Commands

- `/onecommand "<prompt>"` — Build a complete software system from a description
- `/onecommand-status` — Show current build phase progress

## Workflow Overview

```
Phase 1: Spec          → spec-analyzer + stack-detector skills
Phase 2: Parallel      → frontend-agent (Claude) + backend-agent (Codex)
Phase 3: Integration   → direct orchestration + marketing-agent
Phase 4: Tests         → test-agent + self-healer skill (up to 5 iterations)
Phase 5: Automations   → automation-installer skill
Phase 6: Exceed        → exceed-expectations skill + security-agent
Phase 7: Self-Improve  → self-improve-agent (writes to ~/.onecommand/memory/)
Phase 8: Delivery      → delivery-reporter skill
```

## Dependencies (required plugins)

These plugins must be installed for full functionality:
- `codex` — for backend code generation via Codex CLI (`/codex:setup`)
- `superpowers` — for `frontend-design`, `ui-ux-pro-max` skills
- `marketing-skills` — for landing page and documentation generation

## Memory

OneCommand stores learned patterns in `~/.onecommand/memory/`:
- `patterns.json` — successful app_type + feature + stack combinations
- `errors.json` — recurring errors and their fixes
- `stacks.json` — proven tech stack combinations with run counts

## Development

When modifying this plugin, files in `skills/` and `agents/` are the most important. Each file contains instructions for a specific phase of the build. The orchestrator is `commands/onecommand.md`.

Design specs live in `docs/superpowers/specs/`.
Implementation plans live in `docs/superpowers/plans/`.
