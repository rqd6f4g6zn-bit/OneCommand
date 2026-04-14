# OneCommand

Build complete, production-ready software systems from a single prompt.

One command. Eight phases. Working software.

---

## Install

```bash
# In Claude Code
/plugin install /Users/g.urban/OneComand
```

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
| 4. Tests + Self-Healing | Run checks, fix errors automatically (up to 5 iterations) |
| 5. Automations | Git hooks, GitHub Actions CI/CD, Makefile |
| 6. Exceed Expectations | Dark mode, PWA, accessibility, security audit |
| 7. Self-Improvement | Learn from this run for better future builds |
| 8. Delivery | Complete report + deploy instructions |

## Output

- **Full frontend** (Next.js + Tailwind + shadcn/ui) — all pages, components, mobile responsive
- **Complete backend** (API routes, auth, DB schema, migrations, seed data)
- **Automation** (Git hooks, GitHub Actions, Makefile)
- **Documentation** (README, CHANGELOG, landing page)
- **Security** (OWASP audit, rate limiting, input validation)
- **Extras** (dark mode, PWA, error boundaries, loading skeletons, accessibility)

## Commands

| Command | Description |
|---------|-------------|
| `/onecommand "<prompt>"` | Build a complete software system |
| `/onecommand-status` | Show current build phase progress |

## Requirements

- **Claude Code** with this plugin installed
- **Node.js 20+**
- **Codex CLI** for backend generation: `/codex:setup` (recommended, not required)
- **Required plugins**: `superpowers`, `marketing-skills`
- **Optional**: PostgreSQL (for local DB-backed apps), Docker

## Self-Improvement

Every run stores learned patterns in `~/.onecommand/memory/`. Over time, OneCommand makes better stack decisions and produces fewer errors on the first attempt.

---

*Built by USC Software UG*
