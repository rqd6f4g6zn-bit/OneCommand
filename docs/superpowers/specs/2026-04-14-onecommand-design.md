# OneCommand — Design Spec
**Date:** 2026-04-14  
**Author:** USC Software UG  
**Status:** Approved

---

## Vision

Ein einziger Command `/onecommand "<prompt>"` liefert ein vollständig lauffähiges, deployables Softwaresystem — keine manuellen Fixes, keine halben Implementierungen. Das System übertrifft aktiv die Erwartungen des Nutzers durch eine Exceed-Expectations-Phase.

---

## Architektur-Überblick

```
/onecommand "fitness app mit login und leaderboard"
         │
         ▼
  Phase 1: SPEC          Claude analysiert Prompt → strukturierte Spec
         │
    ┌────┴────┐
    ▼         ▼
  Phase 2a    Phase 2b    PARALLEL
  FRONTEND    BACKEND     frontend-design + ui-ux-pro-max
  (Claude)    (Codex)     Codex für Bulk-Code-Generation
    └────┬────┘
         ▼
  Phase 3: INTEGRATION   Merge Frontend + Backend
         │               Env-Files, Config, Docker
         ├──────────────── Phase 3b: MARKETING (marketing-skills)
         │
         ▼
  Phase 4: TESTS         npm install + build + test
         │               Self-Healing Loop (max 5x)
         │
         ▼
  Phase 5: AUTOMATIONS   Git Hooks, Cron-Jobs, CI/CD-Config
         │
         ▼
  Phase 6: EXCEED        Security Audit, Perf, A11y,
                         "Surprise Features" (dark mode, PWA, etc.)
         │
         ▼
  Phase 7: SELF-IMPROVE  Lernt aus dem Run, speichert Patterns
         │               in ~/.onecommand/memory/
         ▼
  Phase 8: DELIVERY      Zusammenfassung, Deploy-Anleitung
```

---

## Plugin-Struktur

```
OneCommand/
├── .claude-plugin/
│   └── plugin.json
├── commands/
│   ├── onecommand.md
│   └── onecommand-status.md
├── skills/
│   ├── spec-analyzer/
│   │   └── spec-analyzer.md
│   ├── stack-detector/
│   │   └── stack-detector.md
│   ├── self-healer/
│   │   └── self-healer.md
│   ├── automation-installer/
│   │   └── automation-installer.md
│   ├── exceed-expectations/
│   │   └── exceed-expectations.md
│   └── delivery-reporter/
│       └── delivery-reporter.md
├── agents/
│   ├── frontend-agent.md
│   ├── backend-agent.md
│   ├── test-agent.md
│   ├── marketing-agent.md
│   ├── security-agent.md
│   └── self-improve-agent.md
└── hooks/
    └── post-generate.sh
```

---

## Phase-Details

### Phase 1: SPEC (Claude)
- Analysiert den Prompt in natürlicher Sprache
- Extrahiert: App-Type, Features, Tech-Stack, Constraints
- Entscheidet welche Skills und Agents aktiviert werden
- Lädt Memory aus `~/.onecommand/memory/patterns.json` für Kontext
- Output: strukturiertes JSON-Spec-Dokument

### Phase 2a: FRONTEND (Claude + Skills)
Aktivierte Skills: `frontend-design`, `ui-ux-pro-max`
- Vollständige UI-Komponenten
- Responsive Design (mobile-first)
- Color System, Typography, Spacing
- Alle Screens/Pages die der Spec verlangt

### Phase 2b: BACKEND (Codex)
Über `codex:codex-cli-runtime` delegiert:
- REST API oder tRPC routes
- Auth-System (JWT + Refresh Tokens)
- DB Schema + Migrations
- Environment-Konfiguration

### Phase 3: INTEGRATION + MARKETING (Claude)
- Frontend + Backend zusammenführen
- `.env.example`, `docker-compose.yml`, Deploy-Configs
- `marketing-skills` für Landing Page, README, Feature-Copy

### Phase 4: TESTS + SELF-HEALING
- `npm install && npm run build && npm test`
- Bei Fehlern: Fix-Agent analysiert und behebt
- Loop bis exit 0 (max 5 Iterationen)
- Nach 5x: verbleibende Fehler werden dokumentiert

### Phase 5: AUTOMATIONEN
- Git Hooks ins generierte Projekt installieren (pre-commit: lint + test)
- `/.github/workflows/ci.yml` — GitHub Actions
- Cron-Job Konfigurationen wenn nötig (z.B. für Scheduled Jobs)
- `Makefile` mit Standard-Targets: `make dev`, `make test`, `make deploy`

### Phase 6: EXCEED EXPECTATIONS
Geht aktiv über den Prompt hinaus:
- **Security Audit Agent**: OWASP-Check, SQL-Injection, XSS, Rate Limiting
- **Performance Agent**: Bundle-Size, Lazy Loading, Caching-Headers
- **Accessibility Agent**: ARIA-Labels, Keyboard-Navigation, Kontrast
- **Surprise Features**: Dark Mode, PWA-Manifest, Error-Boundaries, Loading States — was auch immer die App sinnvoll macht ohne explizit verlangt zu sein

### Phase 7: SELF-IMPROVEMENT
- Extrahiert Muster aus dem Run: was hat funktioniert, welche Fehler gab es, welche Fixes waren nötig
- Speichert in `~/.onecommand/memory/patterns.json`
- Nächster Run lädt diese Patterns als Kontext
- Über Zeit: bessere Entscheidungen beim Stack, weniger Fehler, bessere Specs

### Phase 8: DELIVERY
- Vollständige Zusammenfassung was gebaut wurde
- Was über den Prompt hinaus hinzugefügt wurde (Exceed-Phase)
- Deploy-Anleitung: Vercel / Railway / Docker
- Lokaler Start: `npm run dev`

---

## Commands

```bash
/onecommand "<prompt>"
# Startet vollen 8-Phasen-Workflow

/onecommand-status
# Zeigt aktuelle Phase, Fortschritt, offene Fehler
```

---

## "Fertig"-Kriterien

Plugin gibt erst Delivery-Report wenn:
1. `npm install` → exit 0
2. `npm run build` → exit 0
3. `npm test` → alle grün (oder dokumentiertes Warning)
4. `npm start` → Port antwortet
5. Security-Check → keine kritischen Issues
6. Accessibility-Check → keine WCAG-AA-Blocker

---

## Skill-Routing-Tabelle

| Phase | Aktivierte Skills | Modell |
|-------|-------------------|--------|
| Spec | spec-analyzer, stack-detector | Claude |
| Frontend | frontend-design, ui-ux-pro-max | Claude |
| Backend | codex:codex-cli-runtime | Codex |
| Integration | (intern) | Claude |
| Marketing | marketing-skills | Claude |
| Tests | superpowers:test-driven-development | Codex |
| Automationen | automation-installer | Claude |
| Exceed | exceed-expectations, security-agent | Claude |
| Self-Improve | self-improve-agent | Claude |
| Delivery | delivery-reporter | Claude |

---

## Memory-System

```
~/.onecommand/
└── memory/
    ├── patterns.json        # erfolgreiche Muster
    ├── errors.json          # häufige Fehler + Fixes
    └── stacks.json          # bewährte Tech-Stack-Combos
```

---

## Out of Scope (v1)

- Echtes Modell-Training / Fine-Tuning
- Multi-User-Collaboration in Echtzeit
- Visual Figma-to-Code Pipeline
- Mobile Native (iOS/Android) — nur Web/PWA
