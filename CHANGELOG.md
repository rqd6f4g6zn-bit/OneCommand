# Changelog

All notable changes to OneCommand. Versions follow `.claude-plugin/plugin.json`.

## [1.5.1] — 2026-10-04

### Added
- **Benchmark** (`bench/run.py`, `bench/prompts.json`): builds fixed prompts headless with the plugin
  under test and scores each build from OneCommand's own artefacts (gate verdict, acceptance ratio,
  phases completed) plus wall time, cost, agent and gate-run counts. `compare` flags regressions
  between two runs. Sets: `core` (3 web apps) and `extended` (+ booking, mobile, game, OS).
  Baseline from the first real build: `bench/baselines/v1.5.0.json` (score 100, 18/18, 50 min).
- **`hooks/playwright-pin.py`**: pins `@playwright/test` to the version whose browsers are actually
  installed (`playwright install --dry-run` reports the needed revision without downloading).
  The acceptance-tester runs it right after installing Playwright.
- **Dependency audit in the gate**: `npm/pnpm audit` on production dependencies runs in the static
  stage, so vulnerable packages are fixed while building instead of by a late security pass that
  forces a full re-verification. Critical advisories fail the gate; high ones are recorded as
  `warnings` in `result.json` and shown in the delivery report (`--audit-level high` makes them
  blocking). `--no-audit` / `OC_GATE_AUDIT=0`; an unreachable registry skips it — the JSON verdict
  never mistakes a failed audit request for "no advisories".

### Changed
- acceptance-tester: table of Playwright pitfalls that each cost a healing round in the real build
  (duplicate toasts, empty-list assertions, re-registering users, hover-only buttons, URL races).
- self-healer: categories for audit failures and browser mismatches.

## [1.5.0] — 2026-10-04

### Added
- **Skill plan** (`hooks/skill-catalog.py`): every build considers every available skill — bundled
  ones (mapped to phases from the spec) and user-installed ones (`~/.claude/skills`, project
  `.claude/skills`, enabled plugins). Each external skill needs an explicit decision; `check` fails
  while one is undecided. Phase subagents receive their skills via `for-phase N`.
- **Automatic self-update** (`hooks/update.py`, `hooks/hooks.json`, `/oc-update`): SessionStart hook
  fast-forwards the tracked branch and re-runs `install.sh`, rolls back a failed install and does not
  retry the same broken commit. Never during a running build, with local changes, on another branch
  or when diverged. Settings in `~/.onecommand/config.json`.
- **Test suite** (`tests/`, pytest) for every script, the installer and repository invariants, plus an
  end-to-end gate run against a real Prisma/SQLite app with Playwright; **CI** on Linux and macOS
  (bash 3.2) with shellcheck.

### Changed
- Agents and skills use model aliases (`opus` / `sonnet`) instead of pinned model IDs.
- Plugin agents are dispatched by their namespaced name (`onecommand:<agent>`).
- Previously orphaned skills are wired in: `app-icon-generator` (mobile), `collab-protocol`
  (Phase 2 task split), `codex-setup` (pre-flight hint).

### Fixed
- Quality gate: `DATABASE_URL` comes from the project's `.env.local` / `.env` and falls back to the
  local Postgres default only for Postgres schemas (SQLite projects got a Postgres URL forced on them).
- Quality gate: the install cache never hit, because the manifest hash was taken before `npm install`
  rewrote the lockfile.
- `codex-setup` wrote a machine-specific path into `~/.codex/config.toml`.

## [1.4.1] — 2026-10-04

### Fixed
- Eight skills had a second, never-loaded `<name>.md` next to `SKILL.md`. Content that existed only
  there is merged: `production_dependencies` + mobile detection in `spec-analyzer` (without it
  `live-integrations` never ran), the "Remaining Production Steps" section in `delivery-reporter`,
  learning capture in `self-healer`. The duplicates are removed (also from `~/.codex/skills`).
- Promoted learnings were written into the unloaded `self-healer.md` via hard-coded paths, and each
  promotion dropped earlier rules. New `hooks/learnings.py` (locking, atomic writes) writes
  `~/.onecommand/memory/evolved_rules.md`, which the self-healer loads before every healing round.
- The spec example in `spec-analyzer` failed its own validator.

## [1.4.0] — 2026-10-04

### Added
- **Quality gate** (`hooks/quality-gate.sh`) as the single pass/fail verdict with real exit codes,
  per-step logs, `errors.txt` and `result.json`.
- **Acceptance criteria** in the spec, validated before the build starts; `acceptance-tester` turns
  them into Playwright tests against the production build; `acceptance-report.py` maps results back.
  A missing, skipped or failed test on a must-criterion fails the build. Regression gate after Phase 6.
- Delivery report shows the acceptance matrix and marks failed builds **NOT VERIFIED**.

### Changed
- No more manual `/clear` stops: every phase runs in a subagent; auto-clear SAVE is a silent
  checkpoint after each phase.

### Fixed
- test-agent decided pass/fail with `cmd | tee log; $?` — the exit code of `tee`, always 0 — so broken
  builds passed and the self-healer never ran. Same pattern in the Codex skill.

## [1.3.7] — 2026-10-04

### Fixed
- `install.sh`: never overwrites an unparseable `settings.json`; content-based sync (upgrades without a
  version bump arrive, obsolete files are removed); fallback commands and Codex skills are updated;
  prerequisite check; `--dry-run`, `--verbose`.
- `/oc-doctor` finds the checkout through the registry instead of a hard-coded path.
- `post-generate.sh` reported a failed `npm install` as success.
