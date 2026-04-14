# OneCommand Plugin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that takes a single `/onecommand "<prompt>"` and delivers a complete, deployable software system through an 8-phase parallel multi-agent workflow.

**Architecture:** The plugin orchestrates Claude and Codex as specialized agents across 8 phases (Spec → Frontend+Backend parallel → Integration+Marketing → Tests+Self-Healing → Automations → Exceed-Expectations → Self-Improve → Delivery). Each phase is a focused skill or agent markdown file that Claude Code loads and executes.

**Tech Stack:** Claude Code Plugin (markdown-based), Codex CLI delegation, Shell hooks, JSON memory store at `~/.onecommand/memory/`

---

## File Map

```
/Users/g.urban/OneComand/
├── .claude-plugin/
│   └── plugin.json                          # Plugin manifest
├── commands/
│   ├── onecommand.md                        # Main /onecommand command (orchestrator)
│   └── onecommand-status.md                 # /onecommand-status command
├── skills/
│   ├── spec-analyzer/
│   │   └── spec-analyzer.md                 # Prompt → structured JSON spec
│   ├── stack-detector/
│   │   └── stack-detector.md                # Detect/select tech stack
│   ├── self-healer/
│   │   └── self-healer.md                   # Error-fix loop (max 5 iterations)
│   ├── automation-installer/
│   │   └── automation-installer.md          # Git hooks, CI/CD, Makefile
│   ├── exceed-expectations/
│   │   └── exceed-expectations.md           # Security, perf, a11y, surprise features
│   └── delivery-reporter/
│       └── delivery-reporter.md             # Final summary + deploy guide
├── agents/
│   ├── frontend-agent.md                    # UI via frontend-design + ui-ux-pro-max
│   ├── backend-agent.md                     # API+Auth+DB via Codex
│   ├── test-agent.md                        # Run tests, collect errors
│   ├── marketing-agent.md                   # Landing page + README via marketing-skills
│   ├── security-agent.md                    # OWASP audit + fixes
│   └── self-improve-agent.md                # Extract patterns → ~/.onecommand/memory/
└── hooks/
    └── post-generate.sh                     # npm install + build after code generation
```

---

## Task 1: Plugin manifest

**Files:**
- Create: `.claude-plugin/plugin.json`

- [ ] **Step 1: Create manifest**

```json
{
  "name": "onecommand",
  "version": "1.0.0",
  "description": "Build complete, production-ready software systems from a single prompt. Orchestrates Claude and Codex across 8 phases: Spec, Frontend, Backend, Integration, Tests, Automations, Exceed-Expectations, and Self-Improvement.",
  "author": {
    "name": "USC Software UG"
  }
}
```

Write to: `.claude-plugin/plugin.json`

- [ ] **Step 2: Create directory structure**

```bash
mkdir -p .claude-plugin
mkdir -p commands
mkdir -p skills/spec-analyzer
mkdir -p skills/stack-detector
mkdir -p skills/self-healer
mkdir -p skills/automation-installer
mkdir -p skills/exceed-expectations
mkdir -p skills/delivery-reporter
mkdir -p agents
mkdir -p hooks
```

- [ ] **Step 3: Verify structure**

```bash
find . -not -path './.git/*' -not -path './docs/*' | sort
```

Expected output includes all directories above.

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "feat: add plugin manifest"
```

---

## Task 2: spec-analyzer skill

**Files:**
- Create: `skills/spec-analyzer/spec-analyzer.md`

- [ ] **Step 1: Write skill**

```markdown
---
name: spec-analyzer
description: Analyzes a natural language project prompt and produces a structured JSON specification. Loads prior patterns from ~/.onecommand/memory/ if available.
---

You are the Spec Analyzer for OneCommand. Your job is to turn a natural-language project prompt into a precise, structured specification that all downstream agents can use.

## Input
The user's raw project prompt (passed as $ARGUMENTS or from context).

## Steps

1. **Load memory** — Check if `~/.onecommand/memory/patterns.json` exists:
   ```bash
   cat ~/.onecommand/memory/patterns.json 2>/dev/null || echo "{}"
   ```
   If patterns exist, use them to inform your tech stack and architecture decisions.

2. **Analyze the prompt** — Extract:
   - `app_type`: the category (web-app, mobile-web, api, dashboard, ecommerce, saas, game, tool)
   - `features`: array of required features (e.g. ["auth", "dashboard", "real-time", "payments"])
   - `tech_stack`: chosen stack based on app_type + features + memory patterns
   - `pages`: array of UI pages/screens required
   - `api_routes`: array of backend endpoints required
   - `db_schema`: tables/models needed
   - `auth_type`: none | jwt | oauth | magic-link
   - `deploy_target`: vercel | railway | docker | fly
   - `extra_skills`: which optional skills to activate (marketing-skills if app needs landing page, etc.)

3. **Output a structured spec** as a JSON block:

