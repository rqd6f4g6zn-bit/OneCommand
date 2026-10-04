#!/usr/bin/env bash
# =============================================================================
# OneCommand — Quality Gate
# =============================================================================
# The single source of truth for "does this build pass?". Agents call this
# script instead of hand-written check commands, so exit codes can never be
# swallowed by a pipe (`cmd | tee log; $?` reports tee's status, not cmd's).
#
# Stages:
#   static  install → audit → prisma generate → API contract → typecheck → lint → build → unit tests
#   e2e     database prep → Playwright acceptance tests → acceptance report
#   tour    demo seed → production server → every page as every demo login, screenshots
#           (hooks/ui-tour.py; skipped when the spec has no "demo" section)
#   all     static, then e2e, then tour (each only runs when the previous one passed)
#   (AI/ML projects — build_targets contain "ml" — are handed to hooks/ml-gate.py whatever the stage)
#
# Output (default <project>/.onecommand/gate/):
#   result.json      machine-readable result of every step
#   errors.txt       extracted error lines of failing steps (input for self-healer)
#   <step>.log       full log per step
#   acceptance.json  per-criterion verdict (e2e stage)
#   acceptance.md    Markdown matrix for the delivery report (e2e stage)
#   ../tour/         screenshots, report.md and review.md (tour stage)
#
# Exit codes: 0 passed · 1 failed · 2 usage error · 3 not applicable (no package.json)
#
# Usage: quality-gate.sh [--stage static|e2e|tour|all] [--project-dir DIR] [--out DIR]
#                        [--force-install] [--strict-flaky] [--no-audit] [--audit-level high|critical]
#                        [--verbose] [--help]
#
# audit checks production dependencies (npm, pnpm): critical advisories fail the gate, high ones
# are recorded as warnings (--audit-level high makes them blocking). --no-audit / OC_GATE_AUDIT=0
# disables it; an unreachable registry skips it.
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="static"
PROJECT_DIR="$(pwd)"
OUT_DIR=""
FORCE_INSTALL=false
STRICT_FLAKY=false
AUDIT="${OC_GATE_AUDIT:-1}"
AUDIT_LEVEL="${OC_GATE_AUDIT_LEVEL:-critical}"   # critical: only critical blocks · high: high blocks too
VERBOSE=false
STEP_TIMEOUT="${OC_GATE_STEP_TIMEOUT:-900}"   # seconds per step
E2E_TIMEOUT="${OC_GATE_E2E_TIMEOUT:-1800}"     # seconds for the Playwright run

usage() {
  sed -n '2,33p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --stage)          STAGE="${2:-}"; shift ;;
    --stage=*)        STAGE="${1#*=}" ;;
    --project-dir)    PROJECT_DIR="${2:-}"; shift ;;
    --project-dir=*)  PROJECT_DIR="${1#*=}" ;;
    --out)            OUT_DIR="${2:-}"; shift ;;
    --out=*)          OUT_DIR="${1#*=}" ;;
    --force-install)  FORCE_INSTALL=true ;;
    --strict-flaky)   STRICT_FLAKY=true ;;
    --no-audit)       AUDIT=0 ;;
    --audit-level)    AUDIT_LEVEL="${2:-}"; shift ;;
    --audit-level=*)  AUDIT_LEVEL="${1#*=}" ;;
    -v|--verbose)     VERBOSE=true ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "[gate] Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$AUDIT_LEVEL" in
  high|critical) ;;
  *) echo "[gate] --audit-level must be high or critical (got '$AUDIT_LEVEL')" >&2; exit 2 ;;
esac

case "$STAGE" in
  static|e2e|tour|all) ;;
  *) echo "[gate] --stage must be static, e2e, tour or all (got '$STAGE')" >&2; exit 2 ;;
esac

if [ ! -d "$PROJECT_DIR" ]; then
  echo "[gate] Project directory not found: $PROJECT_DIR" >&2
  exit 2
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
[ -n "$OUT_DIR" ] || OUT_DIR="$PROJECT_DIR/.onecommand/gate"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
cd "$PROJECT_DIR" || exit 2

if ! command -v python3 &>/dev/null; then
  echo "[gate] python3 is required" >&2
  exit 2
fi

