#!/usr/bin/env python3
"""OneCommand UI tour.

Acceptance tests check behaviour against a minimal seed. They do not look at the
product a user sees after "npm run db:seed" and logging in with a demo account.
A real CRM build passed 43/43 criteria and still showed a dashboard whose
win-rate tile read "100 %" above "5 gewonnen, 2 verloren", two different
open-pipeline totals, and an empty "Meine Aufgaben" for the admin demo login.
Its production server also refused to log anyone in with the .env dev secret.
Only screenshots revealed this.

The tour does what a reviewer does:
  1. loads the full demo data (demo.seed_command, SEED_MODE=demo, without ONECOMMAND_E2E),
  2. starts the production build like a deployment would — fresh strong secrets, NODE_ENV=production,
  3. logs in with every demo account (spec "demo.accounts") through the real login form,
  4. visits every page of the spec (dynamic pages like /contacts/[id] through links on the pages),
  5. takes desktop screenshots for every account, mobile screenshots for the first account,
  6. records server errors, uncaught exceptions, failed API calls, "undefined"/"NaN"/"Invalid Date"
     in the visible text, lost sessions, metrics without their spec label (spec.metrics[].shown_on),
     the performance budget (spec.performance_budget: lcp_ms, cls, page_kb — first visit, no cache,
     10 Mbit/s and 40 ms, desktop),
     horizontal overflow on mobile and console errors,
  7. writes .onecommand/tour/review.md — the checklist the agent works through by looking at
     every listed screenshot (consistency of numbers and labels, empty views, layout).

Subcommands
-----------
validate       Check spec "pages" and "demo" in Phase 1.
run            Run the tour (quality gate stage "tour").
review-status  Exit 0 only when every screenshot in review.md is ticked and no finding is open.

Exit codes: 0 ok · 1 problems found · 2 usage error · 3 not applicable (no demo section / not a web app)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTH_PAGES = re.compile(r"/(login|signin|sign-in|anmelden|register|signup|sign-up|registrieren|forgot|reset|"
                        r"passwort|password|verify|invite|einladung)", re.I)
LOGOUT = re.compile(r"/(logout|signout|sign-out|abmelden)\b", re.I)
SECRET_VARS = ("AUTH_SECRET", "NEXTAUTH_SECRET", "JWT_SECRET", "SESSION_SECRET", "BETTER_AUTH_SECRET",
               "COOKIE_SECRET", "IRON_SESSION_PASSWORD")
URL_VARS = ("APP_URL", "NEXTAUTH_URL", "AUTH_URL", "BETTER_AUTH_URL", "PUBLIC_APP_URL", "SITE_URL")
DESKTOP = {"name": "desktop", "width": 1440, "height": 900}
MOBILE = {"name": "mobile", "width": 390, "height": 844}
REVIEW_CHECKS = """\
For every listed screenshot, open it with the Read tool and check:
- **Numbers agree**: a metric shown on several pages (dashboard tile, report, list footer) has the same
  value for the same period. Counts next to a percentage come from the same period as the percentage.
- **Labels name their period** ("Abschlussquote (dieser Monat)", not a bare "Abschlussquote") and use the
  label from spec.metrics.
- **No empty views for demo logins**: lists, boards, "Meine …" views and dashboards show demo data.
  An empty view with demo data loaded is a seed bug — fix prisma/seed (data for every demo account).
- **Nothing raw or broken**: IDs instead of names, ISO dates, English strings in a German UI,
  truncated or overlapping text, misaligned columns, placeholder images, cut-off buttons.
- **Looks designed, not generated** (skills/oc-frontend-design "Visual quality bar"): the brand typeface and
  palette from .onecommand/design.md are visible; one clear focal point per page (title, primary action,
  key numbers in the display face with tabular figures); aligned edges, even spacing, consistent radii;
  charts and badges carry labels and colours, not code values; empty space is intentional. Would a paying
  customer accept this screen next to Linear or Stripe? If not, write what is off as a finding.
- **Mobile** screenshots: navigation reachable, no horizontal scrolling, tables usable.
- **Roles**: restricted pages show a clear "keine Berechtigung" state or are hidden in the navigation.

Tick a line (`- [x]`) only after looking at that screenshot, and end it with a note: `→ ok: <what you
checked>` or `→ see findings`. Write every finding as an indented `  - ✗ …` line under it. A ticked line
without a note does not count as reviewed. After fixing, re-run the gate stage tour; it writes a fresh
checklist.

