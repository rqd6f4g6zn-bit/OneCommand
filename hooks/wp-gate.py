#!/usr/bin/env python3
"""OneCommand WordPress gate — the pass/fail verdict for WordPress websites.

quality-gate.sh hands over to this script when the spec has a "wordpress" section.
A WordPress site is only "done" when its theme and plugins are clean PHP, follow
WordPress's security rules (escaping, nonces, prepared SQL, no direct file access),
ship their fonts and assets themselves, and when the real site — WordPress core,
the project's theme, plugins and demo content — runs and passes the acceptance tests
and the UI tour (screenshots, design audit, performance budget).

No Docker and no MySQL: the site runs on PHP's built-in server with the official
SQLite database integration, WordPress core fetched once into ~/.onecommand/cache.

Project layout (written by the wordpress-builder skill):
  wordpress/themes/<theme>/       block theme: style.css, theme.json, templates/, parts/, patterns/
  wordpress/plugins/<slug>/       own plugins (site plugin with CPTs, custom blocks, settings)
  wordpress/seed.php              demo content, idempotent (runs after wp-load.php)
  package.json                    @wordpress/scripts (blocks), @playwright/test (acceptance)

Spec section:
  "wordpress": {
    "version": "6.8",                       # WordPress core branch
    "theme": "nordlicht",
    "plugins": ["nordlicht-core"],          # own plugins, activated in this order
    "third_party_plugins": ["wordpress-seo"],  # from wordpress.org; counted against plugin_budget
    "plugin_budget": 6,
    "seed": "wordpress/seed.php",
    "build": "npm run build",               # optional: builds blocks/assets before the site starts
    "allow_external_assets": []             # hosts the site may load from (default: none)
  }
  Users come from spec "demo.accounts" (role = WordPress role, e.g. administrator, editor).

Subcommands
-----------
fetch    Cache WordPress core and the SQLite integration (git, works without wordpress.org).
static   Lint and security checks on the project's theme and plugins.
serve    Boot the site on http://127.0.0.1:<port> and keep it running (Ctrl-C stops it).
gate     The verdict for quality-gate.sh: --stage static|e2e|tour|all → .onecommand/gate/result.json

Exit codes: 0 passed · 1 failed · 2 usage error · 3 not applicable (no "wordpress" in the spec)
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

HOOKS = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("ONECOMMAND_WP_CACHE", Path.home() / ".onecommand" / "cache" / "wordpress"))
CORE_REPO = "https://github.com/WordPress/WordPress"
SQLITE_REPO = "https://github.com/WordPress/sqlite-database-integration"
PAGE_BUILDERS = ("elementor", "js_composer", "divi-builder", "beaver-builder-lite-version", "wpbakery", "oxygen",
                 "bricks", "thrive-visual-editor")
ERROR_LINE = re.compile(r"(error|fatal|warning|failed|✗|exception)", re.I)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[wp-gate] {msg}", flush=True)


def load_spec(project: Path) -> dict[str, Any]:
    path = project / ".onecommand-spec.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wp_section(spec: dict[str, Any]) -> dict[str, Any] | None:
    wp = spec.get("wordpress")
    return wp if isinstance(wp, dict) else None


# ─── fetch ────────────────────────────────────────────────────────────────────

def git_clone(url: str, dest: Path, branch: str | None) -> str | None:
    cmd = ["git", "clone", "-q", "--depth", "1"] + (["--branch", branch] if branch else []) + [url, str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"})
    return None if r.returncode == 0 else (r.stderr or r.stdout).strip()[-400:]


def fetch(version: str) -> tuple[Path, Path]:
    """WordPress core for `version` and the SQLite plugin, cached. Raises SystemExit on failure."""
    core = CACHE / f"core-{version}"
    if not (core / "wp-includes" / "version.php").exists():
        log(f"fetching WordPress {version} (git, once) → {core}")
        shutil.rmtree(core, ignore_errors=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        err = git_clone(CORE_REPO, core, version)
        if err:
            raise SystemExit(f"[wp-gate] cannot fetch WordPress {version}: {err}")
    sqlite = CACHE / "sqlite-database-integration"
    plugin = sqlite / "packages" / "plugin-sqlite-database-integration"
    if not (plugin / "db.copy").exists():
        log("fetching the SQLite database integration (git, once)")
        shutil.rmtree(sqlite, ignore_errors=True)
        err = git_clone(SQLITE_REPO, sqlite, None)
        if err:
            raise SystemExit(f"[wp-gate] cannot fetch the SQLite integration: {err}")
    return core, plugin


def fetch_plugin(slug: str) -> Path | None:
    """A wordpress.org plugin, cached; None when wordpress.org is unreachable."""
    dest = CACHE / "plugins" / slug
    if (dest / f"{slug}.php").exists() or any(dest.glob("*.php")):
        return dest
    url = f"https://downloads.wordpress.org/plugin/{slug}.latest-stable.zip"
    zpath = CACHE / "plugins" / f"{slug}.zip"
    try:
        zpath.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as resp, open(zpath, "wb") as fh:
            shutil.copyfileobj(resp, fh)
        shutil.unpack_archive(str(zpath), str(CACHE / "plugins"))
        return dest if dest.exists() else None
    except (urllib.error.URLError, OSError, shutil.ReadError, ValueError) as exc:
        log(f"  ⚠ plugin {slug} not available ({exc}) — the site runs without it")
        return None


def cmd_fetch(args: argparse.Namespace) -> int:
    core, plugin = fetch(args.wp_version)
    log(f"WordPress: {core}\n[wp-gate] SQLite: {plugin}")
    return 0


# ─── static checks ────────────────────────────────────────────────────────────

ESC = r"esc_(html|attr|url|js|textarea|xml)|wp_kses|wp_kses_post|esc_html__|esc_attr__|esc_html_e|esc_attr_e|absint|intval|wp_json_encode|number_format_i18n|get_the_|the_|wp_nonce_field|selected|checked|disabled|sanitize_"
ECHO_RAW = re.compile(r"\becho\s+(\$[A-Za-z_][\w\->\[\]'\"]*)\s*;")
ECHO_CONCAT = re.compile(r"\becho\s+[^;]*\.\s*\$[A-Za-z_]")
SQL_INTERP = re.compile(r"\$wpdb->(query|get_results|get_row|get_var|get_col)\(\s*\"[^\"]*\$[A-Za-z_]")
SUPERGLOBAL = re.compile(r"\$_(GET|POST|REQUEST)\[")
DANGEROUS = re.compile(r"\b(eval|create_function|assert)\s*\(|base64_decode\s*\(\s*\$")
EXTERNAL = re.compile(r"https?://(fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit\.net|cdn\.jsdelivr\.net|"
                      r"cdnjs\.cloudflare\.com|code\.jquery\.com|unpkg\.com|ajax\.googleapis\.com)")


def php_files(root: Path) -> list[Path]:
    skip = ("node_modules", "vendor", "build", ".onecommand")
    return sorted(p for p in root.rglob("*.php") if not any(s in p.parts for s in skip))


def static_problems(project: Path, wp: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    base = project / "wordpress"
    theme_slug = wp.get("theme")
    theme = base / "themes" / str(theme_slug)
    if not theme_slug or not theme.is_dir():
        errors.append(f"theme: wordpress/themes/{theme_slug} does not exist (spec wordpress.theme)")
    else:
        style = theme / "style.css"
        head = style.read_text(encoding="utf-8", errors="replace")[:2000] if style.exists() else ""
        for key in ("Theme Name:", "Text Domain:", "Version:", "Requires at least:"):
            if key not in head:
                errors.append(f"theme: style.css header lacks '{key}'")
        tj = theme / "theme.json"
        try:
            data = json.loads(tj.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"theme: theme.json missing or invalid ({exc})")
            data = {}
        if data:
            if data.get("version", 0) < 3:
                errors.append("theme: theme.json version must be 3 (WordPress 6.6+)")
            settings = data.get("settings") or {}
            palette = (settings.get("color") or {}).get("palette") or []
            if len(palette) < 3:
                errors.append("theme: theme.json settings.color.palette needs the brand palette from the design brief (≥ 3 colours)")
            families = (settings.get("typography") or {}).get("fontFamilies") or []
            faces = [f for fam in families for f in fam.get("fontFace") or []]
            if not faces:
                errors.append("theme: no self-hosted font — theme.json typography.fontFamilies[].fontFace with src "
                              "'file:./assets/fonts/…' (the system font stack looks like a template)")
            for face in faces:
                for src in face.get("src") or []:
                    if isinstance(src, str) and src.startswith("file:./") and not (theme / src[7:]).exists():
                        errors.append(f"theme: font file {src[7:]} missing")
                    elif isinstance(src, str) and src.startswith("http"):
                        errors.append(f"theme: font loaded from {src} — host it in the theme (GDPR: no remote font requests)")
            if not (settings.get("layout") or {}).get("contentSize"):
                warnings.append("theme: theme.json settings.layout.contentSize not set")
        if not (theme / "templates" / "index.html").exists():
            errors.append("theme: templates/index.html missing (block theme)")
        for part in ("header", "footer"):
            if not (theme / "parts" / f"{part}.html").exists():
                errors.append(f"theme: parts/{part}.html missing")
        if not list((theme / "patterns").glob("*.php")) if (theme / "patterns").exists() else True:
            warnings.append("theme: no block patterns — editors get no ready-made sections")
    for slug in wp.get("plugins") or []:
        pdir = base / "plugins" / slug
        main = pdir / f"{slug}.php"
        if not main.exists():
            errors.append(f"plugin {slug}: main file wordpress/plugins/{slug}/{slug}.php missing")
        elif "Plugin Name:" not in main.read_text(encoding="utf-8", errors="replace")[:2000]:
            errors.append(f"plugin {slug}: main file has no 'Plugin Name:' header")
        for bj in pdir.rglob("block.json"):
            if "node_modules" in bj.parts:
                continue
            try:
                block = json.loads(bj.read_text(encoding="utf-8"))
            except ValueError as exc:
                errors.append(f"{bj.relative_to(project)}: invalid JSON ({exc})")
                continue
            if block.get("apiVersion", 0) < 3 or "/" not in str(block.get("name", "")) or not block.get("textdomain"):
                errors.append(f"{bj.relative_to(project)}: needs apiVersion 3, a namespaced name and a textdomain")
    third = wp.get("third_party_plugins") or []
    builders = [p for p in third if p in PAGE_BUILDERS]
    if builders and not wp.get("allow_page_builder"):
        errors.append(f"page builder plugins {builders}: they slow the site and lock the content in — build blocks "
                      "and patterns instead (only with the customer's explicit request: wordpress.allow_page_builder)")
    budget = int(wp.get("plugin_budget", 8))
    if len(third) > budget:
        errors.append(f"{len(third)} third-party plugins exceed the plugin budget of {budget} — every plugin is an "
                      "update and security liability")
    allowed = set(wp.get("allow_external_assets") or [])
    for path in php_files(base) + sorted(base.rglob("*.html")) + sorted(base.rglob("*.css")) + sorted(base.rglob("*.json")):
        if any(s in path.parts for s in ("node_modules", "vendor", ".onecommand")):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(project)
        for m in EXTERNAL.finditer(text):
            if m.group(1) not in allowed:
                errors.append(f"{rel}: loads {m.group(0)} — self-host it (GDPR, performance)")
                break
        if path.suffix != ".php":
            continue
        is_plugin = "plugins" in path.relative_to(base).parts[:1]
        is_template = "patterns" in path.parts or "templates" in path.parts or "parts" in path.parts
        if is_plugin and not re.search(r"defined\(\s*['\"](ABSPATH|WPINC)['\"]\s*\)", text):
            errors.append(f"{rel}: no direct-access guard — add `defined( 'ABSPATH' ) || exit;` at the top")
        for i, line in enumerate(text.splitlines(), 1):
            if DANGEROUS.search(line):
                errors.append(f"{rel}:{i}: dangerous call ({line.strip()[:80]})")
            if SQL_INTERP.search(line) and "prepare" not in line:
                errors.append(f"{rel}:{i}: SQL with an interpolated variable — use $wpdb->prepare()")
            m = ECHO_RAW.search(line)
            if (m or ECHO_CONCAT.search(line)) and not re.search(ESC, line) and not is_template:
                errors.append(f"{rel}:{i}: output without escaping — wrap in esc_html()/esc_attr()/esc_url()/wp_kses_post()")
        if SUPERGLOBAL.search(text):
            if not re.search(r"sanitize_|absint|intval|wp_unslash|filter_input", text):
                errors.append(f"{rel}: reads $_GET/$_POST without sanitizing (sanitize_text_field(wp_unslash(…)))")
            if re.search(r"\$_POST\[", text) and not re.search(r"wp_verify_nonce|check_admin_referer|check_ajax_referer", text):
                errors.append(f"{rel}: handles $_POST without a nonce check (wp_verify_nonce / check_admin_referer)")
    return errors, warnings


def php_lint(project: Path) -> list[str]:
    if not shutil.which("php"):
        return ["php is not on PATH — install PHP 8.1+ (WordPress and this gate need it)"]
    errors = []
    for path in php_files(project / "wordpress"):
        r = subprocess.run(["php", "-l", str(path)], capture_output=True, text=True)
        if r.returncode != 0:
            errors.append(f"{path.relative_to(project)}: {(r.stdout + r.stderr).strip().splitlines()[0][:200]}")
    return errors


def cmd_static(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    wp = wp_section(load_spec(project))
    if wp is None:
        log("spec has no wordpress section — not applicable")
        return 3
    errors = php_lint(project)
    more, warnings = static_problems(project, wp)
    errors += more
    for w in warnings:
        print(f"  ⚠ {w}")
    for e in errors:
        print(f"  ✗ {e}")
    log(f"static: {len(errors)} problem(s)" if errors else "static: clean")
    return 1 if errors else 0


# ─── serve ────────────────────────────────────────────────────────────────────

INSTALL_PHP = r"""<?php
define( 'WP_INSTALLING', true );
$_SERVER['HTTP_HOST'] = getenv( 'OC_WP_HOST' );
$_SERVER['REQUEST_URI'] = '/';
require __DIR__ . '/wp-load.php';
require_once ABSPATH . 'wp-admin/includes/upgrade.php';
$cfg = json_decode( file_get_contents( getenv( 'OC_WP_CONFIG' ) ), true );
if ( ! is_blog_installed() ) {
	$admin = $cfg['users'][0];
	$r = wp_install( $cfg['title'], $admin['login'], $admin['email'], true, '', wp_slash( $admin['password'] ) );
	if ( is_wp_error( $r ) ) { fwrite( STDERR, $r->get_error_message() ); exit( 1 ); }
}
echo "installed\n";
"""

SETUP_PHP = r"""<?php
$_SERVER['HTTP_HOST'] = getenv( 'OC_WP_HOST' );
$_SERVER['REQUEST_URI'] = '/';
require __DIR__ . '/wp-load.php';
require_once ABSPATH . 'wp-admin/includes/plugin.php';
$cfg = json_decode( file_get_contents( getenv( 'OC_WP_CONFIG' ) ), true );
$out = array( 'users' => array(), 'plugins' => array(), 'errors' => array() );
foreach ( $cfg['users'] as $u ) {
	$id = username_exists( $u['login'] );
	if ( ! $id ) {
		$id = wp_insert_user( array( 'user_login' => $u['login'], 'user_email' => $u['email'], 'user_pass' => $u['password'], 'role' => $u['role'], 'display_name' => $u['name'] ) );
	} else {
		wp_set_password( $u['password'], $id );
		( new WP_User( $id ) )->set_role( $u['role'] );
	}
	if ( is_wp_error( $id ) ) { $out['errors'][] = 'user ' . $u['login'] . ': ' . $id->get_error_message(); } else { $out['users'][] = $u['login']; }
}
update_option( 'permalink_structure', '/%postname%/' );
update_option( 'blogname', $cfg['title'] );
foreach ( array( 'timezone_string' => 'Europe/Berlin', 'date_format' => 'd.m.Y', 'time_format' => 'H:i', 'start_of_week' => 1 ) as $k => $v ) { update_option( $k, $v ); }
if ( wp_get_theme( $cfg['theme'] )->exists() ) { switch_theme( $cfg['theme'] ); } else { $out['errors'][] = 'theme ' . $cfg['theme'] . ' not found'; }
foreach ( $cfg['plugins'] as $file ) {
	$r = activate_plugin( $file );
	if ( is_wp_error( $r ) ) { $out['errors'][] = 'plugin ' . $file . ': ' . $r->get_error_message(); } else { $out['plugins'][] = $file; }
}
if ( ! empty( $cfg['seed'] ) && file_exists( $cfg['seed'] ) ) {
	try { require $cfg['seed']; } catch ( Throwable $e ) { $out['errors'][] = 'seed: ' . $e->getMessage(); }
}
flush_rewrite_rules( false );
echo json_encode( $out ) . "\n";
"""

ROUTER_PHP = r"""<?php
$root = __DIR__;
$path = urldecode( parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH ) );
$file = $root . $path;
if ( $path !== '/' && is_file( $file ) ) { return false; }
if ( is_dir( $file ) && is_file( rtrim( $file, '/' ) . '/index.php' ) ) {
	$_SERVER['SCRIPT_NAME'] = rtrim( $path, '/' ) . '/index.php';
	chdir( rtrim( $file, '/' ) );
	require rtrim( $file, '/' ) . '/index.php';
	return;
}
$_SERVER['SCRIPT_NAME'] = '/index.php';
require $root . '/index.php';
"""


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise SystemExit("[wp-gate] no free port")


def demo_users(spec: dict[str, Any]) -> list[dict[str, str]]:
    users = []
    for i, acct in enumerate((spec.get("demo") or {}).get("accounts") or []):
        if not isinstance(acct, dict) or not acct.get("email"):
            continue
        role = acct.get("wp_role") or acct.get("role") or "subscriber"
        role = {"admin": "administrator", "owner": "administrator"}.get(role, role)
        users.append({"login": acct.get("login") or acct["email"].split("@")[0], "email": acct["email"],
                      "password": acct.get("password") or "Demo1234!", "role": role,
                      "name": acct.get("name") or acct["email"].split("@")[0]})
    if not users or users[0]["role"] != "administrator":
        users.insert(0, {"login": "admin", "email": "admin@example.test", "password": secrets.token_urlsafe(12),
                         "role": "administrator", "name": "Admin"})
    return users


def link(src: Path, dest: Path) -> None:
    if dest.is_symlink() or dest.exists():
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            shutil.rmtree(dest)
    dest.symlink_to(src, target_is_directory=src.is_dir())


def prepare_site(project: Path, spec: dict[str, Any], wp: dict[str, Any], port: int, fresh: bool) -> tuple[Path, dict[str, Any]]:
    core, sqlite_plugin = fetch(str(wp.get("version") or "6.8"))
    site = project / ".onecommand" / "wp-site"
    if fresh and site.exists():
        shutil.rmtree(site)
    if not (site / "wp-load.php").exists():
        log(f"▶ creating the site in {site}")
        shutil.copytree(core, site, ignore=shutil.ignore_patterns(".git"), symlinks=False)
        shutil.copytree(sqlite_plugin, site / "wp-content" / "plugins" / "sqlite-database-integration", symlinks=False)
        dropin = (sqlite_plugin / "db.copy").read_text(encoding="utf-8")
        dropin = dropin.replace("{SQLITE_IMPLEMENTATION_FOLDER_PATH}",
                                str(site / "wp-content" / "plugins" / "sqlite-database-integration"))
        dropin = dropin.replace("{SQLITE_PLUGIN}", "sqlite-database-integration/load.php")
        (site / "wp-content" / "db.php").write_text(dropin, encoding="utf-8")
        (site / "wp-content" / "database").mkdir(exist_ok=True)
    salts = "\n".join(f"define( '{k}', '{secrets.token_urlsafe(48)}' );" for k in
                      ("AUTH_KEY", "SECURE_AUTH_KEY", "LOGGED_IN_KEY", "NONCE_KEY", "AUTH_SALT", "SECURE_AUTH_SALT",
                       "LOGGED_IN_SALT", "NONCE_SALT"))
    url = f"http://127.0.0.1:{port}"
    (site / "wp-config.php").write_text(f"""<?php