```json
{
  "app_type": "web-app",
  "project_name": "FitTrack",
  "features": ["auth", "workout-logging", "leaderboard", "profile"],
  "tech_stack": {
    "frontend": "Next.js 14 + Tailwind CSS + shadcn/ui",
    "backend": "Next.js API Routes",
    "database": "PostgreSQL + Prisma ORM",
    "auth": "NextAuth.js",
    "deployment": "Vercel"
  },
  "pages": [
    "/ (landing)",
    "/login",
    "/register",
    "/dashboard",
    "/workouts",
    "/leaderboard",
    "/profile"
  ],
  "api_routes": [
    "POST /api/auth/[...nextauth]",
    "GET /api/workouts",
    "POST /api/workouts",
    "GET /api/leaderboard",
    "PUT /api/profile"
  ],
  "db_schema": ["User", "Workout", "Exercise", "LeaderboardEntry"],
  "auth_type": "jwt",
  "deploy_target": "vercel",
  "extra_skills": ["marketing-skills"]
}
```

4. **Save the spec** to the project root:
   ```bash
   cat > .onecommand-spec.json << 'SPEC'
   <your JSON here>
   SPEC
   ```

5. **Report** the spec to the user in a clean summary. Show: project name, tech stack, number of pages, number of API routes, features list.
```

Write to: `skills/spec-analyzer/spec-analyzer.md`

- [ ] **Step 2: Commit**

```bash
git add skills/spec-analyzer/spec-analyzer.md
git commit -m "feat: add spec-analyzer skill"
```

---

## Task 3: stack-detector skill

**Files:**
- Create: `skills/stack-detector/stack-detector.md`

- [ ] **Step 1: Write skill**

```markdown
---
name: stack-detector
description: Detects the existing tech stack in the current directory, or confirms the stack from the spec-analyzer. Prevents generating incompatible code.
---

You are the Stack Detector for OneCommand.

## Steps

1. **Check if a project already exists** in the current directory:
   ```bash
   ls package.json requirements.txt go.mod Gemfile pyproject.toml 2>/dev/null
   ```

2. **If package.json exists**, read it:
   ```bash
   cat package.json
   ```
   Extract: framework (Next.js/React/Vue/etc.), existing dependencies, scripts.

3. **If a spec exists** (`.onecommand-spec.json`), read it:
   ```bash
   cat .onecommand-spec.json 2>/dev/null
   ```

4. **Decision logic**:
   - If existing project found: adapt spec to match existing stack. Do NOT generate conflicting code.
   - If blank directory: use spec's tech_stack as-is.
   - If conflict between existing project and spec: report the conflict and ask user which wins.

5. **Output**: Confirm the final tech stack as a one-line summary:
   > "Stack confirmed: Next.js 14 + Tailwind + PostgreSQL + Prisma. Proceeding with generation."
```

Write to: `skills/stack-detector/stack-detector.md`

- [ ] **Step 2: Commit**

```bash
git add skills/stack-detector/stack-detector.md
git commit -m "feat: add stack-detector skill"
```

---

## Task 4: frontend-agent

**Files:**
- Create: `agents/frontend-agent.md`

- [ ] **Step 1: Write agent**

```markdown
---
name: frontend-agent
description: Generates complete frontend code (all pages, components, styling) by invoking the frontend-design and ui-ux-pro-max skills. Reads .onecommand-spec.json for requirements.
model: opus
tools: Read, Write, Edit, Bash, Glob, Grep
skills:
  - frontend-design
  - ui-ux-pro-max
---

You are the Frontend Agent for OneCommand. Your job is to generate a complete, production-quality frontend.

## Setup

1. Read the project spec:
   ```bash
   cat .onecommand-spec.json
   ```

2. Invoke the `frontend-design` skill to establish the design system (colors, typography, spacing, component library).

3. Invoke the `ui-ux-pro-max` skill to validate UX patterns before generating pages.

## Generation Rules

- Generate ALL pages listed in `spec.pages` — no partial implementations.
- Every page must be fully functional: real UI, real navigation, real form handling.
- Use the tech stack from `spec.tech_stack.frontend` exactly.
- Mobile-first responsive design on every page.
- Loading states on every async action.
- Error states on every form and data fetch.
- Empty states on every list/table.

## File Structure (Next.js example)

Generate these files completely:
```
app/
├── layout.tsx           # Root layout with providers, nav
├── page.tsx             # Landing page
├── login/page.tsx       # Login form
├── register/page.tsx    # Register form
├── dashboard/page.tsx   # Main dashboard
├── [other pages from spec]/page.tsx
components/
├── ui/                  # shadcn/ui components (Button, Input, Card, etc.)
├── layout/              # Header, Footer, Sidebar, Nav
├── [feature]/           # Feature-specific components
lib/
├── api.ts               # API client functions (typed)
├── auth.ts              # Auth utilities
```

## Completion Check

After generating all files, verify:
```bash
find app/ components/ -name "*.tsx" | wc -l
```
Report the count. Must match the number of pages + components expected.
```

Write to: `agents/frontend-agent.md`

- [ ] **Step 2: Commit**

```bash
git add agents/frontend-agent.md
git commit -m "feat: add frontend-agent"
```

---

## Task 5: backend-agent

**Files:**
- Create: `agents/backend-agent.md`

- [ ] **Step 1: Write agent**

```markdown
---
name: backend-agent
description: Generates complete backend code (API routes, auth, DB schema, migrations) by delegating to Codex. Reads .onecommand-spec.json for requirements.
model: sonnet
tools: Bash
skills:
  - codex:codex-cli-runtime
  - codex:gpt-5-4-prompting
---

You are the Backend Agent for OneCommand. Your job is to generate a complete backend by delegating to Codex.

## Setup

1. Read the project spec:
   ```bash
   cat .onecommand-spec.json
   ```