Listed: every page of the first demo login and anonymous visitors (desktop + mobile) and the landing page
of every other role. The remaining screenshots of other roles are covered by the automated checks
(report.md) — they are not an open review item.
"""


def log(msg: str) -> None:
    print(f"[tour] {msg}", flush=True)


def load_spec(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"[tour] spec not found: {path}") from None
    except ValueError as exc:
        raise SystemExit(f"[tour] spec is not valid JSON ({path}): {exc}") from None


def page_path(entry: Any) -> str | None:
    """'/dashboard (Übersicht)' → '/dashboard'; {'path': '/x'} → '/x'."""
    if isinstance(entry, dict):
        entry = entry.get("path") or entry.get("route") or ""
    match = re.search(r"(/[^\s,;()]*)", str(entry))
    return (match.group(1).rstrip(".:") or "/") if match else None


def collect_pages(spec: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for entry in spec.get("pages") or []:
        path = page_path(entry)
        if path and path not in seen and not path.startswith("/api/"):
            seen.append(path)
    return seen


def is_dynamic(path: str) -> bool:
    return bool(re.search(r"\[[^\]]+\]|/:[A-Za-z_]|\{[^}]+\}", path))


def pattern_regex(path: str) -> str:
    parts = []
    for seg in path.strip("/").split("/"):
        if re.fullmatch(r"\[\.\.\.[^\]]+\]|\[\[\.\.\.[^\]]+\]\]", seg):
            parts.append(".+")
        elif re.fullmatch(r"\[[^\]]+\]|:[A-Za-z_]\w*|\{[^}]+\}", seg):
            parts.append("[^/?#]+")
        else:
            parts.append(re.escape(seg))
    return "^/" + "/".join(parts) + "/?$"


def locale_for(language: Any) -> str:
    lang = str(language or "en")
    return {"de": "de-DE", "en": "en-US", "fr": "fr-FR", "es": "es-ES", "it": "it-IT"}.get(lang, lang)


def needs_login(spec: dict[str, Any]) -> bool:
    if str(spec.get("auth_type", "")).lower() not in ("", "none"):
        return True
    return any(isinstance(c, dict) and c.get("requires_auth") for c in spec.get("acceptance_criteria") or [])


def applicable(spec: dict[str, Any]) -> bool:
    return spec.get("app_type") not in ("game", "os") and "web" in (spec.get("build_targets") or ["web"])


# ─── validate ─────────────────────────────────────────────────────────────────

def validate(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not applicable(spec):
        return errors
    pages = collect_pages(spec)
    if not pages:
        errors.append("spec has no pages — list every UI route (\"/dashboard\", \"/contacts/[id]\" …); the UI tour visits them")
    demo = spec.get("demo")
    if not isinstance(demo, dict):
        errors.append("spec has no demo section — {\"seed_command\": \"npm run db:seed\", \"login_path\": \"/login\", "
                      "\"accounts\": [{\"role\": \"admin\", \"email\": …, \"password\": …}]} (one login per role)")
        return errors
    accounts = demo.get("accounts")
    if not isinstance(accounts, list):
        errors.append("demo.accounts must be a list (empty for an app without login)")
        accounts = []
    for i, acct in enumerate(accounts):
        if not isinstance(acct, dict) or not acct.get("email") or not acct.get("password"):
            errors.append(f"demo.accounts[{i}] needs email and password")
    if needs_login(spec):
        if not accounts:
            errors.append("the app has a login but demo.accounts is empty — add one demo login per role "
                          "(the first one is the account the README tells users to try)")
        if not str(demo.get("login_path") or "").startswith("/"):
            errors.append("demo.login_path is required for an app with login (e.g. \"/login\")")
    roles = {r.get("id") for r in spec.get("roles") or [] if isinstance(r, dict)}
    missing = sorted(roles - {a.get("role") for a in accounts if isinstance(a, dict)} - {None})
    if accounts and missing:
        errors.append(f"no demo login for role(s): {', '.join(missing)} — every role gets one, so the tour "
                      f"sees what each role sees")
    if demo.get("seed_command") is not None and not str(demo["seed_command"]).strip():
        errors.append("demo.seed_command is empty")
    budget = spec.get("performance_budget")
    if budget is not None:
        if not isinstance(budget, dict) or not budget or set(budget) - {"lcp_ms", "cls", "page_kb"}:
            errors.append("performance_budget takes lcp_ms, cls and/or page_kb, e.g. {\"lcp_ms\": 2500, \"cls\": 0.1, \"page_kb\": 1500}")
        elif any(not isinstance(v, (int, float)) or v < 0 for v in budget.values()):
            errors.append("performance_budget values must be non-negative numbers")
    return errors


def cmd_validate(args: argparse.Namespace) -> int:
    spec = load_spec(Path(args.spec))
    if not applicable(spec):
        log("not a web app — no UI tour")
        return 3
    errors = validate(spec)
    for e in errors:
        print(f"  ✗ {e}")
    if errors:
        log(f"{len(errors)} problem(s) in pages/demo")
        return 1
    demo = spec["demo"]
    log(f"valid — {len(collect_pages(spec))} pages, {len(demo.get('accounts') or [])} demo login(s)")
    return 0


# ─── server ───────────────────────────────────────────────────────────────────

def package_manager(project: Path) -> str:
    if (project / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project / "yarn.lock").exists():
        return "yarn"
    if (project / "bun.lockb").exists() or (project / "bun.lock").exists():
        return "bun"
    return "npm"


def free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 50)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"[tour] no free port in {preferred}-{preferred + 49}")


def reachable(url: str) -> bool:
    """Any HTTP answer means the server is up — a 500 is a finding of the tour, not a start failure."""
    try:
        with urllib.request.urlopen(url, timeout=5):  # noqa: S310 — local URL
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def production_env(base_url: str, port: int, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "ONECOMMAND_E2E"}
    env.update({"PORT": str(port), "NODE_ENV": "production", "AUTH_TRUST_HOST": "true", "CI": "true"})
    for var in SECRET_VARS:
        env.setdefault(var, secrets.token_urlsafe(48))
    for var in URL_VARS:
        env.setdefault(var, base_url)
    env.update(extra or {})
    return env


class Server:
    def __init__(self, project: Path, port: int, log_path: Path, extra_env: dict[str, str]):
        self.project, self.port, self.log_path = project, port, log_path
        self.base_url = f"http://127.0.0.1:{port}"
        self.extra_env = extra_env
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self, timeout: int) -> str | None:
        """Start `<pm> run start`; return an error message or None."""
        scripts = json.loads((self.project / "package.json").read_text()).get("scripts") or {}
        if "start" not in scripts:
            return "package.json has no start script — the tour runs the production build"
        pm = package_manager(self.project)
        self.log_fh = open(self.log_path, "wb")
        self.proc = subprocess.Popen([pm, "run", "start"], cwd=self.project, stdout=self.log_fh,
                                     stderr=subprocess.STDOUT, start_new_session=True,
                                     env=production_env(self.base_url, self.port, self.extra_env))
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return f"server exited with code {self.proc.returncode} before it answered — {self.tail()}"
            if reachable(self.base_url):
                return None
            time.sleep(1)
        return f"server did not answer on {self.base_url} within {timeout}s — {self.tail()}"

    def tail(self, lines: int = 15) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        except OSError:
            return ""
        return " | ".join(text[-lines:])

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if getattr(self, "log_fh", None):
            self.log_fh.close()


# ─── browser script ───────────────────────────────────────────────────────────

# Visible snake_case identifiers ("order_status", "knowledge_question") mean the UI shows a code value instead of
# its label. E-mail addresses, URLs and paths are not counted. Shared with the tests.
IDENTIFIER_JS = r"""
function findIdentifiers(text) {
  const found = new Set();
  for (const raw of text.split(/\s+/)) {
    if (!raw || /[@\/=]|:\/\//.test(raw)) continue;
    const w = raw.replace(/^[("'„“‚]+|[)"'“”.,:;!?…]+$/g, '');
    if (/^[a-z][a-z0-9]*(_[a-z0-9]+)+$/.test(w)) found.add(w);
  }
  return [...found];
}
"""

# Design audit, run inside every visited page. A phone-assistant build passed every functional check and still
# looked like an unfinished admin template: headings in the OS fallback serif (the CSS named only system font
# stacks), "callback"/"order_status" in monospace as chart labels, row lines missing in the actions column
# (`last:border-b-0` on the cells removes the border of the last cell in *every* row) and a sidebar whose
# background stopped halfway down the full-page screenshot. Each of these is measurable, so the tour measures it.
# Self-contained: Playwright serialises the function into the page. Shared with the tests.
DESIGN_JS = r"""
async function designAudit() {
  const out = [];
  const say = (kind, msg) => { if (!out.some((o) => o.msg === msg)) out.push({ kind, msg }); };
  try { await document.fonts.ready; } catch {}
  const visible = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const unquote = (f) => f.trim().replace(/^["']|["']$/g, '');

  // Any CSS colour syntax (rgb, oklch, color-mix …) → [r, g, b, a] via a 1×1 canvas.
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const cache = new Map();
  const rgba = (c) => {
    if (cache.has(c)) return cache.get(c);
    let v = [0, 0, 0, 0];
    if (c && c !== 'transparent') {
      cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1);
      const d = cx.getImageData(0, 0, 1, 1).data; v = [d[0], d[1], d[2], d[3] / 255];
    }
    cache.set(c, v); return v;
  };
  const blend = (top, base) => base.map((b, i) => b * (1 - top[3]) + top[i] * top[3]);
  // Background behind an element, composited up to the first opaque layer; null over images and gradients.
  const background = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage && s.backgroundImage !== 'none') return null;
      const c = rgba(s.backgroundColor);
      if (c[3] > 0) { layers.push(c); if (c[3] >= 0.99) break; }
    }
    return layers.reverse().reduce((b, c) => blend(c, b), [255, 255, 255]);
  };
  const lum = (c) => {
    const [r, g, b] = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const hex = (c) => '#' + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const ownText = (el) => [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' ').replace(/\s+/g, ' ').trim();

  // 1. Typography: text must use a font the app ships. A system stack renders differently on every OS
  //    (DejaVu on Linux, Segoe on Windows) and is the main reason generated UIs look like templates.
  const GENERIC = /^(serif|sans-serif|monospace|cursive|fantasy|system-ui|ui-serif|ui-sans-serif|ui-monospace|ui-rounded|-apple-system|blinkmacsystemfont|math|emoji)$/i;
  const loaded = new Set([...document.fonts].filter((f) => f.status === 'loaded').map((f) => unquote(f.family).toLowerCase()));
  const seen = new Set();
  for (const [what, el] of [['body text', document.body], ['headings', document.querySelector('h1, h2')]]) {
    if (!el) continue;
    const stack = getComputedStyle(el).fontFamily;
    const first = unquote(stack.split(',')[0]);
    if (seen.has(first.toLowerCase())) continue;
    seen.add(first.toLowerCase());
    if (GENERIC.test(first)) {
      say('font', `${what} use the system font stack (${stack.slice(0, 70)}) — every OS shows a different default font; ship the design's typeface with the app (next/font/local or @fontsource)`);
    } else if (!loaded.has(first.toLowerCase())) {
      say('font', `${what}: font "${first}" is not loaded by the app — visitors without it installed get a fallback font; self-host it (next/font/local or @fontsource)`);
    }
  }

  // 2. Code values in monospace ("callback", "order_status" as labels) — the UI shows data, not a label.
  const MONO = /monospace|\bmono\b|courier|consolas|menlo/i;
  const CODE = /^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$/;
  const SKIP = 'input, textarea, select, code, pre, kbd, samp, [contenteditable=true], [data-code]';
  const elements = [...document.body.querySelectorAll('*')].slice(0, 4000);
  const mono = [];
  for (const el of elements) {
    if (mono.length >= 5) break;
    const t = ownText(el);
    if (t.length < 3 || !CODE.test(t) || el.closest(SKIP) || !visible(el)) continue;
    if (MONO.test(getComputedStyle(el).fontFamily) && !mono.includes(t)) mono.push(t);
  }
  if (mono.length) say('identifier', `code values shown in monospace: ${mono.map((m) => `"${m}"`).join(', ')} — show the label (e.g. "Rückruf" for callback); monospace only for real reference numbers`);

  // 3. Contrast (WCAG AA): 4.5:1 for text, 3:1 for large text. Disabled controls are exempt.
  const low = [];
  for (const el of elements) {
    const t = ownText(el);
    if (!t || !/[\p{L}\p{N}]/u.test(t) || !visible(el)) continue;
    if (el.closest('[aria-hidden=true], :disabled, [aria-disabled=true], .sr-only')) continue;
    const s = getComputedStyle(el);
    const bg = background(el);
    if (!bg) continue;
    let alpha = 1;
    for (let e = el; e; e = e.parentElement) alpha *= parseFloat(getComputedStyle(e).opacity);
    const c = rgba(s.color);
    const fg = blend([c[0], c[1], c[2], c[3] * alpha], bg);
    const size = parseFloat(s.fontSize), weight = parseInt(s.fontWeight, 10) || 400;
    const need = size >= 24 || (size >= 18.66 && weight >= 700) ? 3 : 4.5;
    const r = ratio(fg, bg);
    if (r < need - 0.05) low.push({ t: t.slice(0, 40), r, need, fg: hex(fg), bg: hex(bg) });
  }
  low.sort((a, b) => a.r - b.r);
  const worst = low.filter((l, i) => low.findIndex((m) => m.fg === l.fg && m.bg === l.bg) === i).slice(0, 3);
  if (worst.length) say('contrast', `text contrast below WCAG AA on ${low.length} element(s): ${worst.map((l) => `"${l.t}" ${l.r.toFixed(1)}:1 (${l.fg} on ${l.bg}, needs ${l.need}:1)`).join('; ')}`);

  // 4. Table row lines must run through every column.
  for (const table of document.querySelectorAll('table')) {
    if (!visible(table)) continue;
    const rows = [...table.querySelectorAll('tbody > tr')].filter(visible);
    const heads = [...table.querySelectorAll('thead th')].map((h) => h.innerText.trim());
    for (const tr of rows.slice(0, -1)) {
      if ((parseFloat(getComputedStyle(tr).borderBottomWidth) || 0) > 0) break;
      const w = [...tr.children].map((c) => parseFloat(getComputedStyle(c).borderBottomWidth) || 0);
      const gap = w.findIndex((x) => x === 0);
      if (gap >= 0 && w.some((x) => x > 0)) {
        say('table', `table row lines stop at column ${gap + 1}${heads[gap] ? ` ("${heads[gap]}")` : ''} — a per-cell rule such as last:border-b-0 hits the last cell of every row; draw the line on the row or exclude only the last row ([&_tbody_tr:last-child_td]:border-b-0)`);
        break;
      }
    }
  }

  // 5. A sidebar's background must reach the bottom of the page (full-page screenshots, print, short pages).
  const H = document.documentElement.scrollHeight;
  if (H > innerHeight + 40) {
    for (const el of document.querySelectorAll('aside, nav, [data-sidebar], [role=navigation]')) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      const edge = r.left <= 2 || r.right >= innerWidth - 2;
      if (!edge || r.width < 120 || r.width > innerWidth * 0.4 || r.top + scrollY > 80 || r.height < innerHeight * 0.6) continue;
      if (rgba(getComputedStyle(el).backgroundColor)[3] < 0.5) continue;
      const bottom = Math.round(r.bottom + scrollY);
      if (H - bottom > 24) {
        say('layout', `the sidebar background ends at ${bottom}px, above the page bottom — put the background on the full-height grid column and make only the inner navigation sticky`);
        break;
      }
    }
  }
  return out;
}
"""

TOUR_JS = r"""
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
// Resolve Playwright from the project, wherever this script was written.
const req = createRequire(path.join(cfg.project_dir, 'package.json'));
let pw;
try { pw = req('@playwright/test'); } catch { pw = req('playwright'); }
const { chromium } = pw;
const origin = new URL(cfg.base_url).origin;
const BAD_TEXT = /(?<![\w-])(undefined|NaN|Invalid Date|\[object Object\]|lorem ipsum)(?![\w-])/gi;
const out = { logins: [], visits: [] };
let shot = 0;

function slug(s) { return (s || 'root').replace(/^\/+/, '').replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'root'; }

async function visit(page, acct, vp, target, pattern) {
  const rec = { account: acct ? acct.email : null, role: acct ? (acct.role || null) : null, viewport: vp.name,
                path: target, pattern: pattern || null, issues: [], warnings: [], console_errors: [] };
  const pageErrors = [], bad = [];
  const onConsole = (m) => { if (m.type() === 'error') rec.console_errors.push(m.text().slice(0, 300)); };
  const onError = (e) => pageErrors.push(String((e && e.message) || e).slice(0, 300));
  const onResponse = (r) => {
    try {
      const u = new URL(r.url());
      if (u.origin === origin && r.status() >= 500) bad.push(`${r.status()} ${r.request().method()} ${u.pathname}`);
    } catch {}
  };
  page.on('console', onConsole); page.on('pageerror', onError); page.on('response', onResponse);
  let resp = null;
  try {
    resp = await page.goto(cfg.base_url + target, { waitUntil: 'networkidle', timeout: cfg.nav_timeout_ms });
  } catch (e) {
    try { resp = await page.goto(cfg.base_url + target, { waitUntil: 'load', timeout: cfg.nav_timeout_ms }); }
    catch (e2) { rec.issues.push(`navigation failed: ${String(e2.message || e2).split('\n')[0]}`); }
  }
  await page.waitForTimeout(cfg.settle_ms);
  rec.status = resp ? resp.status() : null;
  if (page._ocBudget) {
    try {
      rec.performance = await page.evaluate(async () => {
        let lcp = 0, cls = 0;
        try { new PerformanceObserver((l) => { for (const e of l.getEntries()) lcp = e.renderTime || e.loadTime || e.startTime; })
                .observe({ type: 'largest-contentful-paint', buffered: true }); } catch {}
        try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) cls += e.value; })
                .observe({ type: 'layout-shift', buffered: true }); } catch {}
        await new Promise((r) => setTimeout(r, 300));
        const nav = performance.getEntriesByType('navigation')[0];
        let bytes = nav ? nav.transferSize : 0;
        for (const r of performance.getEntriesByType('resource')) {
          if (!['video', 'audio'].includes(r.initiatorType)) bytes += r.transferSize || 0;  // videos have their own budget
        }
        return { lcp_ms: Math.round(lcp), cls: Math.round(cls * 1000) / 1000, page_kb: Math.round(bytes / 1024) };
      });
      const b = page._ocBudget, m = rec.performance;
      if (b.lcp_ms && m.lcp_ms > b.lcp_ms) rec.issues.push(`performance budget: LCP ${m.lcp_ms} ms > ${b.lcp_ms} ms`);
      if (b.cls !== undefined && m.cls > b.cls) rec.issues.push(`performance budget: CLS ${m.cls} > ${b.cls}`);
      if (b.page_kb && m.page_kb > b.page_kb) rec.issues.push(`performance budget: ${m.page_kb} KB transferred > ${b.page_kb} KB (without video)`);
    } catch (e) { rec.warnings.push(`performance not measured: ${String(e.message || e).split('\n')[0]}`); }
  }
  rec.final_path = new URL(page.url()).pathname;
  shot += 1;
  const file = `${String(shot).padStart(3, '0')}-${slug(acct ? (acct.role || acct.email.split('@')[0]) : 'anon')}-${vp.name}-${slug(target)}.png`;
  try { await page.screenshot({ path: path.join(cfg.out_dir, file), fullPage: true, timeout: 30000 }); rec.screenshot = file; }
  catch (e) { rec.warnings.push(`screenshot failed: ${String(e.message || e).split('\n')[0]}`); }
  let text = '';
  try { text = await page.evaluate(() => (document.body ? document.body.innerText : '')); } catch {}
  rec.design = [];
  const ids = findIdentifiers(text);
  if (ids.length) rec.design.push({ kind: 'identifier', msg: `technical identifiers visible: ${ids.slice(0, 5).map((i) => `"${i}"`).join(', ')} — show the user-facing label (e.g. the German intent / status name), not the code value` });
  try { rec.design.push(...await page.evaluate(designAudit)); }
  catch (e) { rec.warnings.push(`design audit failed: ${String(e.message || e).split('\n')[0]}`); }
  const hits = [...new Set((text.match(BAD_TEXT) || []).map((s) => s.trim()))];
  if (hits.length) rec.issues.push(`visible text shows ${hits.map((h) => `"${h}"`).join(', ')} — a value is missing or mis-parsed`);
  const labels = (acct === null || acct.email === cfg.first_account) && vp.name === 'desktop' ? (cfg.metric_labels[target] || []) : [];
  const lower = text.toLowerCase();
  for (const m of labels) {
    if (!lower.includes(m.label.toLowerCase())) rec.issues.push(`metric ${m.id} is not labelled "${m.label}" on this page (spec.metrics: one label, naming the period)`);
  }
  if (vp.name === 'mobile') {
    try {
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 2) rec.warnings.push(`page is ${overflow}px wider than the ${vp.width}px viewport (horizontal scrolling)`);
    } catch {}
  }
  try {
    rec.links = await page.evaluate(() => Array.from(document.querySelectorAll('a[href]')).map((a) => a.getAttribute('href')));
  } catch { rec.links = []; }
  if (rec.status !== null && rec.status >= 500) rec.issues.push(`HTTP ${rec.status}`);
  for (const e of pageErrors) rec.issues.push(`uncaught exception: ${e}`);
  for (const b of [...new Set(bad)]) rec.issues.push(`server error from ${b}`);
  if (acct && cfg.login_path && rec.final_path.startsWith(cfg.login_path) && !target.startsWith(cfg.login_path)) {
    rec.issues.push(`redirected to ${cfg.login_path} although logged in — session lost`);
  }
  page.off('console', onConsole); page.off('pageerror', onError); page.off('response', onResponse);
  out.visits.push(rec);
  return rec;
}

