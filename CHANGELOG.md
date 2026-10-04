# Changelog

All notable changes to OneCommand. Versions follow `.claude-plugin/plugin.json`.

## [1.10.0] — 2026-10-04

### Added
- **Own image and video generators, trained from zero.** Template `skills/ml-builder/templates/scratch-diffusion`:
  U-Net noise predictor (2D for images, 3D for videos — space is downsampled, every frame kept), cosine DDPM
  objective, DDIM sampler, EMA weights, class conditioning from dataset folders, `generate` CLI and
  `POST /generate` (base64 PNG / MP4). Configs `smoke`, `cpu`, `default`, `video-smoke`, `video-cpu`,
  `video-default`. Training writes a checkpoint every 5 % and resumes after an interruption (container restart,
  preempted GPU) — found when two container restarts killed long CPU runs.
  Metric `nn_ratio`: distance of each sample to its nearest real training item ÷ the same for pure noise (lower is
  better). Trained here on the company's own 70 CRM screenshots (CPU, 6 min, 0.7M parameters): samples show the
  interface's style (white panels, text lines, blue accents), nn_ratio 0.55 — all ML gate steps green.
  The real runs found three template bugs, all fixed: the DDIM step reused the pre-clipping noise estimate
  (samples stayed noise); data far from mid-grey (white screenshots) needs per-channel normalisation or samples
  get the wrong brightness; a colour-histogram metric rated noise as "close" to white screenshots, and averaging
  video frames over time made noise look like flat data.
- **`dataset.py --task images | videos`:** collects own media (folder = label), removes exact and visually
  near-identical files (8×8 average hash via ffmpeg), splits by file, records every file's SHA-256; `check`
  detects changed or missing source files.
- Second real v1.7.0 build ("Ticketsystem für unseren Support mit Kundenportal" → Servicehafen): score 100,
  36/36 must-criteria, 52 min; API contract with 33 endpoints passed, 3 metrics labelled with their period,
  3 demo logins, 59 tour screenshots. Lessons folded in: every ticked review line needs a note
  (`→ ok: …` / `→ see findings`) — the agent had ticked 34 screenshots without one and missed the admin landing
  in the customer portal on mobile; review.md states that unlisted screenshots are covered by automated checks
  (the report had listed them as open); expected 401s of the session probe on login pages no longer warn.
- **AI phone support assistants:** blueprint `phone-assistant` (telephony with signature-checked webhooks, AI
  disclosure per EU AI Act, answers from the own knowledge base without invented facts, actions, warm handover,
  DTMF 0, call log, analytics, own intent model trained from own transcripts, GDPR masking and retention,
  multilingual, outbound, self-hosted speech — 14 modules), skill `voice-agent` (architecture, providers cloud
  vs. self-hosted, latency budget, dialogue rules, compliance) and **`hooks/call-sim.py`**: scripted test calls
  against `POST /api/voice/simulate` — greeting must disclose the AI, expected intent, facts, actions,
  handover, end of call, ≤ 300 characters and the latency budget per turn; `validate` requires a test call for
  every intent and the handover. The gate's `tour` stage plays them; `report.md` is the transcript of every call.
- ml-builder: section on generative models — data and compute tiers, no text prompts without an own text
  encoder, rights and consent, marking generated media.

## [1.9.0] — 2026-10-04

### Added
- **Train an own model from zero on own data.** "Eigenes Modell", "von null", "von Grund auf" set
  `ml.from_scratch`: own architecture, own tokenizer, random initialisation, trained only on the user's data.
- **`hooks/dataset.py`** (`build`, `check`, `stats`): the user's raw files (.txt .md .html .csv .jsonl, or one
  folder per label) → cleaned, personal data replaced ([EMAIL] [TELEFON] [IBAN] [URL-MIT-TOKEN]), exact and
  near duplicates removed (MinHash), split by document (stratified per label), `manifest.json` with SHA-256
  of every input and output, `DATASHEET.md`. `check` fails on edited splits and on text in two splits.
- **ML gate for from-scratch models:** `dataset` (manifest valid, splits disjoint), `scratch` (no
  `from_pretrained("<hub id>")`, `pretrained=True`, torchvision weights, `torch.hub`, hub downloads in `src/`;
  own checkpoints are fine), `learning` (training loss falls by `min_loss_drop`), `artifact` (weights file
  written); `predict_path` for APIs like `/generate`.
