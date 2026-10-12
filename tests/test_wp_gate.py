"""hooks/wp-gate.py — WordPress sites: static WordPress rules, the real site on PHP + SQLite, gate verdict."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from conftest import py, write_json

needs_php = pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")

SPEC = {"project_name": "Kaffeehaus", "app_type": "web-app", "build_targets": ["web"], "ui_language": "de",
        "pages": ["/", "/ueber-uns/"],
        "demo": {"login_path": "/wp-login.php", "accounts": [
            {"role": "admin", "wp_role": "administrator", "login": "inhaber", "email": "inhaber@kaffeehaus.test", "password": "Demo1234!"},
            {"role": "editor", "wp_role": "editor", "login": "redaktion", "email": "redaktion@kaffeehaus.test", "password": "Demo1234!"}]},
        "wordpress": {"version": "6.8", "theme": "kaffeehaus", "plugins": ["kaffeehaus-core"], "seed": "wordpress/seed.php"}}

THEME_JSON = {"version": 3, "settings": {
    "layout": {"contentSize": "720px", "wideSize": "1200px"},
    "color": {"palette": [{"slug": "roest", "name": "Röstbraun", "color": "#4a2c1d"},
                          {"slug": "creme", "name": "Creme", "color": "#f6efe4"},
                          {"slug": "akzent", "name": "Akzent", "color": "#c8692f"}]},
    "typography": {"fontFamilies": [{"slug": "brand", "name": "Brand", "fontFamily": "Brand, sans-serif",
                                     "fontFace": [{"fontFamily": "Brand", "src": ["file:./assets/fonts/brand.woff2"]}]}]}}}

PLUGIN = """<?php
/**
 * Plugin Name: Kaffeehaus Core
 */
