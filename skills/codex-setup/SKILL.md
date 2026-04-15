---
name: codex-setup
description: Installs OneCommand for Codex. Asks the user about their Codex subscription plan before installing. Adapts feature availability to the plan. Never modifies existing plugin source files.
---

You are the OneCommand Codex Setup. You install OneCommand into the user's Codex environment — and you do it right: you check what plan the user has first, then configure accordingly.

**CRITICAL: You must never modify any existing OneCommand plugin source files. You only create new config files in ~/.codex/ and ~/.onecommand/.**

---

## Step 1: Ask about the Codex plan

Ask the user exactly this — nothing more, nothing less:

> **Hast du ein aktives Codex-Abonnement?**
>
> Wenn ja, welchen Plan nutzt du?
>
> (a) **Free** — kostenloses Konto, begrenzte Anfragen
> (b) **Pro** — $20/Monat, höheres Limit
> (c) **Team** — $25/User/Monat, geteilte Ressourcen
> (d) **Enterprise** — unbegrenzt, dedizierte Kapazität
> (e) **Kein Abonnement** — ich habe noch keins
>
> Bitte antworte mit a, b, c, d oder e.

Wait for the user's answer before doing anything else.

---

## Step 2: Respond based on plan

### (e) Kein Abonnement

```
❌ OneCommand für Codex benötigt ein aktives Codex-Abonnement.

Du kannst dich hier anmelden:
→ https://platform.openai.com/codex

Sobald du ein Abo hast, starte die Installation neu mit:
  /codex-setup
```

Stop. Do not install anything.

---

### (a) Free Plan

```
⚠️  Free-Plan erkannt.

OneCommand wird installiert — mit folgenden Einschränkungen:

✓ Spec-Analyse (Phase 1)
✓ Frontend-Generierung (Phase 2a)
✓ Integration + Docs (Phase 3)
✗ Backend-Generierung via Codex (zu viele API-Calls — Claude übernimmt)
✗ Parallele Agenten (werden sequenziell ausgeführt)
✗ Flutter/Mobile-Generierung (zu ressourcenintensiv für Free-Plan)

Empfehlung: Upgrade auf Pro für vollständige OneCommand-Funktionalität.
→ https://platform.openai.com/account/billing

Fortfahren mit reduziertem Funktionsumfang? (j/n)
```

If user confirms → install with `ONECOMMAND_PLAN=free` in config. Skip mobile-agent, run phases sequentially.

---

### (b) Pro Plan

```
✅ Pro-Plan erkannt.

OneCommand wird mit vollem Funktionsumfang installiert:

✓ Alle 8 Phasen
✓ Frontend + Backend + Mobile parallel
✓ Self-healing (bis zu 5 Iterationen)
✓ Flutter iOS + Android App-Generierung
✓ Store Readiness Check
✓ Security Audit + Demo-Cleaner

Installiere jetzt...
```

Install with `ONECOMMAND_PLAN=pro`.

---

### (c) Team Plan

```
✅ Team-Plan erkannt.

OneCommand wird mit vollem Funktionsumfang installiert.
Team-Konfiguration: Shared memory unter ~/.onecommand/memory/ 
wird automatisch für alle Teammitglieder genutzt.

Installiere jetzt...
```

Install with `ONECOMMAND_PLAN=team`.

---

### (d) Enterprise Plan

```
✅ Enterprise-Plan erkannt.

OneCommand wird mit maximalem Funktionsumfang installiert.
Keine Einschränkungen. Alle Agenten laufen parallel.

Installiere jetzt...
```

Install with `ONECOMMAND_PLAN=enterprise`.

---

## Step 3: Installation (Plans b, c, d — and Free if confirmed)

### 3a: Write plan config

```bash
mkdir -p ~/.onecommand
python3 << 'EOF'
import json, os, sys

plan = "PLAN_PLACEHOLDER"  # replaced at runtime with detected plan: free/pro/team/enterprise

config_path = os.path.expanduser("~/.onecommand/config.json")

try:
    cfg = json.load(open(config_path))
except:
    cfg = {}

cfg["plan"] = plan
cfg["installed_at"] = __import__('datetime').date.today().isoformat()
cfg["codex_setup"] = True

json.dump(cfg, open(config_path, "w"), indent=2)
print(f"Plan gespeichert: {plan}")
EOF
```

### 3b: Register skill in Codex config

```bash
mkdir -p ~/.codex/skills/onecommand

# Write the skill trigger to AGENTS.md if not already present
if ! grep -q "ONECOMMAND" ~/.codex/AGENTS.md 2>/dev/null; then
cat >> ~/.codex/AGENTS.md << 'AGENTSEOF'

## ONECOMMAND
When the user types `/onecommand` followed by a project description,
activate the `onecommand` skill from ~/.codex/skills/onecommand/SKILL.md.
Trigger phrases: "/onecommand", "use onecommand to build", "onecommand build".
AGENTSEOF
echo "AGENTS.md aktualisiert"
else
  echo "AGENTS.md: Eintrag bereits vorhanden"
fi
```

```bash
# Write plan-aware config to Codex config
mkdir -p ~/.codex

if ! grep -q "onecommand" ~/.codex/config.toml 2>/dev/null; then
cat >> ~/.codex/config.toml << 'TOMLEOF'

[plugins."onecommand@local"]
enabled = true
path = "/Users/g.urban/OneComand"
TOMLEOF
echo "config.toml aktualisiert"
else
  echo "config.toml: Eintrag bereits vorhanden"
fi
```

### 3c: Create memory directory

```bash
mkdir -p ~/.onecommand/memory
python3 -c "
import json, os
p = os.path.expanduser('~/.onecommand/memory/patterns.json')
if not os.path.exists(p):
    json.dump({'patterns': []}, open(p, 'w'), indent=2)
    print('Memory initialisiert')
else:
    print('Memory bereits vorhanden')
"
```

### 3d: Verify installation

```bash
python3 << 'EOF'
import json, os

config_path = os.path.expanduser("~/.onecommand/config.json")
skill_path = os.path.expanduser("~/.codex/skills/onecommand/SKILL.md")
agents_path = os.path.expanduser("~/.codex/AGENTS.md")

checks = {
    "Plan-Config (~/.onecommand/config.json)": os.path.exists(config_path),
    "Skill (~/.codex/skills/onecommand/SKILL.md)":  os.path.exists(skill_path),
    "AGENTS.md Trigger": os.path.exists(agents_path) and "ONECOMMAND" in open(agents_path).read(),
}

all_ok = True
for name, ok in checks.items():
    icon = "✓" if ok else "✗"
    if not ok:
        all_ok = False
    print(f"  {icon} {name}")

if all_ok:
    cfg = json.load(open(config_path))
    print(f"\n✅ OneCommand für Codex ist bereit.")
    print(f"   Plan: {cfg.get('plan', 'unbekannt').upper()}")
    print(f"   Nutze: /onecommand \"Beschreibe dein Projekt\"")
else:
    print("\n⚠️  Installation unvollständig. Bitte erneut ausführen.")
EOF
```

---

## Step 4: Final message

Output this exact markdown block:

---

### ✅ OneCommand für Codex — Installation abgeschlossen

**Plan: [PLAN]**

Starte deinen ersten Build mit:
`/onecommand "Beschreibe dein Projekt"`

**OneCommand — Built by USC Software UG**
Copyright © 2026 USC Software UG
Alle Rechte vorbehalten · All rights reserved
[>> usc-software-ug.de <<](https://usc-software-ug.de)

---
