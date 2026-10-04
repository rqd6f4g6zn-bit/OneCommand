# OneCommand

Build complete, production-ready software systems from a single prompt.

One command. Eight phases. Working software.

---

## Install

```bash
git clone https://github.com/rqd6f4g6zn-bit/OneCommand.git ~/OneCommand
cd ~/OneCommand
./install.sh            # add --dry-run to preview, --verbose for per-file output
```

The installer is idempotent and syncs by content: after `git pull`, re-run it and every changed
file reaches Claude Code and Codex — unchanged files are skipped. It needs `python3` and `rsync`.

Then restart Claude Code and run `/oc-doctor` to confirm the installation is healthy.

## Usage

```bash
/onecommand "fitness app with login, workout tracking, and leaderboard"
/onecommand "SaaS dashboard with Stripe payments, team management, and analytics"
/onecommand "e-commerce store with product catalog, cart, checkout, and admin panel"
/onecommand "security monitoring system with alerting, logs, and user management"
/onecommand "real estate platform with listings, search, favorites, and agent portal"
```

## What Gets Built

OneCommand runs 8 phases automatically:

| Phase | What happens |
|-------|-------------|
| 1. Spec | Analyzes your prompt → structured project spec |
| 2. Frontend + Backend | Parallel generation: full UI + API + DB + auth |
| 3. Integration + Marketing | Connect systems, generate README + landing page |
| 4. Quality Gate + Acceptance | Build, lint, types, unit tests — then every acceptance criterion from the spec as a Playwright test against the running app; self-healing until green |
| 5. Automations | Git hooks, GitHub Actions CI/CD, Makefile |
| 6. Exceed Expectations | Dark mode, PWA, accessibility, security audit — then a final regression gate |
| 7. Self-Improvement | Learn from this run for better future builds |
| 8. Delivery | Complete report + deploy instructions |

The whole run needs no manual steps: every phase runs in its own subagent, so the build never
pauses for `/clear`. State is checkpointed to disk after each phase — if anything interrupts the
build, `/oc-resume` continues where it stopped.

## Definition of Done

Phase 1 writes **acceptance criteria** into `.onecommand-spec.json` — concrete, observable results per
feature ("after login, /dashboard shows heading 'Dashboard'", "GET /api/workouts without a session
returns 401"). Phase 4 turns each one into a Playwright test and runs it against the production
build with a real database. A build is only reported as complete when every `must` criterion
passes; otherwise the delivery report says **NOT VERIFIED** and lists what is open.

The verdict comes from `hooks/quality-gate.sh`, not from an agent's judgement:

```bash
bash hooks/quality-gate.sh --stage all --project-dir ~/Desktop/MyApp
# → .onecommand/gate/result.json, errors.txt, acceptance.md
```

## Output

- **Full frontend** (Next.js + Tailwind + shadcn/ui) — all pages, components, mobile responsive
- **Complete backend** (API routes, auth, DB schema, migrations, seed data)
- **Acceptance suite** (`e2e/acceptance/`, one Playwright test per criterion, runnable with `npx playwright test`)
- **Automation** (Git hooks, GitHub Actions, Makefile)
- **Documentation** (README, CHANGELOG, landing page)
- **Security** (OWASP audit, rate limiting, input validation)
- **Extras** (dark mode, PWA, error boundaries, loading skeletons, accessibility)

## Commands

| Command | Description |
|---------|-------------|
| `/onecommand "<prompt>"` | Build a complete software system |
| `/onecommand-status` | Show current build phase progress |
| `/oc-save` | Save build state so `/clear` is safe at any moment |
| `/oc-resume` | Continue an interrupted build from the last phase |
| `/oc-doctor` | Diagnose the installation and print exact fixes |

Builds are written to `~/Desktop/<ProjectName>` — never into the plugin folder. If the current
directory already contains a OneCommand spec, that directory is used instead (resume case).

## Requirements

- **Claude Code** with this plugin installed
- **Node.js 20+**
- **python3** and **rsync** (for `install.sh`)
- **Codex CLI** for backend generation: `/codex:setup` (recommended, not required)
- **Required plugins**: `superpowers`, `marketing-skills`
- **Optional**: PostgreSQL (for local DB-backed apps), Docker

## Self-Improvement

Every run stores learned patterns in `~/.onecommand/memory/`. Over time, OneCommand makes better stack decisions and produces fewer errors on the first attempt.

---

*Built by USC Software UG*