defined( 'ABSPATH' ) || exit;
add_action( 'init', function () {
\tregister_post_type( 'kh_bohne', array( 'label' => 'Bohnen', 'public' => true, 'show_in_rest' => true ) );
} );
"""

SEED = """<?php
defined( 'ABSPATH' ) || exit;
foreach ( array( 'startseite' => 'Startseite', 'ueber-uns' => 'Über uns' ) as $slug => $title ) {
\tif ( ! get_page_by_path( $slug ) ) {
\t\twp_insert_post( array( 'post_type' => 'page', 'post_status' => 'publish', 'post_title' => $title, 'post_name' => $slug,
\t\t\t'post_content' => '<!-- wp:paragraph --><p>Willkommen im Kaffeehaus.</p><!-- /wp:paragraph -->' ) );
\t}
}
update_option( 'show_on_front', 'page' );
update_option( 'page_on_front', get_page_by_path( 'startseite' )->ID );
"""


def make_site(root: Path, spec: dict | None = None) -> Path:
    theme = root / "wordpress" / "themes" / "kaffeehaus"
    for d in ("templates", "parts", "patterns", "assets/fonts"):
        (theme / d).mkdir(parents=True, exist_ok=True)
    (theme / "style.css").write_text("/*\nTheme Name: Kaffeehaus\nText Domain: kaffeehaus\nVersion: 1.0.0\nRequires at least: 6.6\n*/\n")
    write_json(theme / "theme.json", THEME_JSON)
    (theme / "assets" / "fonts" / "brand.woff2").write_bytes(b"wOF2")
    block = '<!-- wp:template-part {"slug":"header"} /--><!-- wp:post-content /--><!-- wp:template-part {"slug":"footer"} /-->'
    (theme / "templates" / "index.html").write_text(block)
    (theme / "parts" / "header.html").write_text('<!-- wp:site-title /-->')
    (theme / "parts" / "footer.html").write_text('<!-- wp:paragraph --><p>Impressum · Datenschutz</p><!-- /wp:paragraph -->')
    (theme / "patterns" / "hero.php").write_text("<?php\n/**\n * Title: Hero\n * Slug: kaffeehaus/hero\n */\n?>\n"
                                                 "<!-- wp:heading --><h2><?php echo esc_html__( 'Frisch geröstet', 'kaffeehaus' ); ?></h2><!-- /wp:heading -->\n")
    plugin = root / "wordpress" / "plugins" / "kaffeehaus-core"
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "kaffeehaus-core.php").write_text(PLUGIN)
    (root / "wordpress" / "seed.php").write_text(SEED)
    write_json(root / ".onecommand-spec.json", spec or SPEC)
    return root


@needs_php
def test_clean_theme_and_plugin_pass_the_static_rules(tmp_path):
    r = py("wp-gate.py", "static", "--project-dir", str(make_site(tmp_path)))
    assert r.returncode == 0, r.stdout


@needs_php
def test_static_rules_catch_what_breaks_wordpress_sites(tmp_path):
    root = make_site(tmp_path)
    theme = root / "wordpress" / "themes" / "kaffeehaus"
    data = json.loads((theme / "theme.json").read_text())
    data["settings"]["typography"]["fontFamilies"] = []
    write_json(theme / "theme.json", data)
    (theme / "parts" / "footer.html").write_text('<link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet">')
    bad = root / "wordpress" / "plugins" / "kaffeehaus-core" / "includes"
    bad.mkdir()
    (bad / "form.php").write_text("<?php\n$name = $_POST['name'];\necho $name;\n"
                                  "$wpdb->query( \"DELETE FROM wp_posts WHERE ID = $id\" );\neval( $code );\n")
    (bad / "broken.php").write_text("<?php\ndefined( 'ABSPATH' ) || exit;\nfunction ( {\n")
    spec = json.loads((root / ".onecommand-spec.json").read_text())
    spec["wordpress"]["third_party_plugins"] = ["elementor"]
    write_json(root / ".onecommand-spec.json", spec)
    r = py("wp-gate.py", "static", "--project-dir", str(root))
    assert r.returncode == 1
    for needle in ("no self-hosted font", "fonts.googleapis.com", "no direct-access guard", "output without escaping",
                   "without a nonce check", "without sanitizing", "$wpdb->prepare", "dangerous call", "broken.php",
                   "page builder plugins ['elementor']"):
        assert needle in r.stdout, needle


def test_not_applicable_without_wordpress_section(tmp_path):
    write_json(tmp_path / ".onecommand-spec.json", {"project_name": "x"})
    assert py("wp-gate.py", "static", "--project-dir", str(tmp_path)).returncode == 3
    assert py("wp-gate.py", "gate", "--project-dir", str(tmp_path)).returncode == 3


def test_quality_gate_hands_wordpress_specs_over(tmp_path):
    make_site(tmp_path)
    import subprocess
    from conftest import HOOKS
    out = subprocess.run(["bash", str(HOOKS / "quality-gate.sh"), "--stage", "static", "--project-dir", str(tmp_path)],
                         capture_output=True, text=True, timeout=300)
    assert "[wp-gate]" in out.stdout, out.stdout + out.stderr
    result = json.loads((tmp_path / ".onecommand" / "gate" / "result.json").read_text())
    assert result["package_manager"] == "wordpress" and result["stage"] == "static"


@needs_php
@pytest.mark.skipif(os.environ.get("ONECOMMAND_E2E_TESTS") != "1", reason="fetches WordPress core (network)")
def test_real_wordpress_site_starts_with_theme_plugin_users_and_seed(tmp_path):
    import subprocess
    import time
    import urllib.request
    from conftest import HOOKS
    root = make_site(tmp_path)
    proc = subprocess.Popen(["python3", str(HOOKS / "wp-gate.py"), "serve", "--project-dir", str(root), "--port", "8897", "--fresh"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        line = ""
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline and "✅" not in line:
            line = proc.stdout.readline()
            assert line or proc.poll() is None, "serve exited"
        assert "✅" in line, line
        html = urllib.request.urlopen("http://127.0.0.1:8897/", timeout=30).read().decode()
        assert "Willkommen im Kaffeehaus" in html and "kaffeehaus" in html
        assert urllib.request.urlopen("http://127.0.0.1:8897/ueber-uns/", timeout=30).status == 200
        assert urllib.request.urlopen("http://127.0.0.1:8897/wp-login.php", timeout=30).status == 200
    finally:
        import signal
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait(timeout=30)