- **Tested template `skills/ml-builder/templates/scratch-lm`:** GPT (decoder-only transformer) + byte-level BPE
  tokenizer trained on the train split, AdamW/warmup/cosine, safetensors, unigram baseline
  (`perplexity_ratio`), `generate` CLI, `POST /generate`; configs `smoke` (gate), `cpu` (~10 min), `default`
  (GPU). Trained here on the plugin's own documentation (670k characters): smoke run 0.3M parameters in
  21 s, training loss 6.92 → 4.48, perplexity 0.41× the unigram baseline — the gate passes all 12 steps.

### Fixed
- Template: `numpy` is required by safetensors (found by the real run); `download.pytorch.org` blocked →
  `uv sync --no-sources` documented as fallback.

## [1.8.0] — 2026-10-04

### Added
- **AI/ML training projects** (`agents/ml-agent.md`, `skills/ml-builder`, `hooks/ml-gate.py`): prompts that
  ask to train a model get build target `ml` — data pipeline with a licensed sample, baseline, smoke and
  full training configs, evaluation, model card, FastAPI inference service, Dockerfile. Templates for
  tabular, text and image classification, LLM fine-tuning (LoRA) and time series. `quality-gate.sh`
  hands ML specs to `ml-gate.py`: install → lint → tests → smoke training → metric ≥ `smoke_min` →
  model card → `POST /predict` (same result.json, so test-agent, self-healer and the report work unchanged).
- **Video pipeline** (`hooks/video.py`, `skills/video-producer`): `probe`, `scenes` (cut detection),
  `render` from an edit plan (cut by time, Ken-Burns shots from images, one size/fps, fades, music bed,
  MP4 H.264 faststart + WebM VP9 + poster, quality stepped down until `max_kb` fits, `videos.json`
  manifest) and `check` (both formats, poster, faststart, muted loops without audio, budget). Motion
  graphics via Remotion when there is no footage; credits and licenses per clip.
- **Website blueprint** (`website`): corporate and premium websites in three tiers — pages, contact with
  spam protection, GDPR consent, SEO, 404 (mvp); design system, motion with reduced-motion, hero video,
  case studies, CMS with preview, blog, i18n, performance, WCAG 2.2 AA (pro); page builder, image film
  with captions, careers with CV upload, newsletter double opt-in, search, lead routing, Lighthouse CI
  (enterprise, selected by "Premium", "100k", "Agenturniveau"). 21 modules, 25 criteria.
- **Performance budget in the UI tour** (`spec.performance_budget`: `lcp_ms`, `cls`, `page_kb`): every page
  is measured on first visit without cache at 10 Mbit/s / 40 ms (desktop); a violation is blocking.
  report.md shows LCP, CLS and KB per page.
- `blueprint.py expand` carries `performance_budget` and `media.videos` into the spec and finds the login
  page of any blueprint (e.g. `/admin/login`).

### Fixed
- API contract: route handlers under folders named like test directories (`app/api/test/…`) were not
  found. Found by the first real v1.7.0 build, whose agent patched the plugin file itself — test-agent now
  reports plugin bugs instead of editing `$OC_ROOT`.

## [1.7.0] — 2026-10-04

Screenshots of the CRM built in 1.6.0 showed errors that 43 green acceptance tests missed: a win-rate
tile reading "100 %" above "5 gewonnen, 2 verloren", two different open-pipeline totals, an empty
"Meine Aufgaben" for the admin demo login and a mobile page 212 px too wide. The plugin now finds these
error classes itself in every build.

### Added
- **API contract** (`hooks/api-contract.py`, gate step `contract`): the spec defines every endpoint's
  request and response (`api_contract`); `types` generates one TypeScript file (`<Name>Response`,
  `<Name>Request`, `API`, `METRICS`) before Phase 2, so frontend (Claude) and backend (Codex) build against
  the same shapes. The static stage fails when the generated file was edited or is stale, an endpoint has
  no route handler exporting its method (Next.js App Router, `[param]` and catch-all routes resolved like
  Next.js does), a handler or the UI does not use its response type. Code that tries several field names
  (`pick(data, ["winRate", "closeRate", …])` — 16 places in the CRM build) is reported as a warning.