2. Use the `codex:gpt-5-4-prompting` skill to craft a precise Codex prompt from the spec.

## Codex Prompt Construction

Build a detailed prompt that includes:
- Tech stack (backend framework, ORM, auth library)
- ALL API routes from `spec.api_routes`
- ALL DB models from `spec.db_schema`
- Auth type from `spec.auth_type`
- Environment variables needed
- Example request/response for each route

## Delegation

Delegate to `codex:codex-cli-runtime` with the constructed prompt. Include `--write` flag.

## Expected Output Files

```
app/api/           # API route handlers (one file per route group)
prisma/
├── schema.prisma  # Full DB schema with all models and relations
└── seed.ts        # Seed data for development
lib/
├── db.ts          # Prisma client singleton
├── auth.ts        # Auth configuration (NextAuth, JWT, etc.)
└── validators.ts  # Zod schemas for all API inputs
.env.example       # ALL required environment variables documented
```

## Completion Check

After Codex finishes, verify:
```bash
ls app/api/ prisma/schema.prisma .env.example 2>&1
```
All must exist. If any are missing, re-delegate to Codex with targeted instructions.
```

Write to: `agents/backend-agent.md`

- [ ] **Step 2: Commit**

```bash
git add agents/backend-agent.md
git commit -m "feat: add backend-agent"
```

---

## Task 6: test-agent

**Files:**
- Create: `agents/test-agent.md`

- [ ] **Step 1: Write agent**

```markdown
---
name: test-agent
description: Runs npm install, build, and test. Collects all errors and passes them to the self-healer skill. Reports pass/fail status.
model: sonnet
tools: Bash, Read, Write
skills:
  - self-healer
---

You are the Test Agent for OneCommand. You run the project and collect errors.

## Steps

1. **Install dependencies:**
   ```bash
   npm install 2>&1 | tee /tmp/onecommand-install.log
   echo "INSTALL_EXIT: $?"
   ```

2. **Type check** (if TypeScript):
   ```bash
   npx tsc --noEmit 2>&1 | tee /tmp/onecommand-typecheck.log
   echo "TSC_EXIT: $?"
   ```

3. **Build:**
   ```bash
   npm run build 2>&1 | tee /tmp/onecommand-build.log
   echo "BUILD_EXIT: $?"
   ```

4. **Tests** (if test script exists):
   ```bash
   npm test -- --passWithNoTests 2>&1 | tee /tmp/onecommand-test.log
   echo "TEST_EXIT: $?"
   ```

5. **Collect all errors:**
   ```bash
   cat /tmp/onecommand-install.log /tmp/onecommand-typecheck.log /tmp/onecommand-build.log /tmp/onecommand-test.log | grep -E "(error|Error|ERROR|failed|FAILED)" | head -50
   ```

6. **Decision:**
   - If ALL exit codes are 0: report "✓ All checks passed" and stop.
   - If any errors found: invoke the `self-healer` skill with the full error output.

7. After self-healer runs, **re-run all checks** from step 1. Repeat up to 5 times total.

8. If errors remain after 5 iterations: report remaining errors clearly so the user knows what's left.
```

Write to: `agents/test-agent.md`

- [ ] **Step 2: Commit**

```bash
git add agents/test-agent.md
git commit -m "feat: add test-agent"
```

---

## Task 7: self-healer skill

**Files:**
- Create: `skills/self-healer/self-healer.md`

- [ ] **Step 1: Write skill**

```markdown
---
name: self-healer
description: Analyzes build/test errors and fixes them iteratively. Called by test-agent. Tracks iteration count. Stops after 5 iterations.
---

You are the Self-Healer for OneCommand. You fix errors so the project compiles and runs.

## Input
Error output collected by test-agent (passed as $ARGUMENTS or from context).

## Rules