async function login(ctx, acct) {
  const page = await ctx.newPage();
  const rec = { account: acct.email, role: acct.role || null, ok: false };
  try {
    await page.goto(cfg.base_url + cfg.login_path, { waitUntil: 'networkidle', timeout: cfg.nav_timeout_ms });
    await page.locator('input[type=email], input[name=email], input[autocomplete=username], input[autocomplete=email], input[name=username]').first().fill(acct.email);
    await page.locator('input[type=password]').first().fill(acct.password);
    const left = page.waitForURL((u) => !new URL(u).pathname.startsWith(cfg.login_path), { timeout: cfg.login_timeout_ms }).catch(() => null);
    const submit = page.locator('form button[type=submit], button[type=submit]').first();
    if (await submit.count()) await submit.click(); else await page.keyboard.press('Enter');
    await left;
    await page.waitForLoadState('networkidle', { timeout: cfg.nav_timeout_ms }).catch(() => null);
    rec.landing = new URL(page.url()).pathname;
    rec.ok = !rec.landing.startsWith(cfg.login_path);
    if (!rec.ok) {
      shot += 1;
      rec.screenshot = `${String(shot).padStart(3, '0')}-${slug(acct.role || acct.email)}-login-failed.png`;
      await page.screenshot({ path: path.join(cfg.out_dir, rec.screenshot), fullPage: true }).catch(() => null);
      rec.error = (await page.evaluate(() => {
        const el = document.querySelector('[role=alert], .error, [data-error], form p');
        return el ? el.innerText : '';
      }).catch(() => '')).slice(0, 200);
    }
  } catch (e) {
    rec.error = String(e.message || e).split('\n')[0];
  }
  out.logins.push(rec);
  await page.close();
  return rec;
}

