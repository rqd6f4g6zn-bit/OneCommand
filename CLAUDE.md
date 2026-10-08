# OneCommand Plugin

OneCommand is a Claude Code plugin that builds complete, production-ready software systems from a single natural language prompt.

## Plugin Structure

```
.claude-plugin/plugin.json   # Plugin manifest
commands/                    # Slash commands (/onecommand, /onecommand-status, /oc-save, /oc-resume, /oc-doctor, /oc-update, /oc-skills)
skills/                      # Reusable skills invoked by agents and commands
agents/                      # Specialized agents for each build phase
hooks/                       # hooks.json (SessionStart auto-update) + build scripts (see below)
docs/superpowers/            # Design specs and implementation plans
```

## Commands

- `/onecommand "<prompt>"` — Build a complete software system from a description
- `/onecommand-status` — Show current build phase progress
- `/oc-save` — Save build state so `/clear` is safe
- `/oc-resume` — Resume an interrupted build from the last completed phase
- `/oc-doctor` — Diagnose the installation (registry, commands, brain, Codex)
- `/oc-skills [topic]` — The skill library: every bundled and installed skill, searchable
- `/oc-update` — Install the latest release now (`check`, `status`, `off`, `on`)

## Workflow Overview

```
Phase 1: Spec          → spec-analyzer (incl. acceptance_criteria, validated) + stack-detector
Phase 2: Parallel      → frontend-agent (Claude) + backend-agent (Codex)
Phase 3: Integration   → integration subagent + live-integrations + marketing-agent
Phase 4: Gate          → test-agent: quality-gate.sh static → acceptance-tester (Playwright) → e2e → tour + screenshot review; self-healer
Phase 5: Automations   → automation-installer skill
Phase 6: Exceed        → exceed-expectations + security-agent + demo-cleaner, then regression gate
Phase 7: Self-Improve  → self-improve-agent (writes to ~/.onecommand/memory/)
Phase 8: Delivery      → delivery-reporter skill
```

Every phase runs in subagents (`OC_ROOT` + `PROJECT_DIR` passed in each prompt); the orchestrator
never stops for `/clear`. auto-clear SAVE is a silent checkpoint after every phase.

## Quality Gate

- `hooks/quality-gate.sh --stage static|e2e|tour|all` is the only pass/fail verdict. Never decide it with
  `cmd | tee log; $?` — that is `tee`'s exit code. Output: `<project>/.onecommand/gate/result.json`.
- `hooks/acceptance-report.py validate` checks a spec's acceptance criteria; `report` maps Playwright
  results (test titles start with `AC-###`) onto them. A missing test counts as a failure.
- `hooks/api-contract.py` (gate step `contract`): `api_contract` in the spec → one generated TypeScript
  file both sides import; fails on hand-edited types, missing route handlers and untyped handlers/fetches.
- `hooks/ui-tour.py` (stage `tour`): demo seed, production start with fresh secrets, every page as every
  `demo.accounts` login, screenshots + `.onecommand/tour/review.md`; `review-status` must pass before delivery.
  Its design audit (`DESIGN_JS`: shipped fonts, code values, WCAG contrast, table lines, sidebar) adds
  measured findings that stay open until a re-run no longer finds them.
- `hooks/ml-gate.py`: quality-gate.sh hands specs with build target `ml` to it — install, lint, tests,
  smoke training, metric ≥ `ml.metric.smoke_min`, model card, `POST /predict`. Same result.json.
- `hooks/dataset.py build|check|stats`: the user's own raw files → cleaned, PII-scrubbed, deduplicated,
  split dataset with manifest + datasheet. With `ml.from_scratch` the ML gate also checks the dataset,
  rejects pretrained weights in `src/`, requires a falling training loss and the weights file.
- `hooks/call-sim.py validate|run`: scripted test calls for phone assistants (spec `voice`) — AI disclosure,
  intents, facts, actions, handover, reply length, latency, built-in small-talk, complaint, follow-up and caller-identity probes, no TwiML `<Say>` or
  robotic speech engine, voice samples via `voice.tts_endpoint`, a pronunciation round trip via
  `voice.stt_endpoint`; run by the gate's `tour` stage.
  `dataset.py --task speech` checks voice recordings (own brand voice) and reports the hours per voice path.
- `hooks/video.py probe|scenes|render|check`: website videos (ffmpeg) — cut, Ken Burns, MP4 + WebM + poster
  within `max_kb`; used by the `video-producer` skill when `spec.media.videos` is set.