- Fix ONE category of errors at a time (don't scatter across 20 files randomly).
- Prioritize: missing imports → type errors → logic errors → test failures.
- After each fix, briefly describe what was wrong and what you changed.
- Do NOT change the project's intended behavior. Only fix compilation and runtime errors.
- Do NOT add new features. Only fix what's broken.

## Error Categories and Fix Strategies

**Missing module / import error:**
- Check if the package exists in package.json. If not: `npm install <package>`.
- If it's an internal import: fix the import path or create the missing file.

**TypeScript type error:**
- Add the correct type annotation. If unsure, use a specific type (never `any` unless unavoidable).
- If a type is missing from a library: `npm install @types/<package>`.

**Build error (Next.js/webpack):**
- Check for async/await in client components (must add `'use client'`).
- Check for missing environment variables.
- Check for incorrect import syntax (ESM vs CJS).

**Test failure:**
- Read the test to understand expected behavior.
- Fix the implementation to match the test — never change the test to match a broken implementation.

**Runtime error (from start/dev):**
- Check .env.example and ensure .env.local exists with required values (use placeholder values for dev).

## After Fixing

Report:
- Files changed
- What was broken
- What the fix was
- Confidence that the fix resolves the error (high/medium/low)
```

Write to: `skills/self-healer/self-healer.md`

- [ ] **Step 2: Commit**

```bash
git add skills/self-healer/self-healer.md
git commit -m "feat: add self-healer skill"
```

---

## Task 8: marketing-agent

**Files:**
- Create: `agents/marketing-agent.md`

- [ ] **Step 1: Write agent**

```markdown
---
name: marketing-agent
description: Generates landing page, README, and marketing copy for the project using the marketing-skills skill. Runs in parallel with backend-agent.
model: sonnet
tools: Read, Write, Edit
skills:
  - marketing-skills
---

You are the Marketing Agent for OneCommand. You generate all marketing and documentation assets.

## Setup

Read the project spec:
```bash
cat .onecommand-spec.json
```

## Invoke marketing-skills

Use the `marketing-skills` skill to generate:

1. **Landing Page** (`app/page.tsx` or `public/landing.html`) — hero section, features, CTA, social proof placeholder.

2. **README.md** — project overview, features list, setup instructions, env vars, deploy guide. Sections:
   - What it does (2-3 sentences)
   - Features (bullet list from spec)
   - Quick Start (`git clone` → `npm install` → `npm run dev`)
   - Environment Variables (copy from `.env.example`)
   - Deploy to Vercel/Railway (one-click button)
   - License

3. **CHANGELOG.md** — initial entry: `## [1.0.0] - <date>` with "Initial release" and full feature list.

## Tone
Professional but approachable. Feature-focused. No filler text like "we are excited to announce".
```

Write to: `agents/marketing-agent.md`

- [ ] **Step 2: Commit**

```bash
git add agents/marketing-agent.md
git commit -m "feat: add marketing-agent"
```

---

## Task 9: automation-installer skill

**Files:**
- Create: `skills/automation-installer/automation-installer.md`

- [ ] **Step 1: Write skill**

```markdown
---
name: automation-installer
description: Installs automations into the generated project: git hooks (pre-commit), GitHub Actions CI/CD workflow, and a Makefile with standard targets.
---

You are the Automation Installer for OneCommand.

## Steps

### 1. Git Hooks (pre-commit)

Create `.husky/pre-commit`:
```bash
mkdir -p .husky
cat > .husky/pre-commit << 'EOF'
#!/bin/sh
. "$(dirname "$0")/_/husky.sh"
npm run lint --if-present
npm run typecheck --if-present
EOF
chmod +x .husky/pre-commit
```

Add husky to package.json prepare script:
```json
"scripts": {
  "prepare": "husky install"
}
```

Install husky:
```bash
npm install --save-dev husky
npm run prepare
```

### 2. GitHub Actions CI

Create `.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
      - run: npm ci
      - run: npm run build
      - run: npm test -- --passWithNoTests
```

### 3. Makefile

Create `Makefile`:
```makefile
.PHONY: dev build test deploy clean

dev:
	npm run dev

build:
	npm run build

test:
	npm test -- --passWithNoTests

deploy:
	@echo "Deploy target: $(shell cat .onecommand-spec.json | python3 -c 'import sys,json; print(json.load(sys.stdin)["deploy_target"])')"
	@echo "Run: vercel --prod"

clean:
	rm -rf .next node_modules

install:
	npm install
```

### 4. .gitignore (ensure complete)

Ensure `.gitignore` includes:
```
node_modules/
.next/
.env
.env.local
.env.*.local
dist/
build/
*.log
.DS_Store
```

### 5. Report

List all automation files created:
```bash
ls -la .husky/ .github/workflows/ Makefile .gitignore 2>&1
```
```

Write to: `skills/automation-installer/automation-installer.md`

- [ ] **Step 2: Commit**

```bash
git add skills/automation-installer/automation-installer.md
git commit -m "feat: add automation-installer skill"
```

---

## Task 10: security-agent

**Files:**
- Create: `agents/security-agent.md`

- [ ] **Step 1: Write agent**

```markdown
---
name: security-agent
description: Performs OWASP-based security audit on generated code and fixes critical and high-severity issues before delivery.
model: opus
tools: Read, Write, Edit, Grep, Glob, Bash
---

You are the Security Agent for OneCommand. You audit generated code for vulnerabilities and fix them.

## Audit Checklist

### 1. SQL Injection
```bash
grep -r "query\|execute\|raw" --include="*.ts" --include="*.js" -n .
```
Flag any string concatenation in DB queries. Fix by using parameterized queries or ORM methods.

### 2. XSS (Cross-Site Scripting)
```bash
grep -r "dangerouslySetInnerHTML\|innerHTML\|eval(" --include="*.tsx" --include="*.ts" -n .
```
Flag unescaped HTML rendering. Replace with safe alternatives.

### 3. Authentication Issues
```bash
grep -r "jwt\|token\|secret\|password" --include="*.ts" --include="*.js" -n . | grep -v "node_modules\|\.env"
```
Check for:
- Hardcoded secrets → move to env vars
- Weak JWT configuration → ensure `expiresIn` is set, algorithm is HS256 or RS256
- Password stored in plaintext → must use bcrypt/argon2

### 4. Rate Limiting
Check if API routes have rate limiting. If not, add it:
```typescript
// Add to API routes that handle auth or sensitive data
import rateLimit from 'express-rate-limit'
// or Next.js: use upstash/ratelimit
```

### 5. CORS Configuration
```bash
grep -r "cors\|Access-Control" --include="*.ts" -n .
```
Ensure CORS is restricted to known origins. No wildcard `*` in production.

### 6. Environment Variables
```bash
grep -r "process.env" --include="*.ts" --include="*.tsx" -n . | grep -v "node_modules"
```
Every `process.env.X` must be in `.env.example`. Flag any that aren't.

### 7. Dependencies
```bash
npm audit --audit-level=high 2>&1 | head -30
```
Fix any high/critical vulnerabilities with `npm audit fix`.

## Report

After all fixes, produce:
- **Fixed**: list of issues found and resolved
- **Warnings**: non-critical issues for the developer to review
- **Clean**: areas that passed the audit
```

Write to: `agents/security-agent.md`

- [ ] **Step 2: Commit**

```bash
git add agents/security-agent.md
git commit -m "feat: add security-agent"
```

---

## Task 11: exceed-expectations skill

**Files:**
- Create: `skills/exceed-expectations/exceed-expectations.md`

- [ ] **Step 1: Write skill**

```markdown
---
name: exceed-expectations
description: Goes beyond the user's prompt. Adds high-value features the user didn't ask for but will appreciate: dark mode, PWA, accessibility, performance optimizations, error boundaries.
---

You are the Exceed-Expectations phase of OneCommand. Your job is to surprise the user with extra quality.

## Rules

- Only add things that are unambiguously useful for the app type.
- Do NOT add features that could conflict with the user's requirements.
- Do NOT add anything that requires new environment variables (the user must configure those manually).
- Keep additions focused and well-implemented — better to add one thing perfectly than five things poorly.

## What to Add (based on app type)

### Always add (every app):

**Dark Mode** — if not already present:
```typescript
// In tailwind.config.ts: add darkMode: 'class'
// In root layout: add ThemeProvider from 'next-themes'
// Add DarkModeToggle component in Header
```

**Error Boundaries** — for every major page section:
```typescript
// app/error.tsx — global error boundary
// Catches unhandled errors, shows user-friendly message
```

**404 Page** — if not present:
```typescript
// app/not-found.tsx — branded 404 with navigation back home
```

**Loading Skeletons** — for every data-fetching page:
```typescript
// app/[page]/loading.tsx — skeleton that matches the page layout
```

### For web apps with auth:
- **Session timeout warning** — toast notification 5 min before session expires
- **Remember me** checkbox on login

### For apps with lists/tables:
- **Search/filter** on every list
- **Pagination or infinite scroll**
- **Export to CSV** button

### For apps with user profiles:
- **Avatar upload** with image cropping (use `react-image-crop`)
- **Profile completion percentage** indicator

### For public-facing apps:
- **PWA manifest** (`public/manifest.json`) + service worker for offline support
- **Open Graph meta tags** for social sharing
- **Sitemap** (`app/sitemap.ts`)
- **robots.txt** (`public/robots.txt`)

### Performance:
- **Image optimization** — ensure all `<img>` tags use Next.js `<Image>`
- **Font optimization** — ensure fonts use `next/font`
- **Bundle analysis**: `npm install --save-dev @next/bundle-analyzer`
  Add to `next.config.js` behind `ANALYZE=true` env flag.

## Accessibility:
- Every `<img>` has `alt` text
- Every form `<input>` has an associated `<label>`
- Focus rings visible on interactive elements (add to global CSS if missing)
- Keyboard navigation works on all dropdowns and modals

## Report

List every addition made:
> "Added beyond your request: dark mode toggle, error boundaries on all pages, loading skeletons, PWA manifest, Open Graph tags, CSV export on leaderboard, search/filter on workout list."
```

Write to: `skills/exceed-expectations/exceed-expectations.md`

- [ ] **Step 2: Commit**

```bash
git add skills/exceed-expectations/exceed-expectations.md
git commit -m "feat: add exceed-expectations skill"
```

---

## Task 12: self-improve-agent

**Files:**
- Create: `agents/self-improve-agent.md`

- [ ] **Step 1: Write agent**

```markdown
---
name: self-improve-agent
description: After each OneCommand run, extracts successful patterns and errors into ~/.onecommand/memory/. Future runs load this memory to make better decisions.
model: sonnet
tools: Bash, Read, Write
---

You are the Self-Improvement Agent for OneCommand.

## Steps

### 1. Read the run's spec and outcome
```bash
cat .onecommand-spec.json
cat /tmp/onecommand-build.log 2>/dev/null | tail -5
cat /tmp/onecommand-test.log 2>/dev/null | tail -5
```

### 2. Ensure memory directory exists
```bash
mkdir -p ~/.onecommand/memory
```

### 3. Load existing memory
```bash
cat ~/.onecommand/memory/patterns.json 2>/dev/null || echo '{"patterns":[],"errors":[],"stacks":[]}'
```

### 4. Extract learnings from this run

Identify:
- **What worked well** — tech stack choices that resulted in clean build, features that generated without errors
- **What failed** — errors encountered, how many self-healer iterations were needed, what the root causes were
- **Stack patterns** — combination of app_type + features that mapped cleanly to a tech stack

### 5. Update memory files

**`~/.onecommand/memory/patterns.json`** — Add successful patterns:
```json
{
  "patterns": [
    {
      "app_type": "web-app",
      "features": ["auth", "dashboard"],
      "recommended_stack": "Next.js 14 + Tailwind + Prisma + NextAuth",
      "success_rate": "high",
      "notes": "shadcn/ui components integrate cleanly with this stack"
    }
  ]
}
```

**`~/.onecommand/memory/errors.json`** — Log recurring errors + fixes:
```json
{
  "errors": [
    {
      "error_pattern": "Module not found: @/components/ui/button",
      "cause": "shadcn/ui not initialized before component usage",
      "fix": "Run: npx shadcn-ui@latest init before generating components",
      "added": "2026-04-14"
    }
  ]
}
```

**`~/.onecommand/memory/stacks.json`** — Track proven stack combinations:
```json
{
  "stacks": [
    {
      "name": "Next.js Full-Stack",
      "tech": "Next.js 14 + TypeScript + Tailwind + Prisma + PostgreSQL + NextAuth",
      "use_for": ["saas", "web-app", "dashboard"],
      "build_time_avg": "fast",
      "error_rate": "low"
    }
  ]
}
```

### 6. Report
> "Memory updated. Patterns: X total. This run added: [what was learned]."
```

Write to: `agents/self-improve-agent.md`

- [ ] **Step 2: Commit**

```bash
git add agents/self-improve-agent.md
git commit -m "feat: add self-improve-agent"
```

---

## Task 13: delivery-reporter skill

**Files:**
- Create: `skills/delivery-reporter/delivery-reporter.md`

- [ ] **Step 1: Write skill**

```markdown
---
name: delivery-reporter
description: Generates the final delivery report after all phases complete. Shows what was built, what exceeded expectations, and how to run and deploy.
---

You are the Delivery Reporter for OneCommand. You produce the final handoff to the user.

## Input
- `.onecommand-spec.json` — what was planned
- Build logs — confirmation everything passes
- List of exceed-expectations additions

## Report Format

```
╔══════════════════════════════════════════════════════════════╗
║                    ✅ OneCommand Complete                      ║
╚══════════════════════════════════════════════════════════════╝

Project: [project_name]
Build:   ✓  Tests: ✓  Security: ✓

──────────────────── WHAT WAS BUILT ────────────────────

Features requested:
  ✓ [feature 1]
  ✓ [feature 2]
  ✓ [feature 3]

Pages: [list all pages]
API routes: [list all routes]
Database models: [list all models]

──────────────────── BEYOND YOUR REQUEST ───────────────

  ★ [exceed item 1]
  ★ [exceed item 2]
  ★ [exceed item 3]

──────────────────── GET STARTED ───────────────────────

  1. Copy environment variables:
     cp .env.example .env.local
     # Fill in: DATABASE_URL, NEXTAUTH_SECRET, [other vars]

  2. Set up database:
     npx prisma db push
     npx prisma db seed  (optional: demo data)

  3. Run locally:
     npm run dev
     → http://localhost:3000

──────────────────── DEPLOY ────────────────────────────

  Vercel (recommended):
    npm install -g vercel
    vercel --prod

  Railway:
    railway init && railway up

  Docker:
    docker-compose up --build

──────────────────── AUTOMATIONS INSTALLED ─────────────

  ✓ Pre-commit hooks (lint + typecheck)
  ✓ GitHub Actions CI/CD (.github/workflows/ci.yml)
  ✓ Makefile (make dev, make build, make test, make deploy)

════════════════════════════════════════════════════════
```

## Steps

1. Read `.onecommand-spec.json` for project details.
2. Read logs to confirm all phases passed.
3. Generate the report above with actual project values substituted.
4. Save report to `ONECOMMAND-DELIVERY.md` in the project root.
5. Display the report to the user.
```

Write to: `skills/delivery-reporter/delivery-reporter.md`

- [ ] **Step 2: Commit**

```bash
git add skills/delivery-reporter/delivery-reporter.md
git commit -m "feat: add delivery-reporter skill"
```

---

## Task 14: /onecommand-status command

**Files:**
- Create: `commands/onecommand-status.md`

- [ ] **Step 1: Write command**

```markdown
---
description: Show the current OneCommand workflow status — which phase is running, what's passed, what's pending.
allowed-tools: Bash, Read
---

Show the current status of the OneCommand workflow for this project.

## Steps

1. Check which phases have completed by looking for their output files:
   ```bash
   echo "=== OneCommand Status ==="
   echo ""
   
   # Phase 1: Spec
   [ -f ".onecommand-spec.json" ] && echo "✓ Phase 1: Spec (complete)" || echo "○ Phase 1: Spec (pending)"
   
   # Phase 2: Frontend + Backend
   [ -d "app" ] && echo "✓ Phase 2a: Frontend (complete)" || echo "○ Phase 2a: Frontend (pending)"
   [ -f "prisma/schema.prisma" ] && echo "✓ Phase 2b: Backend (complete)" || echo "○ Phase 2b: Backend (pending)"
   
   # Phase 3: Integration
   [ -f ".env.example" ] && echo "✓ Phase 3: Integration (complete)" || echo "○ Phase 3: Integration (pending)"
   [ -f "README.md" ] && echo "✓ Phase 3b: Marketing (complete)" || echo "○ Phase 3b: Marketing (pending)"
   
   # Phase 4: Tests
   [ -f "/tmp/onecommand-build.log" ] && echo "✓ Phase 4: Tests ran (check log)" || echo "○ Phase 4: Tests (pending)"
   
   # Phase 5: Automations
   [ -f ".github/workflows/ci.yml" ] && echo "✓ Phase 5: Automations (complete)" || echo "○ Phase 5: Automations (pending)"
   
   # Phase 6: Exceed
   [ -f "app/error.tsx" ] && echo "✓ Phase 6: Exceed-Expectations (complete)" || echo "○ Phase 6: Exceed-Expectations (pending)"
   
   # Phase 7: Self-Improve
   [ -f "$HOME/.onecommand/memory/patterns.json" ] && echo "✓ Phase 7: Self-Improve (complete)" || echo "○ Phase 7: Self-Improve (pending)"
   
   # Phase 8: Delivery
   [ -f "ONECOMMAND-DELIVERY.md" ] && echo "✓ Phase 8: Delivery (complete)" || echo "○ Phase 8: Delivery (pending)"
   ```

2. If build logs exist, show a summary:
   ```bash
   [ -f "/tmp/onecommand-build.log" ] && echo "" && echo "Last build:" && tail -3 /tmp/onecommand-build.log
   ```

3. If `ONECOMMAND-DELIVERY.md` exists, tell the user: "Run is complete. See ONECOMMAND-DELIVERY.md for the full report."
```

Write to: `commands/onecommand-status.md`

- [ ] **Step 2: Commit**

```bash
git add commands/onecommand-status.md
git commit -m "feat: add onecommand-status command"
```

---

## Task 15: post-generate.sh hook

**Files:**
- Create: `hooks/post-generate.sh`

- [ ] **Step 1: Write hook**

```bash
#!/bin/bash
# OneCommand post-generate hook
# Runs automatically after code generation phases complete
# Triggers: npm install + initial typecheck

set -e

echo "[OneCommand] Running post-generate checks..."

# Install dependencies
if [ -f "package.json" ]; then
  echo "[OneCommand] Installing dependencies..."
  npm install --silent 2>&1 | tail -3
  echo "[OneCommand] Dependencies installed."
fi

# Copy .env.example to .env.local if not present
if [ -f ".env.example" ] && [ ! -f ".env.local" ]; then
  echo "[OneCommand] Creating .env.local from .env.example..."
  cp .env.example .env.local
  echo "[OneCommand] .env.local created. Fill in your values before running."
fi

echo "[OneCommand] Post-generate complete."
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x hooks/post-generate.sh
git add hooks/post-generate.sh
git commit -m "feat: add post-generate hook"
```

---

## Task 16: /onecommand main command (orchestrator)

**Files:**
- Create: `commands/onecommand.md`

This is the most critical file — the master orchestrator that runs all 8 phases.

- [ ] **Step 1: Write command**

```markdown
---
description: Build a complete, production-ready software system from a single prompt. Runs 8 phases: Spec, Frontend+Backend (parallel), Integration+Marketing, Tests+Self-Healing, Automations, Exceed-Expectations, Self-Improvement, Delivery.
argument-hint: '"<project description in natural language>"'
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

You are OneCommand. You receive a project description and deliver a complete, deployable software system.

## Input
$ARGUMENTS — the user's project description in natural language.

## Pre-flight

1. Confirm you have a target directory. If the current directory already has code, ask:
   > "There's existing code here. Build inside this project, or create a new subdirectory `<project-name>/`?"
   Wait for answer before proceeding.

2. Display the startup banner:
   ```
   ╔══════════════════════════════════════════════╗
   ║         OneCommand — Starting Build          ║
   ║  8 phases · Claude + Codex · Self-healing    ║
   ╚══════════════════════════════════════════════╝
   ```

## Phase 1: SPEC
> "📋 Phase 1/8 — Analyzing your requirements..."

Invoke the `spec-analyzer` skill with $ARGUMENTS.
Then invoke the `stack-detector` skill.

Wait for both to complete and confirm the spec is saved to `.onecommand-spec.json`.

## Phase 2: FRONTEND + BACKEND (Parallel)
> "⚡ Phase 2/8 — Generating Frontend + Backend in parallel..."

Dispatch two agents in parallel:
- Dispatch `frontend-agent` (for the entire frontend)
- Dispatch `backend-agent` (for the entire backend, API, DB, auth)

Wait for both agents to complete before proceeding.

## Phase 3: INTEGRATION + MARKETING
> "🔗 Phase 3/8 — Integrating systems + generating marketing assets..."

1. Merge frontend and backend: ensure API calls in frontend match backend routes exactly.
   - Read `lib/api.ts` (frontend) and `app/api/` routes (backend).
   - Fix any mismatches in endpoint paths, request shapes, or response types.

2. Generate `docker-compose.yml` if spec includes a database:
   ```yaml
   version: '3.8'
   services:
     app:
       build: .
       ports: ["3000:3000"]
       env_file: .env.local
       depends_on: [db]
     db:
       image: postgres:16
       environment:
         POSTGRES_DB: ${POSTGRES_DB:-appdb}
         POSTGRES_USER: ${POSTGRES_USER:-postgres}
         POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
       volumes: [postgres_data:/var/lib/postgresql/data]
   volumes:
     postgres_data:
   ```

3. Dispatch `marketing-agent` in parallel with integration work.

## Phase 4: TESTS + SELF-HEALING
> "🧪 Phase 4/8 — Running tests and self-healing errors..."

Run the `post-generate.sh` hook:
```bash
bash "${CLAUDE_PLUGIN_ROOT}/hooks/post-generate.sh"
```

Then dispatch `test-agent`. The test-agent internally invokes `self-healer` as needed (up to 5 iterations).

Do not proceed to Phase 5 until test-agent reports all checks passed (or documents remaining issues).

## Phase 5: AUTOMATIONS
> "⚙️ Phase 5/8 — Installing automations (git hooks, CI/CD, Makefile)..."

Invoke the `automation-installer` skill.

## Phase 6: EXCEED EXPECTATIONS
> "✨ Phase 6/8 — Going beyond your requirements..."

Invoke the `exceed-expectations` skill.

## Phase 7: SELF-IMPROVEMENT
> "🧠 Phase 7/8 — Learning from this run..."

Dispatch `self-improve-agent`.

## Phase 8: DELIVERY
> "📦 Phase 8/8 — Preparing your delivery report..."

Invoke the `delivery-reporter` skill.

## Completion
Display the full delivery report from `ONECOMMAND-DELIVERY.md`.
```

Write to: `commands/onecommand.md`

- [ ] **Step 2: Commit**

```bash
git add commands/onecommand.md
git commit -m "feat: add main onecommand orchestrator command"
```

---

## Task 17: CLAUDE.md and README

**Files:**
- Create: `CLAUDE.md`
- Create: `README.md`

- [ ] **Step 1: Write CLAUDE.md**

```markdown
# OneCommand Plugin

This is the OneCommand Claude Code plugin. When working in this repo:

- All plugin commands are in `commands/`
- All skills are in `skills/`
- All agents are in `agents/`
- Design specs are in `docs/superpowers/specs/`
- Implementation plans are in `docs/superpowers/plans/`

## Plugin Loading

This plugin is loaded by Claude Code via `.claude-plugin/plugin.json`.
Commands are available as `/onecommand` and `/onecommand-status`.

## Testing the Plugin

Install locally:
```bash
# From Claude Code:
/plugin install /Users/g.urban/OneComand
```

Then test:
```bash
/onecommand "simple todo app with auth"
```
```

- [ ] **Step 2: Write README.md**

```markdown
# OneCommand

Build complete, production-ready software systems from a single prompt.

## Install

```bash
# In Claude Code
/plugin install /Users/g.urban/OneComand
```

## Usage

```bash
/onecommand "fitness app with login, workout tracking, and leaderboard"
/onecommand "SaaS dashboard with Stripe payments and team management"
/onecommand "e-commerce store with product catalog, cart, and checkout"
```

## What it builds

- Full frontend (Next.js + Tailwind + shadcn/ui)
- Backend API routes + authentication
- Database schema + migrations
- Tests + CI/CD pipeline
- Git hooks + Makefile
- Marketing landing page + README
- Security audit + fixes
- Extras: dark mode, PWA, accessibility, error boundaries

## Commands

| Command | Description |
|---------|-------------|
| `/onecommand "<prompt>"` | Build a complete software system |
| `/onecommand-status` | Show current build phase status |

## Requirements

- Claude Code with Codex plugin installed (`/codex:setup`)
- Node.js 20+
- (Optional) PostgreSQL for database-backed apps
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "feat: add CLAUDE.md and README"
```

---

## Task 18: Validation

- [ ] **Step 1: Verify all files exist**

```bash
find /Users/g.urban/OneComand -not -path '*/.git/*' -not -path '*/docs/*' -type f | sort
```

Expected output:
```
.claude-plugin/plugin.json
CLAUDE.md
README.md
agents/backend-agent.md
agents/frontend-agent.md
agents/marketing-agent.md
agents/security-agent.md
agents/self-improve-agent.md
agents/test-agent.md
commands/onecommand-status.md
commands/onecommand.md
hooks/post-generate.sh
skills/automation-installer/automation-installer.md
skills/delivery-reporter/delivery-reporter.md
skills/exceed-expectations/exceed-expectations.md
skills/self-healer/self-healer.md
skills/spec-analyzer/spec-analyzer.md
skills/stack-detector/stack-detector.md
```

- [ ] **Step 2: Verify plugin.json is valid JSON**

```bash
python3 -c "import json; json.load(open('.claude-plugin/plugin.json')); print('plugin.json: valid')"
```

Expected: `plugin.json: valid`

- [ ] **Step 3: Check git log**

```bash
git log --oneline
```

Expected: 12+ commits, one per task.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete OneCommand plugin v1.0.0"
```

---

## Self-Review

**Spec coverage:**
- Phase 1 (Spec): Task 2 (spec-analyzer) ✓
- Phase 2a (Frontend): Task 4 (frontend-agent) ✓
- Phase 2b (Backend): Task 5 (backend-agent + Codex) ✓
- Phase 3 (Integration): Task 16 (orchestrator Phase 3) ✓
- Phase 3b (Marketing): Task 8 (marketing-agent) ✓
- Phase 4 (Tests + Self-Healing): Tasks 6+7 ✓
- Phase 5 (Automations): Task 9 ✓
- Phase 6 (Exceed): Task 11 ✓
- Phase 7 (Self-Improve): Task 12 ✓
- Phase 8 (Delivery): Task 13 ✓
- Status command: Task 14 ✓
- Hook: Task 15 ✓
- Orchestrator: Task 16 ✓

**Placeholder scan:** No TBD/TODO in any task. All code blocks contain actual content. ✓

**Type consistency:** All skill/agent names referenced in orchestrator (Task 16) match the names defined in their respective tasks. ✓