# AI/ML training projects (spec build_targets contain "ml") have their own verdict: install, lint,
# tests, smoke training, metric threshold, model card, inference API. Same result.json format.
if [ -f .onecommand-spec.json ] && python3 -c 'import json,sys; s=json.load(open(".onecommand-spec.json")); sys.exit(0 if "ml" in (s.get("build_targets") or []) and isinstance(s.get("ml"), dict) else 1)' 2>/dev/null; then
  exec python3 "$SCRIPT_DIR/ml-gate.py" --project-dir "$PROJECT_DIR" --out "$OUT_DIR"
fi

STEPS_FILE="$OUT_DIR/.steps.tsv"
: > "$STEPS_FILE"
: > "$OUT_DIR/errors.txt"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

log()   { echo "[gate] $*"; }
debug() { if [ "$VERBOSE" = true ]; then echo "[gate]   · $*"; fi; }

# Keep gate output out of the generated project's git history.
if [ -f .gitignore ] && ! grep -qxF '.onecommand/' .gitignore; then
  printf '\n# OneCommand build state\n.onecommand/\n' >> .gitignore
  debug "added .onecommand/ to .gitignore"
fi

# ─── Helpers ──────────────────────────────────────────────────────────────────

# record <step> <status> <exit_code> <duration_s> <log> <reason>
record() {
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$6" >> "$STEPS_FILE"
}

# with_timeout <seconds> <cmd...> — portable: coreutils timeout, gtimeout (macOS), or none.
with_timeout() {
  local secs="$1"; shift
  if command -v timeout &>/dev/null; then
    timeout "$secs" "$@"
  elif command -v gtimeout &>/dev/null; then
    gtimeout "$secs" "$@"
  else
    "$@"
  fi
}

# extract_errors <step> <logfile> — appends the useful lines of a failing log to errors.txt.
extract_errors() {
  local step="$1" logfile="$2" matches
  matches="$(grep -nE '(error TS[0-9]+|[Ee]rror:|ERROR|ERR!|✘|✗|FAIL|failed|Failed to compile|Type error|Module not found|Cannot find|[0-9]+:[0-9]+ +error)' "$logfile" 2>/dev/null \
    | grep -v 'node_modules/' | head -60)"
  {
    echo "===== ${step} (full log: ${logfile}) ====="
    if [ -n "$matches" ]; then
      printf '%s\n' "$matches"
    else
      tail -40 "$logfile"
    fi
    echo ""
  } >> "$OUT_DIR/errors.txt"
}

# run_step <step> <timeout> <cmd...> — runs cmd with its real exit code, logs, records.
run_step() {
  local step="$1" secs="$2"; shift 2
  local logfile="$OUT_DIR/${step}.log" start end rc
  log "▶ ${step}: $*"
  start="$(date +%s)"
  with_timeout "$secs" "$@" > "$logfile" 2>&1
  rc=$?
  end="$(date +%s)"
  if [ "$rc" -eq 0 ]; then
    record "$step" pass "$rc" "$((end - start))" "$logfile" ""
    log "  ✓ ${step} ($((end - start))s)"
  else
    local reason="exit code $rc"
    [ "$rc" -eq 124 ] && reason="timed out after ${secs}s"
    record "$step" fail "$rc" "$((end - start))" "$logfile" "$reason"
    extract_errors "$step" "$logfile"
    log "  ✗ ${step} — ${reason} (log: ${logfile})"
  fi
  return "$rc"
}

skip_step() {
  record "$1" skipped "" 0 "" "$2"
  log "  ○ ${1} skipped — ${2}"
}

# promote_warnings <step> — a passed step whose log has "⚠" lines is recorded as warn.
promote_warnings() {
  local step="$1" logfile="$OUT_DIR/$1.log" count last
  count="$(grep -c '⚠' "$logfile" 2>/dev/null || true)"
  last="$(tail -1 "$STEPS_FILE")"
  if [ "${count:-0}" -gt 0 ] && printf '%s' "$last" | grep -q "^${step}"$'\t'"pass"$'\t'; then
    sed -i.bak '$d' "$STEPS_FILE" && rm -f "$STEPS_FILE.bak"
    printf '%s\n' "$last" | awk -F'\t' -v OFS='\t' -v r="${count} warning(s): $(grep -m1 '⚠' "$logfile" | sed 's/^[[:space:]]*⚠[[:space:]]*//' | tr '\t' ' ')" \
      '{ $2 = "warn"; $6 = r; print }' >> "$STEPS_FILE"
    log "  ⚠ ${step} — ${count} warning(s), see ${logfile}"
  fi
}

