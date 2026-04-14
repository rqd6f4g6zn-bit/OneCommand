---
description: Show the current OneCommand workflow status — which phases are complete, which are running, and what's still pending for the current project.
allowed-tools: Bash, Read
---

Show the current OneCommand build status for this project directory.

## Steps

1. Run the phase check:

```bash
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║         OneCommand — Build Status            ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Phase 1: Spec
if [ -f ".onecommand-spec.json" ]; then
  PROJECT=$(python3 -c "import json; d=json.load(open('.onecommand-spec.json')); print(d.get('project_name',''))" 2>/dev/null)
  echo "✓ Phase 1: Spec complete — Project: $PROJECT"
else
  echo "○ Phase 1: Spec (not started)"
fi

# Phase 2: Frontend
FRONTEND_COUNT=$(find app -name "page.tsx" 2>/dev/null | wc -l | tr -d ' ')
if [ "$FRONTEND_COUNT" -gt "0" ]; then
  echo "✓ Phase 2a: Frontend — $FRONTEND_COUNT pages generated"
else
  echo "○ Phase 2a: Frontend (pending)"
fi

# Phase 2b: Backend
if [ -f "prisma/schema.prisma" ]; then
  MODEL_COUNT=$(grep -c "^model " prisma/schema.prisma 2>/dev/null || echo "0")
  echo "✓ Phase 2b: Backend — $MODEL_COUNT DB models, API routes generated"
else
  echo "○ Phase 2b: Backend (pending)"
fi

# Phase 3: Integration
if [ -f ".env.example" ] && [ -f "lib/auth.ts" ]; then
  echo "✓ Phase 3: Integration complete"
else
  echo "○ Phase 3: Integration (pending)"
fi

# Phase 3b: Marketing
if [ -f "README.md" ] && [ -f "CHANGELOG.md" ]; then
  echo "✓ Phase 3b: Marketing — README + CHANGELOG generated"
else
  echo "○ Phase 3b: Marketing (pending)"
fi

# Phase 4: Tests
if [ -f "/tmp/onecommand-build.log" ]; then
  BUILD_STATUS=$(tail -1 /tmp/onecommand-build.log 2>/dev/null)
  if grep -q "error\|Error\|failed" /tmp/onecommand-build.log 2>/dev/null; then
    echo "⚠ Phase 4: Tests — build had errors (check /tmp/onecommand-build.log)"
  else
    echo "✓ Phase 4: Tests passed"
  fi
else
  echo "○ Phase 4: Tests + Self-Healing (pending)"
fi

# Phase 5: Automations
if [ -f ".github/workflows/ci.yml" ] && [ -f "Makefile" ]; then
  echo "✓ Phase 5: Automations — Git hooks, CI/CD, Makefile installed"
else
  echo "○ Phase 5: Automations (pending)"
fi

# Phase 6: Exceed Expectations
if [ -f "app/error.tsx" ] && [ -f "app/not-found.tsx" ]; then
  echo "✓ Phase 6: Exceed-Expectations complete"
else
  echo "○ Phase 6: Exceed-Expectations (pending)"
fi

# Phase 7: Self-Improve
if [ -f "$HOME/.onecommand/memory/patterns.json" ]; then
  PATTERN_COUNT=$(python3 -c "import json,os; d=json.load(open(os.path.expanduser('~/.onecommand/memory/patterns.json'))); print(len(d['patterns']))" 2>/dev/null || echo "?")
  echo "✓ Phase 7: Self-Improvement — $PATTERN_COUNT patterns in memory"
else
  echo "○ Phase 7: Self-Improvement (pending)"
fi

# Phase 8: Delivery
if [ -f "ONECOMMAND-DELIVERY.md" ]; then
  echo "✓ Phase 8: Delivery complete — see ONECOMMAND-DELIVERY.md"
else
  echo "○ Phase 8: Delivery (pending)"
fi

echo ""
```

2. If remaining errors exist, show them:
```bash
if [ -f "/tmp/onecommand-remaining-errors.txt" ]; then
  echo "⚠ Unresolved errors from last run:"
  cat /tmp/onecommand-remaining-errors.txt
  echo ""
fi
```

3. If delivery is complete:
```bash
[ -f "ONECOMMAND-DELIVERY.md" ] && echo "Run complete. See ONECOMMAND-DELIVERY.md for the full report and deploy instructions."
```