define( 'DB_NAME', 'wordpress' ); define( 'DB_USER', '' ); define( 'DB_PASSWORD', '' ); define( 'DB_HOST', '' );
define( 'DB_CHARSET', 'utf8mb4' ); define( 'DB_COLLATE', '' );
define( 'DB_DIR', __DIR__ . '/wp-content/database/' ); define( 'DB_FILE', '.ht.sqlite' );
{salts}
$table_prefix = 'wp_';
define( 'WP_HOME', '{url}' ); define( 'WP_SITEURL', '{url}' );
define( 'WP_ENVIRONMENT_TYPE', 'local' );
define( 'WP_DEBUG', true ); define( 'WP_DEBUG_LOG', __DIR__ . '/wp-content/debug.log' ); define( 'WP_DEBUG_DISPLAY', false );
define( 'DISALLOW_FILE_EDIT', true ); define( 'AUTOMATIC_UPDATER_DISABLED', true ); define( 'WP_HTTP_BLOCK_EXTERNAL', true );
if ( ! defined( 'ABSPATH' ) ) {{ define( 'ABSPATH', __DIR__ . '/' ); }}
require_once ABSPATH . 'wp-settings.php';
""", encoding="utf-8")
    base = project / "wordpress"
    theme = str(wp.get("theme"))
    if (base / "themes" / theme).is_dir():
        link(base / "themes" / theme, site / "wp-content" / "themes" / theme)
    plugin_files = []
    for slug in wp.get("plugins") or []:
        if (base / "plugins" / slug).is_dir():
            link(base / "plugins" / slug, site / "wp-content" / "plugins" / slug)
            plugin_files.append(f"{slug}/{slug}.php")
    for slug in wp.get("third_party_plugins") or []:
        src = fetch_plugin(slug)
        if src:
            link(src, site / "wp-content" / "plugins" / slug)
            main = next((p.name for p in sorted(src.glob("*.php")) if "Plugin Name:" in p.read_text(errors="replace")[:3000]), None)
            if main:
                plugin_files.insert(0, f"{slug}/{main}")
    (site / "router.php").write_text(ROUTER_PHP, encoding="utf-8")
    (site / ".oc-install.php").write_text(INSTALL_PHP, encoding="utf-8")
    (site / ".oc-setup.php").write_text(SETUP_PHP, encoding="utf-8")
    seed = project / str(wp.get("seed") or "wordpress/seed.php")
    cfg = {"title": spec.get("project_name") or "Website", "theme": theme, "plugins": plugin_files,
           "users": demo_users(spec), "seed": str(seed) if seed.exists() else ""}
    cfg_path = site / ".oc-site.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    env = {**os.environ, "OC_WP_HOST": f"127.0.0.1:{port}", "OC_WP_CONFIG": str(cfg_path)}
    for script in (".oc-install.php", ".oc-setup.php"):
        r = subprocess.run(["php", "-d", "memory_limit=512M", script], cwd=site, env=env, capture_output=True,
                           text=True, timeout=300)
        if r.returncode != 0:
            raise SystemExit(f"[wp-gate] {script} failed: {(r.stderr or r.stdout).strip()[-1500:]}")
        if script == ".oc-setup.php":
            last = (r.stdout.strip().splitlines() or ["{}"])[-1]
            try:
                result = json.loads(last)
            except ValueError:
                raise SystemExit(f"[wp-gate] setup printed no result: {r.stdout[-800:]} {r.stderr[-800:]}")
            if result.get("errors"):
                raise SystemExit("[wp-gate] setup: " + "; ".join(result["errors"]))
    return site, cfg


class Server:
    def __init__(self, site: Path, port: int, log_path: Path):
        self.site, self.port, self.log_path = site, port, log_path
        self.proc: subprocess.Popen | None = None

    def start(self, timeout: int = 60) -> str | None:
        self.log_fh = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(["php", "-d", "memory_limit=512M", "-S", f"127.0.0.1:{self.port}", "-t", str(self.site),
                                      str(self.site / "router.php")], cwd=self.site, stdout=self.log_fh,
                                     stderr=subprocess.STDOUT, env={**os.environ, "PHP_CLI_SERVER_WORKERS": "4"},
                                     start_new_session=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                return f"php server exited with code {self.proc.returncode}"
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=10) as resp:
                    if resp.status < 500:
                        return None
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    return None
                return f"home page answers HTTP {exc.code}"
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        return f"no answer on port {self.port} after {timeout}s"

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                os.killpg(self.proc.pid, signal.SIGKILL)
        if getattr(self, "log_fh", None):
            self.log_fh.close()


def cmd_serve(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    spec = load_spec(project)
    wp = wp_section(spec)
    if wp is None:
        log("spec has no wordpress section — not applicable")
        return 3
    port = free_port(args.port)
    site, cfg = prepare_site(project, spec, wp, port, args.fresh)
    server = Server(site, port, project / ".onecommand" / "wp-server.log")
    problem = server.start()
    if problem:
        server.stop()
        print(f"  ✗ {problem} — see {server.log_path}")
        return 1
    admin = cfg["users"][0]
    log(f"✅ http://127.0.0.1:{port}  ·  /wp-admin as {admin['login']} / {admin['password']}  ·  Ctrl-C stops")
    try:
        while server.proc and server.proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


# ─── gate ─────────────────────────────────────────────────────────────────────

class Gate:
    def __init__(self, project: Path, out: Path, stage: str):
        self.project, self.out, self.stage = project, out, stage
        self.steps: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.started = now()
        out.mkdir(parents=True, exist_ok=True)

    def record(self, step: str, status: str, reason: str | None = None, log_file: Path | None = None) -> None:
        self.steps.append({"step": step, "status": status, "exit_code": 0 if status == "pass" else 1,
                           "duration_s": 0, "log": str(log_file) if log_file else None, "reason": reason})
        mark = {"pass": "✓", "fail": "✗", "warn": "⚠", "skipped": "○"}[status]
        log(f"  {mark} {step}" + (f" — {reason}" if reason else ""))

    def problems(self, step: str, items: list[str]) -> bool:
        if items:
            self.record(step, "fail", f"{len(items)} problem(s)")
            self.errors.append(f"===== {step} =====\n" + "\n".join(items) + "\n")
            return False
        self.record(step, "pass")
        return True

    def run(self, step: str, cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> bool:
        logfile = self.out / f"{step}.log"
        with open(logfile, "w", encoding="utf-8") as fh:
            try:
                rc = subprocess.run(cmd, cwd=self.project, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout,
                                    env={**os.environ, **(env or {})}).returncode
            except subprocess.TimeoutExpired:
                rc = 124
        if rc == 0:
            self.record(step, "pass", log_file=logfile)
            return True
        self.record(step, "fail", "timed out" if rc == 124 else f"exit code {rc}", logfile)
        lines = logfile.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [line for line in lines if ERROR_LINE.search(line)][:60]
        self.errors.append(f"===== {step} (full log: {logfile}) =====\n" + "\n".join(hits or lines[-40:]) + "\n")
        return False

    def write(self, passed: bool) -> None:
        result = {"version": 1, "stage": self.stage, "project_dir": str(self.project), "package_manager": "wordpress",
                  "started_at": self.started, "finished_at": now(), "passed": passed, "not_applicable": False,
                  "failed_steps": [s["step"] for s in self.steps if s["status"] == "fail"],
                  "warnings": [f"{s['step']}: {s['reason']}" for s in self.steps if s["status"] == "warn"],
                  "steps": self.steps}
        tmp = self.out / ".result.json.tmp"
        tmp.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.out / "result.json")
        (self.out / "errors.txt").write_text("\n".join(self.errors), encoding="utf-8")


def has_dep(project: Path, name: str) -> bool:
    try:
        pkg = json.loads((project / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return name in {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}


def playwright_config(project: Path) -> Path | None:
    return next((project / f"playwright.config.{ext}" for ext in ("ts", "js", "mjs")
                 if (project / f"playwright.config.{ext}").exists()), None)


def cmd_gate(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    spec = load_spec(project)
    wp = wp_section(spec)
    if wp is None:
        log("spec has no wordpress section — not applicable")
        return 3
    gate = Gate(project, Path(args.out).resolve() if args.out else project / ".onecommand" / "gate", args.stage)
    log(f"Project: {project} · WordPress {wp.get('version') or '6.8'} · stage: {args.stage}")
    ok = gate.problems("php-lint", php_lint(project))
    errors, warnings = static_problems(project, wp)
    ok = gate.problems("wordpress-standards", errors) and ok
    for w in warnings:
        gate.record("wordpress-standards", "warn", w)
    if wp.get("build") and (project / "package.json").exists():
        ok = gate.run("build", ["bash", "-lc", str(wp["build"])], 900) and ok
    if args.stage != "static" and ok:
        port = free_port(args.port)
        server = None
        try:
            site, _ = prepare_site(project, spec, wp, port, fresh=True)
            gate.record("site", "pass", f"WordPress with theme {wp.get('theme')} on 127.0.0.1:{port}")
            server = Server(site, port, gate.out / "wp-server.log")
            problem = server.start()
            if problem:
                ok = gate.problems("serve", [f"{problem} — see {server.log_path}"]) and False
            else:
                gate.record("serve", "pass")
                base = f"http://127.0.0.1:{port}"
                if args.stage in ("e2e", "all"):
                    config = playwright_config(project)
                    if not config or not has_dep(project, "@playwright/test"):
                        ok = gate.problems("e2e", ["no playwright.config / @playwright/test — run the acceptance-tester "
                                                   "skill (baseURL from process.env.BASE_URL)"]) and False
                    else:
                        results = gate.out / "playwright.json"
                        ran = gate.run("e2e", ["npx", "playwright", "test", "--config", str(config), "--reporter=list,json"],
                                       1800, {"BASE_URL": base, "PLAYWRIGHT_JSON_OUTPUT_NAME": str(results), "CI": "true"})
                        rep = gate.run("acceptance", [sys.executable, str(HOOKS / "acceptance-report.py"), "report",
                                                      "--spec", ".onecommand-spec.json", "--results", str(results),
                                                      "--out", str(gate.out / "acceptance.json"),
                                                      "--markdown", str(gate.out / "acceptance.md")], 120)
                        ok = ran and rep and ok
                if args.stage in ("tour", "all"):
                    ok = gate.run("tour", [sys.executable, str(HOOKS / "ui-tour.py"), "run", "--project-dir", str(project),
                                           "--base-url", base, "--no-seed"], 1800) and ok
                debug_log = site / "wp-content" / "debug.log"
                if debug_log.exists():
                    fatal = [line for line in debug_log.read_text(errors="replace").splitlines()
                             if re.search(r"PHP (Fatal|Parse) error", line)]
                    notices = [line for line in debug_log.read_text(errors="replace").splitlines()
                               if re.search(r"PHP (Warning|Notice|Deprecated)", line)
                               and ("/themes/" in line or "/plugins/" in line)]
                    ok = gate.problems("php-errors", fatal[:30]) and ok
                    if notices:
                        gate.record("php-notices", "warn", f"{len(notices)} warning(s)/notice(s) from theme or plugins — {debug_log}")
        except SystemExit as exc:
            ok = gate.problems("site", [str(exc.code)]) and False
        finally:
            if server:
                server.stop()
    gate.write(ok)
    log(f"✅ WORDPRESS GATE PASSED ({args.stage}) — {gate.out / 'result.json'}" if ok
        else f"❌ WORDPRESS GATE FAILED ({args.stage}) — errors: {gate.out / 'errors.txt'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch", help="cache WordPress core and the SQLite integration")
    p.add_argument("--wp-version", default="6.8")
    p.set_defaults(func=cmd_fetch)
    for name, func in (("static", cmd_static), ("serve", cmd_serve), ("gate", cmd_gate)):
        p = sub.add_parser(name)
        p.add_argument("--project-dir", default=".")
        if name != "static":
            p.add_argument("--port", type=int, default=8890)
        if name == "serve":
            p.add_argument("--fresh", action="store_true", help="rebuild the site (new database)")
        if name == "gate":
            p.add_argument("--stage", choices=("static", "e2e", "tour", "all"), default="all")
            p.add_argument("--out")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