# spec_has <key> — true when .onecommand-spec.json has a non-null top-level key.
spec_has() {
  [ -f .onecommand-spec.json ] && python3 -c 'import json,sys; sys.exit(0 if json.load(open(".onecommand-spec.json")).get(sys.argv[1]) is not None else 1)' "$1" 2>/dev/null
}

# pkg_script <name> — prints the script body from package.json, empty if missing.
pkg_script() {
  python3 - "$1" << 'PYEOF'
import json, sys
try:
    scripts = json.load(open("package.json")).get("scripts") or {}
except (OSError, ValueError):
    scripts = {}
print(scripts.get(sys.argv[1], ""))
PYEOF
}

has_dep() {
  python3 - "$1" << 'PYEOF'
import json, sys
try:
    pkg = json.load(open("package.json"))
except (OSError, ValueError):
    sys.exit(1)
deps = {}
for key in ("dependencies", "devDependencies"):
    deps.update(pkg.get(key) or {})
sys.exit(0 if sys.argv[1] in deps else 1)
PYEOF
}

# ensure_database_url — use the project's own DATABASE_URL (.env.local, then .env, as
# Next.js does) and fall back to the local Postgres default only for postgres schemas.
ensure_database_url() {
  [ -n "${DATABASE_URL:-}" ] && return 0
  local f value
  for f in .env.local .env; do
    [ -f "$f" ] || continue
    value="$(sed -n 's/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}DATABASE_URL[[:space:]]*=[[:space:]]*//p' "$f" | tail -1)"
    value="${value%\"}"; value="${value#\"}"; value="${value%\'}"; value="${value#\'}"
    if [ -n "$value" ]; then
      export DATABASE_URL="$value"
      debug "DATABASE_URL from $f"
      return 0
    fi
  done
  if grep -qE 'provider[[:space:]]*=[[:space:]]*"postgres(ql)?"' prisma/schema.prisma 2>/dev/null; then
    export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/devdb"
    debug "DATABASE_URL defaulted to local Postgres"
  fi
}

manifest_hash() {
  file_hash package.json package-lock.json pnpm-lock.yaml yarn.lock bun.lockb bun.lock | awk '{print $1}' | tr -d '\n'
}

has_any_dep() {
  python3 -c 'import json,sys; p=json.load(open("package.json")); sys.exit(0 if (p.get("dependencies") or p.get("devDependencies")) else 1)' 2>/dev/null
}

file_hash() {
  if command -v shasum &>/dev/null; then shasum -a 256 "$@" 2>/dev/null
  else sha256sum "$@" 2>/dev/null; fi
}

# ─── Package manager ──────────────────────────────────────────────────────────

detect_pm() {
  if   [ -f pnpm-lock.yaml ]; then echo pnpm
  elif [ -f yarn.lock ];      then echo yarn
  elif [ -f bun.lockb ] || [ -f bun.lock ]; then echo bun
  else echo npm; fi
}

PM="$(detect_pm)"
case "$PM" in
  npm)  RUN=(npm run);  EXEC=(npx --no-install) ;;
  pnpm) RUN=(pnpm run); EXEC=(pnpm exec) ;;
  yarn) RUN=(yarn run); EXEC=(yarn) ;;
  bun)  RUN=(bun run);  EXEC=(bunx) ;;
esac

install_cmd() {
  case "$PM" in
    npm)  if [ -f package-lock.json ]; then echo "npm ci"; else echo "npm install"; fi ;;
    pnpm) echo "pnpm install --frozen-lockfile" ;;
    yarn) echo "yarn install --frozen-lockfile" ;;
    bun)  echo "bun install" ;;
  esac
}

# ─── Stage: static ────────────────────────────────────────────────────────────

