#!/bin/bash
# OneCommand post-generate hook
# Runs automatically after code generation phases complete.
# Performs: npm install, .env.local bootstrap, Prisma client generation.

set -eo pipefail

echo ""
echo "[OneCommand] Running post-generate checks..."

# Install dependencies
if [ -f "package.json" ]; then
  echo "[OneCommand] Installing dependencies..."
  if npm install --silent > /tmp/onecommand-npm-install.log 2>&1; then
    tail -3 /tmp/onecommand-npm-install.log
    echo "[OneCommand] ✓ Dependencies installed."
  else
    tail -20 /tmp/onecommand-npm-install.log
    echo "[OneCommand] ✗ npm install failed — full log: /tmp/onecommand-npm-install.log"
    exit 1
  fi
fi

# Copy .env.example to .env.local if not present
if [ -f ".env.example" ] && [ ! -f ".env.local" ]; then
  echo "[OneCommand] Creating .env.local from .env.example..."
  cp .env.example .env.local
  echo "[OneCommand] ✓ .env.local created. Edit it with your values before running."
fi

# Generate Prisma client if schema exists
if [ -f "prisma/schema.prisma" ]; then
  echo "[OneCommand] Generating Prisma client..."
  export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/devdb}"
  if npx prisma generate > /tmp/onecommand-prisma.log 2>&1; then
    echo "[OneCommand] ✓ Prisma client generated."
  else
    tail -5 /tmp/onecommand-prisma.log
    echo "[OneCommand] ⚠ Prisma generate failed — full log: /tmp/onecommand-prisma.log"
  fi
fi

# Initialize husky if package.json has prepare script
if [ -f "package.json" ] && grep -q '"prepare"' package.json 2>/dev/null; then
  echo "[OneCommand] Initializing git hooks..."
  npm run prepare --silent 2>/dev/null || true
fi

echo "[OneCommand] ✓ Post-generate complete."
echo ""
