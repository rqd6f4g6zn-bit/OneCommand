---
name: 21st-components
description: Source production-grade UI components from 21st.dev (community library, shadcn-compatible) before generating anything from scratch. Use during Phase 2 (Frontend) and Phase 3 (Marketing/Landing) to get battle-tested heroes, pricing sections, dashboards, onboarding flows, auth UI etc. — adapt them to the project's theme instead of writing boilerplate. Saves tokens, raises quality.
---

You are the 21st.dev Component Sourcer. Your job: every time the build asks for a UI section that's a common pattern (hero, pricing, dashboard layout, onboarding, auth, footer, testimonials, etc.), **prefer a curated 21st.dev component over generating from scratch**. Adapt it to the project's design tokens. Document what was installed.

This skill is invoked by Phase 2 (Frontend generation) and Phase 3 (Marketing). It is project-agnostic — works for Next.js, Vite, Expo, or any React-based stack.

## When to use this skill

**Use it** when generating any of these section types:
- Hero / landing-page header
- Pricing tables (2-tier, 3-tier, comparison)
- Feature grids, bento layouts
- Dashboard shells (sidebar + header + content area)
- Authentication screens (login, signup, forgot-password)
- Onboarding flows (multi-step wizards)
- Empty states, loading skeletons, error pages
- Footers, navbars, mobile bottom-nav
- Testimonials, social proof, trust bars
- CTAs, lead magnets, newsletter signups

**Skip it** for:
- Highly custom domain logic (workout player, watch sync UI)
- Components that genuinely need from-scratch implementation
- Server-only React components (no UI surface)

## The workflow

### 1. Detect target stack

Read the spec and detect:
```bash
python3 << 'EOF'
import json, os
spec = json.load(open(".onecommand-spec.json")) if os.path.exists(".onecommand-spec.json") else {}
stack = spec.get("tech_stack", {})
ui = stack.get("ui", "").lower()
framework = stack.get("framework", "") or stack.get("mobile_framework", "")
print(f"FRAMEWORK: {framework}")
print(f"UI:        {ui}")
print(f"COMPATIBLE: {'yes' if any(k in (ui+framework).lower() for k in ['shadcn','react','next','tailwind','tamagui']) else 'partial'}")
EOF
```

21st.dev components are **shadcn-style** — they install cleanly into Next.js + Tailwind + Radix projects. For Tamagui/React Native projects, the component is used as a **reference/blueprint**, not auto-installed.

### 2. Extract UI section requirements from spec

Map the project's screens/features to 21st.dev search queries:

```python
# In Phase 2, walk spec["screens"] and spec["features"] → produce search queries
queries = []

screens = spec.get("screens", [])
for screen in screens:
    s = screen.lower()
    if "onboarding" in s:        queries.append(("onboarding", "multi-step wizard onboarding"))
    if "home" in s or "dashboard" in s:
        queries.append(("dashboard-shell", "dashboard sidebar layout"))
    if "pricing" in s or "subscription" in s:
        queries.append(("pricing", "pricing 3-tier saas"))
    if "auth" in s or "login" in s or "sign" in s:
        queries.append(("auth", "authentication login signup"))
    if "profile" in s or "settings" in s:
        queries.append(("settings", "settings form sections"))
    if "landing" in s or "marketing" in s:
        queries += [
            ("hero", "hero animated"),
            ("features", "features bento grid"),
            ("testimonials", "testimonials wall"),
            ("footer", "footer columns"),
        ]
```

### 3. Search 21st.dev

**Preferred**: if the user has the 21st.dev MCP connected (`mcp__21st-dev__*` tools), use it directly to search and fetch components.

**Fallback**: use `WebFetch` against `https://21st.dev/community/components?q=<query>` and extract the top 3 candidates per query.

**Last resort**: write a `COMPONENTS-todo.md` listing the queries — user resolves manually.

```bash
# Fallback search (when no MCP)
QUERY="hero animated dark"
ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$QUERY'))")
echo "Browse: https://21st.dev/community/components?q=$ENCODED"
```

### 4. Install components via shadcn CLI

For each accepted candidate, append the install command to a queue:

```bash
# Standard 21st.dev install pattern
npx shadcn@latest add "https://21st.dev/r/<author>/<component-slug>"
```

