# OneCommand Plugin

OneCommand is a Claude Code plugin that builds complete, production-ready software systems from a single natural language prompt.

## Plugin Structure

```
.claude-plugin/plugin.json   # Plugin manifest
commands/                    # Slash commands (/onecommand, /onecommand-status, /oc-save, /oc-resume, /oc-doctor)
skills/                      # Reusable skills invoked by agents and commands
agents/                      # Specialized agents for each build phase
hooks/                       # post-generate.sh, quality-gate.sh, acceptance-report.py
docs/superpowers/            # Design specs and implementation plans
```

## Commands

- `/onecommand "<prompt>"` — Build a complete software system from a description
- `/onecommand-status` — Show current build phase progress
- `/oc-save` — Save build state so `/clear` is safe
- `/oc-resume` — Resume an interrupted build from the last completed phase
- `/oc-doctor` — Diagnose the installation (registry, commands, brain, Codex)

## Workflow Overview

```
Phase 1: Spec          → spec-analyzer (incl. acceptance_criteria, validated) + stack-detector
Phase 2: Parallel      → frontend-agent (Claude) + backend-agent (Codex)
Phase 3: Integration   → integration subagent + live-integrations + marketing-agent
Phase 4: Gate          → test-agent: quality-gate.sh static → acceptance-tester (Playwright) → e2e; self-healer
Phase 5: Automations   → automation-installer skill
Phase 6: Exceed        → exceed-expectations + security-agent + demo-cleaner, then regression gate
Phase 7: Self-Improve  → self-improve-agent (writes to ~/.onecommand/memory/)
Phase 8: Delivery      → delivery-reporter skill
```

Every phase runs in subagents (`OC_ROOT` + `PROJECT_DIR` passed in each prompt); the orchestrator
never stops for `/clear`. auto-clear SAVE is a silent checkpoint after every phase.

## Quality Gate

- `hooks/quality-gate.sh --stage static|e2e|all` is the only pass/fail verdict. Never decide it with
  `cmd | tee log; $?` — that is `tee`'s exit code. Output: `<project>/.onecommand/gate/result.json`.
- `hooks/acceptance-report.py validate` checks a spec's acceptance criteria; `report` maps Playwright
  results (test titles start with `AC-###`) onto them. A missing test counts as a failure.
- Exit codes: 0 passed · 1 failed · 2 usage error · 3 not applicable (no package.json).

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

Releasing: bump `version` in `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` and
`PLUGIN_VERSION` in `install.sh` together. New skills must also be added to `BUNDLED_SKILLS` in
`install.sh` (the installer warns about unlisted skill directories). Test the installer against a
throwaway home: `HOME=$(mktemp -d) ./install.sh --verbose`.

Design specs live in `docs/superpowers/specs/`.
Implementation plans live in `docs/superpowers/plans/`.