- Exit codes: 0 passed · 1 failed · 2 usage error · 3 not applicable (no package.json).

## Domain Blueprints

`skills/domain-blueprints/blueprints/<id>.json` — 10 products (crm, shop, booking, helpdesk, projects, invoicing,
phone-assistant, website, recruiting, warehouse) and 8 industries (notary, law-firm, tax-advisor, medical-practice,
property-management, real-estate-agency, trades, restaurant) — hold modules, entities, roles, pages, acceptance
criteria per tier (mvp ⊂ pro ⊂ enterprise), `design`, `compliance` (§ sources) and `integrations`
(connectable / export_only / not_possible). `detect` plans combinations (`--with` product modules, `--context`
industry look and duties). No match → the spec needs a `domain_brief` (`blueprint.py brief`); `check` fails
without it.
`hooks/blueprint.py detect|expand|check`: spec-analyzer expands the matching blueprint and builds the
spec on top; `check` fails when a module or a blueprint criterion (`source` tag) is dropped. New
blueprints: add a JSON file — `tests/test_blueprint.py` validates schema and every tier expansion.

## Skill Plan

`hooks/skill-catalog.py` makes every build consider every skill. `scan` discovers bundled skills
(mapped to phases via `BUNDLED` in the script) and external ones (`~/.claude/skills`, project
`.claude/skills`, enabled plugins); the orchestrator decides each external skill in
`.onecommand/skill-plan.json`; `check` fails while one is undecided; `for-phase N` output goes into
every subagent prompt. Agents load skills with `skill-catalog.py read <skill> --phase N` (prints the
SKILL.md, records it in `.onecommand/skills-read.json`); `check-read N` fails for an assigned skill nobody
loaded, and `checkpoint.py phase N` refuses to save until it passes. Every agent has a "Step 0 — Load your
skills" and lists its bundled skills bare and as `onecommand:<name>`.
The library (`skill-catalog.py library [--search]`, `/oc-skills`) lists every bundled and installed skill;
`skills/LIBRARY.md` is generated from `BUNDLED` (`library --markdown`) and a test keeps it in sync. **A new bundled skill must be added to `BUNDLED`** — `install.sh` fails the
verification step otherwise.

## Auto-Update

`hooks/hooks.json` runs `hooks/update.py auto --quiet` at SessionStart: throttled
(`update_interval_hours`), fast-forward only, rollback on failed install, skipped during a running
build, with local changes or on another branch. A commit that failed to install is not retried until
a newer one appears. Codex runs the same script in its pre-flight.

## Benchmark

`bench/run.py run --set core --skip-permissions` builds the prompts in `bench/prompts.json`
headless (`claude --plugin-dir . -p '/onecommand:onecommand "…"'`) and scores them; `compare`
against `bench/baselines/` shows regressions. Builds run sequentially (they share
`~/.onecommand/brain`). Use it to verify changes to skills, agents or the orchestrator.

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
- `cross_learnings.json` — fixes recorded by Claude Code and Codex (`hooks/learnings.py record`)
- `evolved_rules.md` — learnings confirmed 3+ times (`hooks/learnings.py evolve`); the self-healer
  loads it before every healing round

Learned rules are never written into plugin files — those are replaced on every install and tracked
in git.

## Development

When modifying this plugin, files in `skills/` and `agents/` are the most important. Each skill has
exactly one instruction file, `skills/<name>/SKILL.md` — never add a second copy next to it (the
installer warns about them). Each file contains instructions for a specific phase of the build. The orchestrator is `commands/onecommand.md`.

Releasing: bump `version` in `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` and
`PLUGIN_VERSION` in `install.sh` together. New skills must also be added to `BUNDLED_SKILLS` in
`install.sh` (the installer warns about unlisted skill directories). Test the installer against a
throwaway home: `HOME=$(mktemp -d) ./install.sh --verbose`.

Attribution: commits are authored by `USC Software UG <info@usc-software.de>`. Commit messages, PR
descriptions and comments carry no AI attribution — no "Generated with …" line, no `Co-Authored-By`
trailer, no session link. PR descriptions end with `*USC Software UG · usc-software-ug.de*`.

Findings from a built project are fixed in the plugin (skills, agents, hooks), never in the built project.
To test a skill rule, use a throwaway copy, and never present it as the plugin's output. Showcase images come
unedited from real builds.

Design specs live in `docs/superpowers/specs/`.
Implementation plans live in `docs/superpowers/plans/`.