stage_audit() {
  if [ "$AUDIT" = "0" ]; then
    skip_step audit "disabled (--no-audit / OC_GATE_AUDIT=0)"
    return 0
  fi
  local -a cmd
  case "$PM" in
    npm)  cmd=(npm audit --omit=dev --json) ;;
    pnpm) cmd=(pnpm audit --prod --json) ;;
    *)    skip_step audit "no machine-readable audit for $PM"; return 0 ;;
  esac
  log "▶ audit: ${cmd[*]} (blocking level: ${AUDIT_LEVEL})"
  local start end verdict
  start="$(date +%s)"
  # audit exits non-zero whenever anything is found — the verdict comes from the JSON counts.
  with_timeout 180 "${cmd[@]}" > "$OUT_DIR/audit.json" 2> "$OUT_DIR/audit.log"
  end="$(date +%s)"
  # Temp file instead of $( … ) around the heredoc: bash 3.2 (macOS) parses quotes inside it.
  python3 - "$OUT_DIR/audit.json" "$AUDIT_LEVEL" > "$OUT_DIR/.audit-verdict" << 'PYEOF2'
import json, sys
path, level = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path))
except (OSError, ValueError):
    print("unreadable"); raise SystemExit
# An error object or missing counts means the audit did not run (e.g. registry unreachable) —
# never report that as "no advisories".
if not isinstance(data, dict) or data.get("error") or "vulnerabilities" not in (data.get("metadata") or {}):
    print("unreadable"); raise SystemExit
counts = data["metadata"]["vulnerabilities"]
critical, high = int(counts.get("critical") or 0), int(counts.get("high") or 0)
vulns = data.get("vulnerabilities") or data.get("advisories") or {}
names = sorted({(v.get("name") or k) + ":" + str(v.get("severity")) for k, v in vulns.items()
                if v.get("severity") in ("high", "critical")})
blocking = critical + (high if level == "high" else 0)
state = "fail" if blocking else ("warn" if high else "pass")
print(f"{state}\t{critical}\t{high}\t{', '.join(names)[:600]}")
PYEOF2
  verdict="$(cat "$OUT_DIR/.audit-verdict")"
  rm -f "$OUT_DIR/.audit-verdict"
  local state critical high names
  IFS=$'\t' read -r state critical high names <<< "$verdict"
  case "$state" in
    pass)
      record audit pass 0 "$((end - start))" "$OUT_DIR/audit.json" ""
      log "  ✓ audit — no high/critical advisories ($((end - start))s)" ;;
    warn)
      record audit warn 0 "$((end - start))" "$OUT_DIR/audit.json" "${high} high advisories (non-blocking at level ${AUDIT_LEVEL}): ${names}"
      log "  ⚠ audit — ${high} high advisories, not blocking at level ${AUDIT_LEVEL}: ${names}" ;;
    fail)
      record audit fail 1 "$((end - start))" "$OUT_DIR/audit.json" "${critical} critical / ${high} high advisories"
      {
        echo "===== audit (full report: ${OUT_DIR}/audit.json) ====="
        echo "${critical} critical, ${high} high advisories in production dependencies: ${names}"
        echo "Fix: upgrade the affected packages to patched versions ($PM audit fix, or bump the direct"
        echo "dependency named in the advisory). A major upgrade is fine — the gate re-verifies everything."
        echo ""
      } >> "$OUT_DIR/errors.txt"
      log "  ✗ audit — ${critical} critical / ${high} high advisories: ${names}"
      return 1 ;;
    *)
      # Unreadable output almost always means the registry was unreachable — not a vulnerability.
      skip_step audit "audit not possible ($(head -c 160 "$OUT_DIR/audit.log" | tr '\n' ' '))" ;;
  esac
  return 0
}

