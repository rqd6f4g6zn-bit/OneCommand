---
name: domain-blueprints
description: Domain knowledge for common business systems (CRM, online shop, booking, helpdesk, project management, invoicing) as structured blueprints — modules, entities, roles, pages and concrete acceptance criteria in three tiers (mvp, pro, enterprise). Lets a one-line prompt like "CRM auf höchstem Niveau" produce the full feature set a professional expects. Used by spec-analyzer in Phase 1.
---

You are the Domain Blueprint step of OneCommand. Users should not have to write long prompts: "ein CRM auf höchstem Niveau" must yield everything a professional means by a CRM — not a contact list with three fields.

The knowledge lives in `skills/domain-blueprints/blueprints/<id>.json`; `hooks/blueprint.py` turns it into a draft spec and later proves that the final spec still covers it.

## Available blueprints

```bash
python3 "$OC_ROOT/hooks/blueprint.py" list
```

| id | System | Typical prompts |
|---|---|---|
| `crm` | CRM: contacts, companies, pipeline, activities, leads, reports, GDPR, automations | "CRM", "Kundenverwaltung", "Vertriebstool", "wie HubSpot" |
| `shop` | Online shop: catalogue, cart, checkout, orders, coupons, reviews | "Online-Shop", "Webshop", "E-Commerce" |
| `booking` | Appointment booking: services, slots, booking, cancellation, calendar | "Terminbuchung", "Friseur", "Praxis" |
| `helpdesk` | Ticket system: tickets, replies, SLA, macros, knowledge base | "Ticketsystem", "Support", "Helpdesk" |
| `projects` | Project & task management: workspaces, board, comments, time tracking | "Projektmanagement", "Kanban", "wie Trello" |
| `invoicing` | Invoices & quotes: §14 UStG, gap-free numbers, PDF, dunning, DATEV | "Rechnungsprogramm", "Faktura" |
| `phone-assistant` | AI phone support: telephony, AI disclosure, knowledge-base answers, actions, handover, call log, own intent model, GDPR | "Telefonassistent", "Voicebot", "KI am Telefon", "Support Telefon KI" |
| `website` | Corporate / premium website: design system, motion, hero video, case studies, CMS, i18n, SEO, GDPR, WCAG, performance budget | "Webseite", "Firmenwebseite", "Landingpage", "Premium-Website", "100k" |

## Tiers

Tiers are cumulative: `mvp` ⊂ `pro` ⊂ `enterprise`.

| Tier | Chosen when the prompt says | Scope |
|---|---|---|
| `mvp` | "MVP", "Prototyp", "erste Version", "einfaches CRM", "nur das Nötigste" | core modules only |
| `pro` | nothing about scope (default) | what a paying customer expects from a serious product |
| `enterprise` | "höchstes Niveau", "Enterprise", "wie Salesforce", "alle Funktionen", "auf max", "mandantenfähig", "Premium", "100k", "Agenturniveau" | everything incl. automation, API, SSO, multi-tenancy (website: page builder, films, careers, search) |

## Procedure (spec-analyzer, Phase 1)

1. **Detect**
   ```bash
   python3 "$OC_ROOT/hooks/blueprint.py" detect --prompt "$ARGUMENTS"
   ```
   No match → continue without a blueprint (spec-analyzer derives everything from the prompt).

2. **Expand** the best match into a draft spec. Pass modules the user explicitly does **not** want with a reason (their own words):
   ```bash
   python3 "$OC_ROOT/hooks/blueprint.py" expand crm --tier enterprise --project-name "<Name>" \
     --out .onecommand/blueprint-spec.json
   # e.g. --exclude "products-quotes=Nutzer: keine Angebote nötig"
   ```

3. **Adapt, don't shrink.** Write `.onecommand-spec.json` starting from the draft:
   - Add everything the prompt asks for beyond the blueprint (extra modules → own features + criteria).
   - Adjust wording, UI language and domain terms to the prompt (e.g. "Makler" instead of "Vertrieb").
   - Keep every blueprint criterion and its `"source"` tag — rewording is fine, deleting is not.
   - Keep `blueprint`, `module_features`, `entities`, `roles`, `non_functional`, `metrics`, `demo` — the build agents read them.
   - Keep every metric (definition, period, label); adjust labels to the domain words, keep the period in them.
   - Replace the draft demo e-mails with ones fitting the project name (e.g. `admin@novacrm.demo`), one per role.
   - The draft's acceptance-criterion ids are sequential; keep ids unique when you add more.

4. **Prove coverage** — must pass before Phase 2:
   ```bash
   python3 "$OC_ROOT/hooks/blueprint.py" check --spec .onecommand-spec.json
   python3 "$OC_ROOT/hooks/acceptance-report.py" validate --spec .onecommand-spec.json
   ```
   A missing module, a dropped criterion or a dropped metric fails the check. The fix is to restore it — or, only if the user asked for that, to exclude the module with their reason.

## What the build agents do with it

- `module_features` is the checklist per module for frontend-agent and backend-agent.
- `entities` (with fields) is the starting data model; `roles` drive authorization; every protected resource needs an ownership/role check that the acceptance criteria verify.
- `non_functional` lines are requirements, not suggestions (pagination, server-side prices, GoBD immutability …).
- `metrics` define every KPI once (definition, period, label, pages); the API contract serves them and the
  UI tour checks the labels — a dashboard and a report can no longer disagree silently.
- `demo` lists one login per role; the demo seed fills every view for each of them.
- `performance_budget` (website) is checked by the UI tour on every page; `media.videos` goes to the
  `video-producer` skill.
- The delivery report lists blueprint coverage: modules built, modules excluded and why.

## Large scopes

`enterprise` blueprints are big (CRM: 22 modules, 47 criteria, 6 metrics). Build module by module in the order of the blueprint (mvp modules first) and run the static gate after each group of modules, so errors surface early instead of all at once in Phase 4.
