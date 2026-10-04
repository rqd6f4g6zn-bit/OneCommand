#!/usr/bin/env bash
# =============================================================================
# OneCommand — Quality Gate
# =============================================================================
# The single source of truth for "does this build pass?". Agents call this
# script instead of hand-written check commands, so exit codes can never be
# swallowed by a pipe (`cmd | tee log; $?` reports tee's status, not cmd's).
#
# Stages:
#   static  install → prisma generate → typecheck → lint → build → unit tests
#   e2e     database prep → Playwright acceptance tests → acceptance report
#   all     static, then e2e (e2e only runs when static passed)
#
# Output (default <project>/.onecommand/gate/):
#   result.json      machine-readable result of every step
#   errors.txt       extracted error lines of failing steps (input for self-healer)
#   <step>.log       full log per step
#   acceptance.json  per-criterion verdict (e2e stage)
#   acceptance.md    Markdown matrix for the delivery report (e2e stage)
#
# Exit codes: 0 passed · 1 failed · 2 usage error · 3 not applicable (no package.json)
#
# Usage: quality-gate.sh [--stage static|e2e|all] [--project-dir DIR] [--out DIR]
#                        [--force-install] [--strict-flaky] [--verbose] [--help]
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="static"
PROJECT_DIR="$(pwd)"
OUT_DIR=""
FORCE_INSTALL=false
STRICT_FLAKY=false
VERBOSE=false
STEP_TIMEOUT="${OC_GATE_STEP_TIMEOUT:-900}"   # seconds per step
E2E_TIMEOUT="${OC_GATE_E2E_TIMEOUT:-1800}"     # seconds for the Playwright run

usage() {
  sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
    -v|--verbose)     VERBOSE=true ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "[gate] Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$STAGE" in
  static|e2e|all) ;;
  *) echo "[gate] --stage must be static, e2e or all (got '$STAGE')" >&2; exit 2 ;;
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

stage_static() {
  local failed=0

  # 1. install — skipped when manifests are unchanged since the last green install
  local stamp="$OUT_DIR/.install-stamp" current=""
  current="$(file_hash package.json package-lock.json pnpm-lock.yaml yarn.lock bun.lockb bun.lock | awk '{print $1}' | tr -d '\n')"
  if [ "$FORCE_INSTALL" = false ] && [ -d node_modules ] && [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$current" ]; then
    skip_step install "package manifests unchanged since last successful install"
  else
    # shellcheck disable=SC2046
    if run_step install "$STEP_TIMEOUT" $(install_cmd); then
      printf '%s' "$current" > "$stamp"
    else
      rm -f "$stamp"
      # npm ci fails on an out-of-sync lockfile — retry once with npm install
      if [ "$PM" = npm ] && [ -f package-lock.json ] && grep -qE 'npm ci|in sync|lock file' "$OUT_DIR/install.log"; then
        log "  ↻ lockfile out of sync — retrying with npm install"
        sed -i.bak '$d' "$STEPS_FILE" && rm -f "$STEPS_FILE.bak"
        if run_step install "$STEP_TIMEOUT" npm install; then
          printf '%s' "$current" > "$stamp"
        else
          return 1
        fi
      else
        return 1   # nothing else can run without dependencies
      fi
    fi
  fi

  # 2. prisma generate
  if [ -f prisma/schema.prisma ]; then
    export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/devdb}"
    run_step prisma "$STEP_TIMEOUT" "${EXEC[@]}" prisma generate || failed=1
  else
    skip_step prisma "no prisma/schema.prisma"
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

prepare_database() {
  [ -f prisma/schema.prisma ] || { skip_step database "no prisma/schema.prisma"; return 0; }
  export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/devdb}"

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

  # Browser binary: reuse a pre-installed Chromium when present (CI images, sandboxes).
  if [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ] || [ ! -d "${PLAYWRIGHT_BROWSERS_PATH}" ]; then
    run_step browsers "$STEP_TIMEOUT" "${EXEC[@]}" playwright install chromium || return 1
  else
    skip_step browsers "using PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH}"
  fi

  local results="$OUT_DIR/playwright.json"
  rm -f "$results"
  PLAYWRIGHT_JSON_OUTPUT_NAME="$results" CI=true \
    run_step e2e "$E2E_TIMEOUT" "${EXEC[@]}" playwright test --config "$config" --reporter=list,json
  # The e2e exit code alone is not the verdict: the acceptance report checks that
  # every must-criterion has a passing test (a missing test is a failure too).

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
    all)
      if stage_static; then
        stage_e2e || OVERALL=1
      else
        OVERALL=1
        record e2e skipped "" 0 "" "static stage failed"
        log "  ○ e2e skipped — static stage failed"
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