stage_static() {
  local failed=0

  # 1. install — skipped when manifests are unchanged since the last green install
  # The stamp is taken AFTER a successful install: npm creates/rewrites the lockfile,
  # so a hash taken before would never match on the next run.
  local stamp="$OUT_DIR/.install-stamp"
  if [ "$FORCE_INSTALL" = false ] && [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$(manifest_hash)" ] \
     && { [ -d node_modules ] || ! has_any_dep; }; then
    skip_step install "package manifests unchanged since last successful install"
  else
    # shellcheck disable=SC2046
    if run_step install "$STEP_TIMEOUT" $(install_cmd); then
      manifest_hash > "$stamp"
    else
      rm -f "$stamp"
      # npm ci fails on an out-of-sync lockfile — retry once with npm install
      if [ "$PM" = npm ] && [ -f package-lock.json ] && grep -qE 'npm ci|in sync|lock file' "$OUT_DIR/install.log"; then
        log "  ↻ lockfile out of sync — retrying with npm install"
        sed -i.bak '$d' "$STEPS_FILE" && rm -f "$STEPS_FILE.bak"
        if run_step install "$STEP_TIMEOUT" npm install; then
          manifest_hash > "$stamp"
        else
          return 1
        fi
      else
        return 1   # nothing else can run without dependencies
      fi
    fi
  fi

  # 1b. audit — high/critical advisories in production dependencies. Run in the static
  # stage so vulnerable dependencies are fixed while building, not by a late
  # security pass that forces a full re-verification.
  stage_audit || failed=1

  # 2. prisma generate
  if [ -f prisma/schema.prisma ]; then
    ensure_database_url
    run_step prisma "$STEP_TIMEOUT" "${EXEC[@]}" prisma generate || failed=1
  else
    skip_step prisma "no prisma/schema.prisma"
  fi

  # 2b. API contract — generated types current, every endpoint has a handler, both sides use the
  # types (the typecheck below then catches every field-name drift between frontend and backend).
  if spec_has api_contract; then
    run_step contract 120 python3 "$SCRIPT_DIR/api-contract.py" check --project-dir "$PROJECT_DIR" --spec .onecommand-spec.json || failed=1
    promote_warnings contract
  else
    skip_step contract "spec has no api_contract"
  fi

  # 3. typecheck
  if [ -n "$(pkg_script typecheck)" ]; then
    run_step typecheck "$STEP_TIMEOUT" "${RUN[@]}" typecheck || failed=1
  elif [ -f tsconfig.json ]; then
    run_step typecheck "$STEP_TIMEOUT" "${EXEC[@]}" tsc --noEmit || failed=1
  else
    skip_step typecheck "no tsconfig.json"
  fi

  # 4. lint — errors fail the gate (warnings do not: linters exit 0 on warnings)
  if [ -n "$(pkg_script lint)" ]; then
    run_step lint "$STEP_TIMEOUT" "${RUN[@]}" lint || failed=1
  else
    skip_step lint "no lint script"
  fi

  # 5. build
  if [ -n "$(pkg_script build)" ]; then
    run_step build "$STEP_TIMEOUT" "${RUN[@]}" build || failed=1
  else
    skip_step build "no build script"
  fi

  # 6. unit tests — the npm init placeholder script counts as "no tests"
  local test_script
  test_script="$(pkg_script test)"
  if [ -z "$test_script" ] || printf '%s' "$test_script" | grep -q 'no test specified'; then
    skip_step unit "no test script"
  else
    CI=true run_step unit "$STEP_TIMEOUT" "${RUN[@]}" test || failed=1
  fi

  return "$failed"
}

# ─── Stage: e2e ───────────────────────────────────────────────────────────────

compose_file() {
  local f
  for f in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do
    [ -f "$f" ] && { echo "$f"; return 0; }
  done
  return 1
}

DATABASE_READY=false
prepare_database() {
  [ "$DATABASE_READY" = true ] && return 0
  [ -f prisma/schema.prisma ] || { skip_step database "no prisma/schema.prisma"; DATABASE_READY=true; return 0; }
  ensure_database_url

  local cf
  if cf="$(compose_file)" && command -v docker &>/dev/null && docker info &>/dev/null \
     && grep -qE '^[[:space:]]+db:' "$cf"; then
    run_step database-up 300 docker compose -f "$cf" up -d db || return 1
  else
    debug "no docker compose db service available — expecting DATABASE_URL to be reachable"
  fi

  # The DB container needs a few seconds after `up -d`; retry db push for up to 60s.
  local tries=0
  while :; do
    if run_step database "$STEP_TIMEOUT" "${EXEC[@]}" prisma db push --skip-generate --accept-data-loss; then
      break
    fi
    tries=$((tries + 1))
    [ "$tries" -ge 6 ] && return 1
    sed -i.bak '$d' "$STEPS_FILE" && rm -f "$STEPS_FILE.bak"   # keep only the final attempt
    log "  ↻ database not ready — retry ${tries}/5 in 10s"
    sleep 10
  done

  if python3 -c 'import json,sys; sys.exit(0 if (json.load(open("package.json")).get("prisma") or {}).get("seed") else 1)' 2>/dev/null; then
    run_step seed "$STEP_TIMEOUT" "${EXEC[@]}" prisma db seed || return 1
  else
    skip_step seed "no prisma.seed configured"
  fi
  DATABASE_READY=true
}

# browser_mismatch_hint — every test fails in milliseconds when the installed
# @playwright/test needs a browser revision that is not on disk. Say so explicitly,
# otherwise the healer goes hunting for bugs in the app.
browser_mismatch_hint() {
  grep -q "Executable doesn't exist" "$OUT_DIR/e2e.log" 2>/dev/null || return 0
  local wanted have version
  wanted="$(grep -o "Executable doesn't exist at [^ ]*" "$OUT_DIR/e2e.log" | head -1 | sed 's/.* at //')"
  local d
  have=""
  for d in "${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"/chromium*; do
    [ -d "$d" ] && have="${have}$(basename "$d") "
  done
  version="$(node -p "require('@playwright/test/package.json').version" 2>/dev/null || echo '?')"
  {
    echo "===== browsers (not an application bug) ====="
    echo "@playwright/test ${version} needs a browser that is not installed: ${wanted}"
    echo "Installed: ${have:-none}"
    echo "Fix: python3 \"${SCRIPT_DIR}/playwright-pin.py\" --project-dir \"${PROJECT_DIR}\" apply"
    echo "(pins the version whose browsers are installed), or allow the download: npx playwright install chromium"
    echo ""
  } >> "$OUT_DIR/errors.txt"
  log "  ⚠ browser revision mismatch — see errors.txt"
}

# test_change_check — the first e2e run records a hash of every acceptance test file; a later
# run that finds a changed or deleted test file without a mention in .onecommand/test-changes.md
# records a warning. A real build changed a test silently although the rules require a log entry.
test_change_check() {
  local test_dir="$1"
  python3 - "$test_dir" "$OUT_DIR/test-baseline.json" ".onecommand/test-changes.md" > "$OUT_DIR/.test-changes" << 'PYEOF2'
import hashlib, json, os, sys
test_dir, baseline_path, log_path = sys.argv[1:4]
current = {}
for root, _, files in os.walk(test_dir):
    for name in files:
        if name.endswith((".ts", ".js", ".mjs")):
            path = os.path.join(root, name)
            current[path] = hashlib.sha256(open(path, "rb").read()).hexdigest()
if not os.path.exists(baseline_path):
    json.dump(current, open(baseline_path, "w"), indent=2)
    print("baseline\t" + str(len(current)))
    raise SystemExit
baseline = json.load(open(baseline_path))
log = open(log_path, encoding="utf-8", errors="replace").read() if os.path.exists(log_path) else ""
unlogged = sorted(p for p, h in baseline.items()
                  if current.get(p) != h and os.path.basename(p) not in log)
print(("warn\t" if unlogged else "pass\t") + ", ".join(unlogged))
PYEOF2
  local state detail
  IFS=$'\t' read -r state detail < "$OUT_DIR/.test-changes"
  rm -f "$OUT_DIR/.test-changes"
  case "$state" in
    baseline) record test-changes pass 0 0 "$OUT_DIR/test-baseline.json" "baseline of ${detail} test files recorded" ;;
    pass)     record test-changes pass 0 0 "$OUT_DIR/test-baseline.json" "" ;;
    warn)
      record test-changes warn 0 0 "$OUT_DIR/test-baseline.json" "acceptance tests changed without an entry in .onecommand/test-changes.md: ${detail}"
      log "  ⚠ test-changes — changed without a test-changes.md entry: ${detail}" ;;
  esac
}