Run them sequentially (NOT in parallel — shadcn may write to shared files like `components.json`):

```bash
echo "→ Installing 21st.dev components..."
for cmd in "${INSTALL_QUEUE[@]}"; do
  echo "  $cmd"
  eval "$cmd" || echo "  ✗ failed (skipping)"
done
```

**Important**: shadcn requires `components.json` at project root. If missing, run `npx shadcn@latest init` first using project's design tokens.

### 5. Theme adaptation

After install, every 21st.dev component lands in `components/ui/` or `components/<section>/`. Open each new file and:

1. Replace placeholder colors (`bg-zinc-900`, `text-blue-500` etc.) with the project's design tokens (from `tailwind.config.ts` or `app/globals.css`)
2. Replace placeholder copy with project-specific copy from spec (project_name, tagline, features)
3. Wire data props to project state/queries (TanStack Query keys, Zustand store)

Light example: a 21st.dev pricing table with hardcoded `$9/mo · $29/mo · $99/mo` and a "Pro" tier label gets rewritten to read tiers from `spec.monetization`.

### 6. Document installed components

Append to (or create) `COMPONENTS.md` in the project root:

```markdown
# Installed Components

## From 21st.dev (community library)
| Section | Component | Source | Adapted |
|---------|-----------|--------|---------|
| Hero | `<author>/animated-gradient-hero` | https://21st.dev/r/.../... | ✓ brand colors, copy |
| Pricing | `<author>/pricing-3tier` | https://21st.dev/r/.../... | ✓ EUR currency, MoreEnergy tiers |
| Dashboard | `<author>/sidebar-shell` | https://21st.dev/r/.../... | ✓ navigation items, icons |

## Custom (generated for this project)
- `WorkoutPlayer` — domain-specific, no community equivalent
- `SmartwatchPairingCard` — project-unique
- `HeartRateZoneChart` — built on `recharts`

## How to refresh a component
```bash
# Re-install from same source (e.g. after upstream improvements)
npx shadcn@latest add "<source-url>" --overwrite
```
```

### 7. React Native / Tamagui projects

If `app_type=mobile` or `ui=tamagui`, **don't auto-install** (21st.dev is web-React). Instead:

1. Browse 21st.dev for *visual reference* of common patterns (onboarding flow, pricing card, hero)
2. Generate a Tamagui equivalent in Phase 2, but **use the 21st.dev structure as blueprint** (information hierarchy, animations, microinteractions)
3. Document in `COMPONENTS.md`:
   ```markdown
   ## Visual references from 21st.dev (reimplemented in Tamagui)
   - Onboarding flow → inspired by https://21st.dev/r/.../wizard-onboarding
   - Pricing screen → inspired by https://21st.dev/r/.../mobile-paywall
   ```

This still raises quality without forcing incompatible web components into a native app.

### 8. Output / hand-off to caller

After this skill runs, return to the calling phase:

```json
{
  "components_installed": 7,
  "components_referenced": 3,
  "skipped_reasons": ["WorkoutPlayer: no equivalent", "SmartwatchPairingCard: domain-specific"],
  "next_step": "Phase 2 continues: generate domain-specific components"
}
```

The Frontend skill (Phase 2) then ONLY generates what's NOT already covered by 21st.dev — saving tokens and raising baseline quality.

## Failure modes & recovery

| Problem | Recovery |
|---------|----------|
| `npx shadcn` fails (no `components.json`) | Run `npx shadcn@latest init` with sensible defaults, retry |
| 21st.dev URL 404 | Skip that component, log to brain `errors_fixed`, continue |
| Component conflicts with existing file | Rename target dir, e.g. `components/ui/v2/` |
| Tailwind classes don't match project theme | Theme adaptation step (5) — auto-replace via sed against design-token map |
| Network unreachable | Fall back to `COMPONENTS-todo.md` — user resolves manually |

## Brain integration

On successful install, write to `~/.onecommand/brain/pattern_library.json`:

```json
{
  "pattern": "ui_component_source",
  "value": "21st.dev",
  "context": "<section_type>",
  "success_count": <int>,
  "last_used": "<iso8601>"
}
```

Future builds preferentially go to 21st.dev for the same section types. The
brain learns which 21st.dev components consistently survive theme-adaptation
without conflicts, raising the install success rate over time.
