---
name: domain-blueprints
description: Domain knowledge as structured blueprints — products (CRM, shop, booking, helpdesk, projects, invoicing, phone assistant, website, recruiting, warehouse) and industries (notary, law firm, tax advisor, medical practice, property management, real-estate agency, trades, restaurant) — modules, entities, roles, pages and concrete acceptance criteria in three tiers (mvp, pro, enterprise). Lets a one-line prompt like "CRM auf höchstem Niveau" produce the full feature set a professional expects. Used by spec-analyzer in Phase 1.
---

You are the Domain Blueprint step of OneCommand. Users should not have to write long prompts: "ein CRM auf höchstem Niveau" must yield everything a professional means by a CRM — not a contact list with three fields.

The knowledge lives in `skills/domain-blueprints/blueprints/<id>.json`; `hooks/blueprint.py` turns it into a draft spec and later proves that the final spec still covers it.

## Available blueprints

```bash
python3 "$OC_ROOT/hooks/blueprint.py" list
```

Two kinds: a **product** blueprint describes what is built (CRM, shop, website …); an **industry** blueprint
describes a business (notary, practice, restaurant …) with its processes, duties, closed systems and look.

| id | Kind | System | Typical prompts |
|---|---|---|---|
| `crm` | product | contacts, companies, pipeline, activities, leads, reports, GDPR, automations | "CRM", "Kundenverwaltung", "wie HubSpot" |
| `shop` | product | catalogue, cart, checkout, orders, coupons, reviews | "Online-Shop", "Webshop" |
| `booking` | product | services, slots, booking, cancellation, calendar | "Terminbuchung", "Friseur" |
| `helpdesk` | product | tickets, replies, SLA, macros, knowledge base | "Ticketsystem", "Helpdesk" |
| `projects` | product | workspaces, board, comments, time tracking | "Projektmanagement", "wie Trello" |
| `invoicing` | product | §14 UStG, gap-free numbers, PDF, dunning, DATEV | "Rechnungsprogramm", "Faktura" |
| `phone-assistant` | product | AI phone support: telephony, voice, handover, call log | "Telefon-KI", "Voicebot" |
| `website` | product | corporate / premium website, motion, CMS, SEO, performance budget | "Webseite", "Landingpage", "100k" |
| `recruiting` | product | ATS: jobs, career page, pipeline, scorecards, deletion periods, works council | "Bewerbermanagement" |
| `warehouse` | product | articles, bins, goods in/out, picking by phone camera, inventory (§ 240 HGB), batches | "Lagerverwaltung", "Warenwirtschaft" |
| `notary` | industry | matters, conflict check (§ 3 BeurkG), 14-day draft rule, deed register, GNotKG, Vollzug, escrow, GwG | "Notariat", "Notar" |
| `law-firm` | industry | matters, conflict check, deadline control, RVG billing, beA handover, client money | "Anwaltskanzlei", "Kanzleisoftware" |
| `tax-advisor` | industry | clients, document exchange, filing deadlines, monthly close, StBVV, DATEV export | "Steuerberater", "Steuerkanzlei" |
| `medical-practice` | industry | online booking, anamnesis, check-in, recall, GOÄ/GOZ — no KV/TI (certification) | "Arztpraxis", "Physiotherapie" |
| `property-management` | industry | WEG + rentals: units, leases, BetrKV statement, owners' meeting, resolutions | "Hausverwaltung" |
| `real-estate-agency` | industry | listings, exposé, OpenImmo, matching, viewings, commission (§ 656c BGB), GwG | "Immobilienmakler" |
| `trades` | industry | inquiries, quotes, scheduling, mobile field app, acceptance, invoices, maintenance | "Handwerksbetrieb", "Elektriker" |
| `restaurant` | industry | reservations, floor plan, menu with allergens, QR ordering, kitchen display — POS/TSE stays certified | "Restaurant", "Gastronomie" |

**Combinations.** `detect` prints a plan:
- "Software für …" with an industry → the industry leads, product matches add their modules (`--with`):
  "Praxis-Software mit Telefon-KI" → `expand medical-practice --with phone-assistant`.
- A product named for an industry → the product leads, the industry gives look, duties and integrations
  (`--context`): "Webseite für unser Restaurant" → `expand website --context restaurant` (no kitchen display).
`check` covers every `--with` blueprint like the primary one.

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
   No match → **research the domain** and write `domain_brief` into the spec (`blueprint.py brief` prints the
   template; `check` fails until it is complete). An unknown industry is never guessed from three words.

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

## What a blueprint carries besides modules

- `design` — the industry's design direction (personality, typefaces, palette, density, signature ideas,
  references, what looks cheap there). `expand` puts it into the spec as `design_direction`; the frontend
  agent's design brief starts from it.
- `compliance` — legal and professional duties with their source (§ …), per tier. The delivery report lists
  how each one is supported.
- `integrations` — `connectable`, `export_only`, `not_possible`: honest about closed official systems
  (notaries' archive, KV billing, beA, TSE cash registers). Build export/handover for those, never a fake
  connection.

New blueprint: add the JSON file — `tests/test_blueprint.py` validates the schema (design included) and every
tier expansion against the spec, acceptance and tour validators.

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