stage_e2e() {
  local spec=".onecommand-spec.json" config=""
  local f
  for f in playwright.config.ts playwright.config.js playwright.config.mjs; do
    [ -f "$f" ] && { config="$f"; break; }
  done

  if [ ! -f "$spec" ]; then
    record acceptance fail "" 0 "" "missing $spec"
    echo "===== acceptance =====" >> "$OUT_DIR/errors.txt"
    echo "$spec not found — run spec-analyzer first" >> "$OUT_DIR/errors.txt"
    return 1
  fi
  if [ -z "$config" ]; then
    record acceptance fail "" 0 "" "no playwright.config — run the acceptance-tester skill first"
    printf '===== acceptance =====\nNo playwright.config.(ts|js|mjs) — run the acceptance-tester skill to generate the suite.\n\n' >> "$OUT_DIR/errors.txt"
    return 1
  fi
  if ! has_dep @playwright/test; then
    record acceptance fail "" 0 "" "@playwright/test not in devDependencies"
    printf '===== acceptance =====\n@playwright/test is not installed — add it as a devDependency.\n\n' >> "$OUT_DIR/errors.txt"
    return 1
  fi

  prepare_database || return 1

  # Browser binary. `playwright install` is a no-op when the revision this @playwright/test
  # needs is already there — a pre-set PLAYWRIGHT_BROWSERS_PATH does NOT mean it is the
  # right revision. If the download is blocked (sandbox, offline) but pre-installed browsers
  # exist, carry on: the run below says precisely which revision is missing.
  if ! run_step browsers "$STEP_TIMEOUT" "${EXEC[@]}" playwright install chromium; then
    if [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ -d "${PLAYWRIGHT_BROWSERS_PATH}" ]; then
      sed -i.bak '$d' "$STEPS_FILE" && rm -f "$STEPS_FILE.bak"
      skip_step browsers "download failed — trying pre-installed browsers in ${PLAYWRIGHT_BROWSERS_PATH}"
    else
      return 1
    fi
  fi

  local results="$OUT_DIR/playwright.json"
  rm -f "$results"
  PLAYWRIGHT_JSON_OUTPUT_NAME="$results" CI=true \
    run_step e2e "$E2E_TIMEOUT" "${EXEC[@]}" playwright test --config "$config" --reporter=list,json
  # The e2e exit code alone is not the verdict: the acceptance report checks that
  # every must-criterion has a passing test (a missing test is a failure too).
  browser_mismatch_hint
  local test_dir
  test_dir="$(sed -n "s/.*testDir:[[:space:]]*['\"]\([^'\"]*\)['\"].*/\1/p" "$config" | head -1)"
  [ -n "$test_dir" ] && [ -d "$test_dir" ] && test_change_check "$test_dir"

  local report_args=(report --spec "$spec" --results "$results" --out "$OUT_DIR/acceptance.json" --markdown "$OUT_DIR/acceptance.md")
  [ "$STRICT_FLAKY" = true ] && report_args+=(--strict-flaky)
  run_step acceptance 120 python3 "$SCRIPT_DIR/acceptance-report.py" "${report_args[@]}"
  local rc=$?
  if [ "$rc" -ne 0 ] && [ -f "$OUT_DIR/acceptance.json" ]; then
    python3 - "$OUT_DIR/acceptance.json" >> "$OUT_DIR/errors.txt" << 'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
print("===== failing acceptance criteria =====")
for c in data.get("criteria", []):
    if c["blocking"] and c["status"] != "passed":
        print(f'{c["id"]} [{c["status"]}] {c["title"]}')
        for t in c.get("tests", []):
            if t.get("error"):
                print(f'    {t["file"]}: {t["error"][:400]}')
print()
PYEOF
  fi
  cat "$OUT_DIR/acceptance.log"
  return "$rc"
}

