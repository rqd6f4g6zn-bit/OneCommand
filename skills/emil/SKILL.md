---
name: emil
description: Emil Kowalski's design-engineering skills in one place — UI polish, animation (build, review, audit, find opportunities, performance, vocabulary), Apple-style fluid motion, mobile web that feels native, worst-case data stress tests, prototyping variants, library picks, Sonner toasts, React Native/Expo motion and modern Swift. Use for any interface that should feel crafted, not generated, and whenever motion, interaction feel or UI polish is built or reviewed. /emil runs it directly.
---

You are the design-engineering layer of OneCommand, built on Emil Kowalski's skills (Vercel, Linear;
<https://github.com/emilkowalski/skills>, MIT licence — see `LICENSE` in this folder). The guides below
are his, unchanged; this file only routes to them. `oc-frontend-design` sets the brand (brief, typefaces,
palette); this skill sets how the interface *feels*: motion, interaction, polish, edge cases.

## Load the guide that fits the task

Every guide is `guides/<name>/GUIDE.md`, next to it the files it links (RECIPES.md, STANDARDS.md …).
A guide that says "use `animate`" or "see review-animations" means the guide of that name here.

| Task | Guide |
|---|---|
| Polish a UI, design decisions, "make it feel great" — **the main one, read it for every UI build** | `emil-design-eng` |
| Build an animation or transition (web) | `animate` (+ `RECIPES.md`) |
| Review motion code strictly (diff, component, PR) | `review-animations` (+ `STANDARDS.md`) |
| Audit all motion in a codebase, write fix plans | `improve-animations` (+ `AUDIT.md`, `PLAN-TEMPLATE.md`) |
| Find places that should animate — and those that must not | `find-animation-opportunities` |
| Janky / dropped frames, which property to animate, `will-change` | `animation-performance` (+ `CHEATSHEET.md`) |
| Name a motion effect precisely | `animation-vocabulary` |
| Gestures, springs, sheets, momentum, materials, typography — Apple's principles for the web | `apple-design` |
| Web app should feel native on a phone (100vh, tap highlight, zoom on input, safe areas …) | `mobile-native` |
| Stress-test a screen with worst-case data | `break-ui` (+ `CATALOG.md`) |
| Several real variants of a UI piece behind a picker | `prototype` (+ `PICKER.md`) — only when asked |
| Which library for numbers, OTP, charts, command menu, DnD, toasts … | `pick-ui-library` — only when asked |
| Toasts with Sonner | `ask-sonner` (+ `API.md`) |
| React Native / Expo motion | `animate-expo` (+ `RECIPES.md`) |
| Swift (iOS/macOS native code) | `write-swift` |

Read the guide with the Read tool before writing or judging code for that task; read the linked files
when the guide says so. Several tasks → several guides.

## Inside a OneCommand build

- **Phase 2 (frontend, mobile):** load `emil-design-eng` with `oc-frontend-design`; add `animate` for
  every transition you build, `mobile-native` for every web build that will be used on phones,
  `animate-expo` / `write-swift` for native targets.
- **Phase 6 (exceed expectations):** run `break-ui` on every list, table and card component with the demo
  data, `review-animations` on every component that moves, `animation-performance` on anything that
  animates on scroll or during load. Fix what they find — in the app's code, with the guides' exact values.
- Motion follows the design brief: the brief's personality decides how much moves (a notary's software
  moves less than a restaurant's website); these guides decide how it moves.
- `prefers-reduced-motion` is honoured everywhere (the guides show how).

## /emil

`/emil <what you want>` loads this skill directly — e.g. `/emil review the animations in components/`,
`/emil make the drawer feel native on iOS`, `/emil break the contacts table`, `/emil what is the
bouncy popover effect called`. Pick the guide from the table, then follow it.