async function tour(acct, vp, pages) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, locale: cfg.locale,
                                         ignoreHTTPSErrors: true, deviceScaleFactor: 1 });
  try {
    if (acct) {
      const l = await login(ctx, acct);
      if (!l.ok) return;
    }
    const page = await ctx.newPage();
    // Performance budget: first visit (no cache) on a realistic line, desktop only.
    if (cfg.performance_budget && vp.name === 'desktop' && (!acct || acct.email === cfg.first_account)) {
      try {
        const cdp = await ctx.newCDPSession(page);
        await cdp.send('Network.enable');
        await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
        await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 40,
          downloadThroughput: 10 * 1024 * 1024 / 8, uploadThroughput: 5 * 1024 * 1024 / 8 });
        page._ocBudget = cfg.performance_budget;
      } catch (e) { /* non-Chromium: measured without throttling */ page._ocBudget = cfg.performance_budget; }
    }
    const links = new Set();
    for (const p of pages.static) {
      const rec = await visit(page, acct, vp, p);
      (rec.links || []).forEach((h) => links.add(h));
    }
    for (const d of pages.dynamic) {
      const re = new RegExp(d.regex);
      const hit = [...links].map((h) => { try { return new URL(h, cfg.base_url); } catch { return null; } })
        .filter((u) => u && u.origin === origin && re.test(u.pathname) && !pages.static.includes(u.pathname))[0];
      if (!hit) {
        out.visits.push({ account: acct ? acct.email : null, role: acct ? (acct.role || null) : null, viewport: vp.name,
                          path: d.path, pattern: d.path, issues: [], unresolved: true,
                          warnings: [`no link to ${d.path} on any visited page — demo data missing, or no list links to it`] });
        continue;
      }
      await visit(page, acct, vp, hit.pathname, d.path);
    }
  } finally {
    await ctx.close();
  }
}