- **Metrics** (`spec.metrics`, blueprint `metrics`): every KPI has one definition, period, unit and label
  plus the pages that show it. The CRM, helpdesk, invoicing, projects and shop blueprints define theirs;
  `blueprint.py check` fails when one is dropped. CRM blueprint v3 adds two criteria: the win-rate tile
  names its period and counts from the same period; dashboard and reports agree.
- **UI tour** (`hooks/ui-tour.py`, gate stage `tour`, part of `--stage all`): loads the full demo data
  (`demo.seed_command`, `SEED_MODE=demo`), starts the production build with fresh strong secrets, logs in
  through the real form with every `demo.accounts` login and screenshots every page of the spec: desktop
  for every role, mobile for the first account; dynamic pages are reached through links. Blocking: failed
  login, HTTP 5xx, uncaught exceptions, failed API calls, "undefined"/"NaN"/"Invalid Date" on screen, a lost
  session, a metric without its spec label. Warnings: mobile overflow, console errors, unreachable dynamic
  pages. Writes `report.md` and `review.md`; test-agent reviews every listed screenshot and
  `ui-tour.py review-status` must pass before delivery. Against the real CRM: 107 screenshots in 2:43 min,
  and it found the mobile overflow and the missing metric labels.
- **Demo logins** (`spec.demo`): one login per role; `blueprint.py expand` drafts them from the roles.
  The demo seed fills every view for every account.
- **Showcase** (`docs/showcase/crm/`): the CRM built from "CRM auf höchstem Niveau", 12 desktop and
  2 mobile screenshots, linked from the README.

### Changed
- spec-analyzer writes `api_contract`, `metrics`, `demo` and validates them; frontend-agent builds a typed
  client on the generated file and labels tiles from `METRICS`; backend-agent types handlers with
  `satisfies`, computes each metric in one function and seeds data for every demo login; collab-protocol
  hands Codex the contract; self-healer has strategies for contract and tour failures; the delivery report
  embeds the tour screenshots and the demo logins.
- Quality gate: steps with `⚠` lines in their log are recorded as `warn`; the database is prepared once
  per run.
- USC Software UG branding: `/oc-doctor` report, README header and footer, plugin manifests (author
  URL), CRM showcase, generated contract file and UI tour report.
- No personal names or home paths in docs and install instructions (company name only);
  `test_repo_consistency` checks every tracked file.

## [1.6.0] — 2026-10-04

### Added
- **Domain blueprints** (`skills/domain-blueprints`, `hooks/blueprint.py`): structured domain knowledge
  for CRM, online shop, appointment booking, helpdesk, project management and invoicing — modules,
  entities, roles, pages and concrete acceptance criteria in three cumulative tiers (mvp / pro /
  enterprise). A short prompt like "CRM auf höchstem Niveau" is detected as `crm` · `enterprise` and
  expanded into 22 modules with 43 acceptance criteria. spec-analyzer builds on the draft; `check`
  fails when a blueprint module or criterion is dropped (modules may only be excluded with the user's
  reason). The delivery report states the tier and any excluded modules.
- **Proven in a real build:** `CRM auf höchstem Niveau` → NovaCRM (25 pages, 65 API routes, 26 models,
  ~7.5k lines), gate 43/43 incl. the regression run, 50 min — baseline in
  `bench/baselines/v1.6.0-crm-enterprise.json`. Findings from that run are folded in:
  - crm blueprint v2: criterion for shared records (role text promised them, nothing tested them, so they
    were not built); tenant isolation tested across list, detail, search, export and reports (the
    security audit found a path the single-path criterion missed); SSO rejects unverified e-mails;
    non-functional security requirements (no default auth secret, CSP and security headers, SSRF checks,
    real sync outside test mode).
  - Quality gate records `test-changes` warnings: acceptance test files changed after the first run
    without an entry in `.onecommand/test-changes.md` (a test was changed silently in the CRM build).
  - Headless builds: Claude Code may run parallel agents in the background despite
    `run_in_background: false`; the orchestrator waits for their notifications and `bench/run.py` sets
    `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`.
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