# ─── Stage: tour ──────────────────────────────────────────────────────────────

# stage_tour — what a user sees after the demo seed: every page as every demo login, screenshots
# for the review checklist (.onecommand/tour/review.md), server errors, lost sessions, missing
# metric labels and "undefined"/"NaN" in the UI are blocking.
stage_tour() {
  if ! spec_has demo; then
    skip_step tour "spec has no demo section"
    return 0
  fi
  if [ -z "$(pkg_script start)" ]; then
    record tour fail "" 0 "" "no start script"
    printf '===== tour =====\npackage.json has no start script — the UI tour runs the production build.\n\n' >> "$OUT_DIR/errors.txt"
    return 1
  fi
  prepare_database || return 1
  local rc
  # The browser part gets the stage budget minus time for seed and server start.
  run_step tour "$E2E_TIMEOUT" python3 "$SCRIPT_DIR/ui-tour.py" run --project-dir "$PROJECT_DIR" \
    --spec .onecommand-spec.json --out "$PROJECT_DIR/.onecommand/tour" --timeout "$((E2E_TIMEOUT > 600 ? E2E_TIMEOUT - 300 : E2E_TIMEOUT))"
  rc=$?
  cat "$OUT_DIR/tour.log"
  if [ "$rc" -eq 3 ]; then   # not a web app — nothing to tour
    sed -i.bak '$d' "$STEPS_FILE" && rm -f "$STEPS_FILE.bak"
    skip_step tour "$(tail -1 "$OUT_DIR/tour.log" | sed 's/^\[tour\] //')"
    return 0
  fi
  [ "$rc" -eq 0 ] || return 1
  promote_warnings tour
}