// --lang: native controls (date fields, number formats) follow the browser process locale, not the context's.
const browser = await chromium.launch({ args: [`--lang=${cfg.locale}`] });
try {
  if (cfg.anonymous.static.length || cfg.anonymous.dynamic.length) {
    await tour(null, cfg.desktop, cfg.anonymous);
    if (cfg.mobile_anonymous) await tour(null, cfg.mobile, cfg.anonymous);
  }
  cfg.accounts.forEach((a, i) => { a._i = i; });
  for (const acct of cfg.accounts) {
    await tour(acct, cfg.desktop, cfg.private);
    if (acct._i < cfg.mobile_accounts) await tour(acct, cfg.mobile, cfg.private);
  }
} finally {
  await browser.close();
  fs.writeFileSync(path.join(cfg.out_dir, 'tour.json'), JSON.stringify(out, null, 2));
}
"""


# ─── run ──────────────────────────────────────────────────────────────────────

def has_playwright(project: Path) -> bool:
    return any((project / "node_modules" / name / "package.json").exists() for name in ("@playwright/test", "playwright"))


def metric_labels(spec: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """page → metrics whose label must be visible there (spec.metrics[].shown_on)."""
    result: dict[str, list[dict[str, str]]] = {}
    for m in spec.get("metrics") or []:
        if not isinstance(m, dict) or not m.get("label"):
            continue
        for page in m.get("shown_on") or []:
            path = page_path(page)
            if path and not is_dynamic(path):
                result.setdefault(path, []).append({"id": str(m.get("id")), "label": str(m["label"])})
    return result


def split_pages(pages: list[str], login_path: str | None, with_accounts: bool) -> tuple[dict, dict]:
    anon: dict[str, list] = {"static": [], "dynamic": []}
    priv: dict[str, list] = {"static": [], "dynamic": []}
    for p in pages:
        if LOGOUT.search(p):
            continue
        public = bool(AUTH_PAGES.search(p)) or (login_path is not None and p.startswith(login_path))
        bucket = anon if (public or not with_accounts) else priv
        if is_dynamic(p):
            bucket["dynamic"].append({"path": p, "regex": pattern_regex(p)})
        else:
            bucket["static"].append(p)
    return anon, priv


def evaluate(data: dict[str, Any], first_account: str | None) -> tuple[list[str], list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    for login in data.get("logins", []):
        if not login.get("ok"):
            blocking.append(f"login failed for {login['account']} ({login.get('role') or 'no role'})"
                            + (f": {login['error']}" if login.get("error") else "")
                            + (f" — see {login['screenshot']}" if login.get("screenshot") else ""))
    for v in data.get("visits", []):
        who = f"{v.get('role') or v.get('account') or 'anonymous'} · {v['viewport']} · {v['path']}"
        status = v.get("status")
        if status in (401, 403, 404) and v.get("account") and v["account"] != first_account:
            notes.append(f"{who}: HTTP {status} (restricted for this role)")
        elif status in (401, 403, 404):
            blocking.append(f"{who}: HTTP {status} — a page of the spec is missing or not reachable")
        for issue in v.get("issues", []):
            blocking.append(f"{who}: {issue}")
        for w in v.get("warnings", []):
            warnings.append(f"{who}: {w}")
        errs = v.get("console_errors") or []
        if not v.get("account") and AUTH_PAGES.search(v.get("path", "")):
            errs = [e for e in errs if "status of 401" not in e]  # session probe on a login page: expected
        if errs:
            warnings.append(f"{who}: {len(errs)} console error(s): {errs[0][:160]}")
    return blocking, warnings, notes


def design_findings(data: dict[str, Any]) -> list[str]:
    """Design-audit results of all visits, one line per distinct finding with the pages it occurs on."""
    pages: dict[str, list[str]] = {}
    for v in data.get("visits", []):
        for d in v.get("design") or []:
            where = f"{v['path']} ({v['viewport']})"
            pages.setdefault(d["msg"], [])
            if where not in pages[d["msg"]]:
                pages[d["msg"]].append(where)
    return [f"{msg} — on {', '.join(w[:4])}{f' and {len(w) - 4} more' if len(w) > 4 else ''}"
            for msg, w in pages.items()]


def write_reports(out_dir: Path, spec: dict[str, Any], data: dict[str, Any], blocking: list[str],
                  warnings: list[str], notes: list[str], first_account: str | None) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    visits = data.get("visits", [])
    report = {"version": 1, "finished_at": now, "passed": not blocking, "blocking": blocking,
              "warnings": warnings, "notes": notes, "logins": data.get("logins", []),
              "visits": [{k: v for k, v in visit.items() if k != "links"} for visit in visits]}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md = [f"# UI tour — {spec.get('project_name', 'app')}", "",
          f"{now} · {len(visits)} page views · {len(data.get('logins', []))} logins · "
          f"{'✅ no blocking problems' if not blocking else f'❌ {len(blocking)} blocking problem(s)'}", ""]
    if blocking:
        md += ["## Blocking", ""] + [f"- ✗ {b}" for b in blocking] + [""]
    design = design_findings(data)
    report["design"] = design
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if design:
        md += ["## Design", ""] + [f"- ✗ {d}" for d in design] + [""]
    if warnings:
        md += ["## Warnings", ""] + [f"- ⚠ {w}" for w in warnings] + [""]
    md += ["## Pages", "", "| Account | Viewport | Page | HTTP | LCP | CLS | KB | Screenshot |",
           "|---|---|---|---|---|---|---|---|"]
    for v in visits:
        perf = v.get("performance") or {}
        md.append(f"| {v.get('role') or v.get('account') or 'anonymous'} | {v['viewport']} | {v['path']} | "
                  f"{v.get('status', '—')} | {perf.get('lcp_ms', '—')} | {perf.get('cls', '—')} | "
                  f"{perf.get('page_kb', '—')} | {v.get('screenshot', '—')} |")
    md += ["", "---", "*OneCommand UI-Rundgang · USC Software UG · usc-software-ug.de*"]
    (out_dir / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # Review list: everything the first account and anonymous visitors see (desktop + mobile),
    # plus the landing page of every other role. The rest is covered by the automated checks.
    review = [f"# UI review — {spec.get('project_name', 'app')}", "", REVIEW_CHECKS, "## Screenshots", ""]
    seen_roles: set[str] = set()
    for v in visits:
        if not v.get("screenshot"):
            continue
        account = v.get("account")
        if account and account != first_account:
            key = f"{account}/{v['viewport']}"
            if key in seen_roles:
                continue
            seen_roles.add(key)
        who = v.get("role") or account or "anonymous"
        review.append(f"- [ ] {v['screenshot']} — {who} · {v['viewport']} · {v['path']}")
    if design:
        # Measured, not judged: these stay open until a re-run of the tour no longer finds them.
        review += ["", "## Design audit (measured — fix the code and re-run the tour; do not tick or delete)", "",
                   "- design-audit — automated checks: fonts, code values, contrast, table lines, sidebar"]
        review += [f"  - ✗ {d}" for d in design]
    (out_dir / "review.md").write_text("\n".join(review) + "\n", encoding="utf-8")


def run_seed(project: Path, command: str, timeout: int, log_path: Path) -> str | None:
    env = {k: v for k, v in os.environ.items() if k != "ONECOMMAND_E2E"}
    env["SEED_MODE"] = "demo"
    log(f"▶ demo seed: {command}")
    with open(log_path, "wb") as fh:
        try:
            rc = subprocess.run(command, shell=True, cwd=project, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return f"demo seed timed out after {timeout}s (log: {log_path})"
    if rc != 0:
        tail = " | ".join(log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-10:])
        return f"demo seed failed with exit code {rc}: {tail}"
    return None


def cmd_run(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    spec_path = Path(args.spec) if os.path.isabs(args.spec) else project / args.spec
    spec = load_spec(spec_path)
    if not applicable(spec) or not isinstance(spec.get("demo"), dict):
        log("spec has no demo section (or is not a web app) — not applicable")
        return 3
    errors = validate(spec)
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        log("fix pages/demo in the spec first (ui-tour.py validate)")
        return 1
    if not has_playwright(project):
        print("  ✗ neither @playwright/test nor playwright is installed in the project")
        return 1
    if not shutil.which("node"):
        print("  ✗ node is not on PATH")
        return 1

    out_dir = Path(args.out).resolve() if args.out else project / ".onecommand" / "tour"
    if out_dir.exists():
        # Nothing from an earlier run may be mistaken for this run's result.
        for old in list(out_dir.glob("*.png")) + [out_dir / n for n in ("tour.json", "report.json", "report.md", "review.md")]:
            old.unlink(missing_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    demo = spec["demo"]
    accounts = [a for a in demo.get("accounts") or [] if isinstance(a, dict)]
    login_path = demo.get("login_path") if accounts else None
    pages = collect_pages(spec)
    anon, priv = split_pages(pages, login_path, bool(accounts))

    if not args.no_seed and demo.get("seed_command"):
        problem = run_seed(project, str(demo["seed_command"]), args.seed_timeout, out_dir / "seed.log")
        if problem:
            print(f"  ✗ {problem}")
            return 1

    server = None
    base_url = args.base_url
    try:
        if not base_url:
            port = free_port(args.port)
            server = Server(project, port, out_dir / "server.log", {})
            log(f"▶ production server on port {port} (fresh secrets, NODE_ENV=production)")
            problem = server.start(args.start_timeout)
            if problem:
                print(f"  ✗ {problem}")
                return 1
            base_url = server.base_url
        cfg = {
            "base_url": base_url.rstrip("/"), "out_dir": str(out_dir), "project_dir": str(project),
            "login_path": login_path, "first_account": accounts[0]["email"] if accounts else None,
            "metric_labels": metric_labels(spec),
            "performance_budget": spec.get("performance_budget") or None,
            "accounts": accounts, "anonymous": anon, "private": priv,
            "mobile_accounts": max(0, args.mobile_accounts), "mobile_anonymous": not accounts or bool(anon["static"]),
            "desktop": DESKTOP, "mobile": MOBILE, "locale": locale_for(spec.get("ui_language")),
            "nav_timeout_ms": args.nav_timeout * 1000, "login_timeout_ms": 20000, "settle_ms": 500,
        }
        (out_dir / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        script = out_dir / "tour.mjs"
        script.write_text(TOUR_JS + IDENTIFIER_JS + DESIGN_JS, encoding="utf-8")
        total = len(anon["static"]) + len(anon["dynamic"]) + len(accounts) * (len(priv["static"]) + len(priv["dynamic"]))
        log(f"▶ visiting {total} page(s) with {len(accounts)} demo login(s)")
        try:
            proc = subprocess.run(["node", str(script), str(out_dir / "config.json")], cwd=project,
                                  capture_output=True, text=True, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            print(f"  ✗ tour timed out after {args.timeout}s")
            return 1
        if args.verbose and proc.stdout.strip():
            print(proc.stdout)
        if proc.returncode != 0 or not (out_dir / "tour.json").exists():
            print(f"  ✗ browser tour crashed (exit {proc.returncode}): {(proc.stderr or proc.stdout).strip()[-1500:]}")
            return 1
    finally:
        if server:
            server.stop()

    data = json.loads((out_dir / "tour.json").read_text(encoding="utf-8"))
    first = accounts[0]["email"] if accounts else None
    blocking, warnings, notes = evaluate(data, first)
    write_reports(out_dir, spec, data, blocking, warnings, notes, first)
    for n in notes:
        print(f"  ○ {n}")
    for w in warnings:
        print(f"  ⚠ {w}")
    design = design_findings(data)
    for d in design:
        print(f"  ✗ design: {d}")
    for b in blocking:
        print(f"  ✗ {b}")
    shots = len(list(out_dir.glob("*.png")))
    if blocking:
        log(f"error: {len(blocking)} blocking problem(s) — {out_dir / 'report.md'}")
        return 1
    log(f"{shots} screenshots, no blocking problems"
        + (f", {len(design)} design finding(s) open (review-status fails until a re-run no longer finds them)"
           if design else "")
        + f" — now review them: {out_dir / 'review.md'}")
    return 0


# ─── review-status ────────────────────────────────────────────────────────────

def cmd_review_status(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    review = (Path(args.out).resolve() if args.out else project / ".onecommand" / "tour") / "review.md"
    if not review.exists():
        log(f"{review} not found — run the tour first")
        return 1
    text = review.read_text(encoding="utf-8")
    unchecked = re.findall(r"^- \[ \] (\S+)", text, re.M)
    # A tick without a note ("→ ok: …" or "→ see findings") was not really looked at.
    unchecked += re.findall(r"^- \[[xX]\] (\S+)(?:(?!→).)*$", text, re.M)
    open_findings = re.findall(r"^\s+- ✗ (.+)$", text, re.M)
    total = len(re.findall(r"^- \[[ xX]\] ", text, re.M))
    for f in open_findings:
        print(f"  ✗ open finding: {f}")
    if unchecked:
        print(f"  ○ not reviewed yet: {', '.join(unchecked[:10])}{' …' if len(unchecked) > 10 else ''}")
    if unchecked or open_findings:
        log(f"review incomplete — {total - len(unchecked)}/{total} screenshots reviewed, {len(open_findings)} open finding(s)")
        return 1
    log(f"review complete — {total} screenshots reviewed, no open findings")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check spec pages and demo accounts")
    p.add_argument("--spec", default=".onecommand-spec.json")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("run", help="seed demo data, start the production server, screenshot every page")
    p.add_argument("--project-dir", default=".")
    p.add_argument("--spec", default=".onecommand-spec.json")
    p.add_argument("--out", help="output directory (default <project>/.onecommand/tour)")
    p.add_argument("--base-url", help="use an already running app instead of starting `npm run start`")
    p.add_argument("--port", type=int, default=3210)
    p.add_argument("--no-seed", action="store_true", help="skip demo.seed_command")
    p.add_argument("--mobile-accounts", type=int, default=1, help="accounts that also get mobile screenshots (default 1)")
    p.add_argument("--seed-timeout", type=int, default=600)
    p.add_argument("--start-timeout", type=int, default=120)
    p.add_argument("--nav-timeout", type=int, default=30, help="seconds per page load")
    p.add_argument("--timeout", type=int, default=1800, help="seconds for the whole browser tour")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("review-status", help="is every screenshot reviewed and every finding fixed?")
    p.add_argument("--project-dir", default=".")
    p.add_argument("--out")
    p.set_defaults(func=cmd_review_status)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