# ─── Main ─────────────────────────────────────────────────────────────────────

if [ ! -f package.json ]; then
  log "No package.json in $PROJECT_DIR — gate not applicable (game/OS/Flutter builds verify through their own agents)"
  record gate not_applicable "" 0 "" "no package.json"
  OVERALL=3
else
  log "Project: $PROJECT_DIR · package manager: $PM · stage: $STAGE"
  OVERALL=0
  case "$STAGE" in
    static) stage_static || OVERALL=1 ;;
    e2e)    stage_e2e    || OVERALL=1 ;;
    tour)   stage_tour   || OVERALL=1 ;;
    all)
      if stage_static; then
        if stage_e2e; then
          stage_tour || OVERALL=1
        else
          OVERALL=1
          record tour skipped "" 0 "" "e2e stage failed"
          log "  ○ tour skipped — e2e stage failed"
        fi
      else
        OVERALL=1
        record e2e skipped "" 0 "" "static stage failed"
        record tour skipped "" 0 "" "static stage failed"
        log "  ○ e2e and tour skipped — static stage failed"
      fi
      ;;
  esac
fi

FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "$STEPS_FILE" "$OUT_DIR" "$STAGE" "$PROJECT_DIR" "$PM" "$STARTED_AT" "$FINISHED_AT" "$OVERALL" << 'PYEOF'
import json, os, sys
steps_file, out_dir, stage, project, pm, started, finished, overall = sys.argv[1:9]
steps = []
with open(steps_file) as f:
    for line in f:
        name, status, rc, dur, log, reason = (line.rstrip("\n").split("\t") + [""] * 6)[:6]
        steps.append({
            "step": name, "status": status,
            "exit_code": int(rc) if rc not in ("", None) else None,
            "duration_s": int(dur or 0), "log": log or None, "reason": reason or None,
        })
result = {
    "version": 1, "stage": stage, "project_dir": project, "package_manager": pm,
    "started_at": started, "finished_at": finished,
    "passed": overall == "0", "not_applicable": overall == "3",
    "failed_steps": [s["step"] for s in steps if s["status"] == "fail"],
    "warnings": [f'{s["step"]}: {s["reason"]}' for s in steps if s["status"] == "warn"],
    "steps": steps,
}
acc_path = os.path.join(out_dir, "acceptance.json")
if stage in ("e2e", "all") and os.path.exists(acc_path):
    result["acceptance"] = json.load(open(acc_path)).get("summary")
tmp = os.path.join(out_dir, ".result.json.tmp")
with open(tmp, "w") as f:
    json.dump(result, f, indent=2)
    f.write("\n")
os.replace(tmp, os.path.join(out_dir, "result.json"))
PYEOF
rm -f "$STEPS_FILE"

case "$OVERALL" in
  0) log "✅ GATE PASSED (${STAGE}) — ${OUT_DIR}/result.json" ;;
  3) log "○ GATE NOT APPLICABLE — ${OUT_DIR}/result.json" ;;
  *) log "❌ GATE FAILED (${STAGE}) — errors: ${OUT_DIR}/errors.txt" ;;
esac
exit "$OVERALL"
