---
name: wordpress-builder
description: Build WordPress websites at agency level — a block theme (Full Site Editing) generated from the design brief, a site plugin for post types, custom blocks and settings, curated patterns so editors cannot break the design, WooCommerce for the German market, privacy without third-party requests, hardened security, performance, demo content, deployment and handover. Used whenever the spec has a "wordpress" section (prompts naming WordPress, WP, WooCommerce, Gutenberg). Checked by hooks/wp-gate.py.
---

You build the WordPress version of the product in the spec. The modules, pages and acceptance criteria come
from the blueprint (website, shop …) like for any build; this skill decides how they become a WordPress site.
The bar is a site an agency would sell for a five-figure sum: designed (design brief + `emil`), fast,
private, secure, and editable by the customer without breaking it.

`hooks/wp-gate.py` is the verdict. It runs real WordPress (PHP built-in server + SQLite, no Docker) with your
theme, plugins and demo content, then the acceptance tests and the UI tour. `quality-gate.sh` hands over to it
automatically when the spec has a `wordpress` section. Locally: `python3 "$OC_ROOT/hooks/wp-gate.py" serve`
starts the site and prints the admin login.

## 1. Layout (fixed — the gate reads it)

```
wordpress/
  themes/<theme>/                 block theme
    style.css                     header: Theme Name, Text Domain, Version, Requires at least: 6.6, Requires PHP: 8.1
    theme.json                    version 3 — every design token from .onecommand/design.md
    functions.php                 enqueue, theme supports, pattern categories, block styles — nothing else
    templates/                    index, front-page, page, single, archive, search, 404 (.html)
    parts/                        header.html, footer.html (+ variants)
    patterns/                     one PHP file per section (Title/Slug/Categories/Block Types headers)
    styles/                       optional style variations (e.g. dark)
    assets/fonts/                 the brief's typefaces as woff2 (latin + latin-ext subsets)
    assets/css/                   only what theme.json cannot express (motion, complex layouts)
  plugins/<theme>-core/           site plugin: everything that must survive a theme change
    <theme>-core.php              header + bootstrap; `defined( 'ABSPATH' ) || exit;` in EVERY php file
    includes/                     post types, taxonomies, meta (register_post_meta, show_in_rest), privacy, security
    blocks/<name>/                custom blocks: block.json (apiVersion 3), edit.js, render.php or save.js
  seed.php                        demo content — idempotent, fixed slugs
package.json                      @wordpress/scripts (build blocks), @playwright/test (acceptance)
playwright.config.ts              baseURL from process.env.BASE_URL (the gate starts the site)
```

Spec: `wordpress.theme`, `wordpress.plugins` (own, activated in order), `wordpress.third_party_plugins`
(slugs from wordpress.org, counted against `plugin_budget`, default 6), `wordpress.seed`, `wordpress.build`.
Demo logins: `demo.accounts` with `wp_role` (administrator, editor …) and `login`.

## 2. Theme from the design brief

- Write `.onecommand/design.md` first (oc-frontend-design), then translate it — tokens live in `theme.json`,
  not in CSS: `settings.color.palette` (brand, accent, tinted neutrals, states), `settings.typography.fontFamilies`
  with `fontFace` → `file:./assets/fonts/…woff2` (self-hosted, never Google Fonts), `fontSizes` (fluid
  clamp scale), `settings.spacing.spacingSizes`, `settings.layout.contentSize/wideSize`, `styles.elements`
  (link, button, heading h1–h6), `styles.blocks` for core blocks.
- Lock the design for editors: `settings.color.custom: false`, `customGradient: false`,
  `typography.customFontSize: false`, `settings.appearanceTools: true` only where wanted. Editors pick from the
  palette and the scale, nothing else.
- Templates are composed of patterns and template parts; no hard-coded text in templates — text lives in
  patterns (`esc_html__()` with the theme's text domain) or in content.
- Every section of the blueprint's pages is a pattern (hero, services, case grid, testimonials, team, CTA, FAQ,
  contact). Register a pattern category named after the brand. Start pages from patterns in `seed.php`.
- **`emil` is mandatory for every website** (`skill-catalog.py read emil --phase 2`): read `emil-design-eng`
  before the first pattern, `animate` before every transition (CSS, `prefers-reduced-motion`), `mobile-native`
  for touch, and in Phase 6 `break-ui` on every pattern with long German texts and `review-animations`. No animation library for a website unless the brief
  asks for a signature motion piece.
- Style variations (`styles/*.json`) for a dark mode or seasonal look instead of a second theme.

## 3. Site plugin and blocks

- Post types and taxonomies for every blueprint entity (case studies, team, jobs, services …):
  `show_in_rest: true`, German labels, `rewrite` slugs in German, `template` + `template_lock` for their block
  layout, archive templates in the theme.
- Custom fields: `register_post_meta` with `show_in_rest`, `sanitize_callback`, `auth_callback`; edit them with
  block bindings or a block inspector panel — no ACF unless the customer already uses it.
- Custom blocks only where core blocks plus patterns cannot do it (filters, maps with two-click consent,
  calculators). Build with `@wordpress/scripts` (`npm run build` → `build/`), dynamic blocks render in PHP.
- Forms: one own contact block or a vetted form plugin — server-side validation, nonce, honeypot + time trap
  against spam, mail via `wp_mail` (SMTP configured in production), consent checkbox with link to the privacy
  page, stored submissions optional with deletion after N days.

## 4. Privacy (Germany)

The tour fails on every request to a third-party host. Remove WordPress's defaults:
- emoji script and styles (`print_emoji_detection_script`, `print_emoji_styles`, `wp_resource_hints` for
  s.w.org, `emoji_svg_url` → false);
- Gravatar: `show_avatars` off, or local avatars; also in the admin bar on the front end;
- oEmbed discovery and embeds: YouTube / Vimeo / Maps only behind a two-click preview ("Video laden");
- Google Fonts in any plugin or pattern; jQuery from CDNs;
- comments off by default (`default_comment_status` closed); if wanted: no IP stored, privacy note.
No analytics without consent. If the customer wants statistics: self-hosted Matomo without cookies, or a
consent tool that blocks before consent. Impressum and Datenschutz pages exist and are linked in the footer.

## 5. Security

The gate rejects: output without escaping, `$_POST` without nonce check, `$_GET/$_POST` without
sanitizing, SQL with interpolated variables, `eval`/`base64_decode($…)`, plugin files without ABSPATH guard.
In addition, the site plugin:
- disables XML-RPC (`xmlrpc_enabled` → false) and file editing (`DISALLOW_FILE_EDIT` in wp-config for production);
- blocks user enumeration: `/?author=N` → 404, `/wp-json/wp/v2/users` only for logged-in users;
- limits failed logins (own transient counter or a vetted plugin), enforces strong passwords, 2FA for
  administrators at pro tier (vetted plugin);
- sends security headers (`X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`,
  `Content-Security-Policy` frame-ancestors);
- capabilities: editors manage content, never plugins, themes, users or settings.

## 6. Performance

No jQuery on the front end, `should_load_separate_core_block_assets`, block styles inline only where used,
images through the media library (WebP/AVIF, `srcset`, width/height, lazy below the fold, the LCP image
`fetchpriority="high"`), fonts `font-display: swap` with preload of the one body face, no page builder.
The tour measures the blueprint's performance budget on every page.

## 7. WooCommerce (shop on WordPress)

WooCommerce + a German legal plugin (e.g. Germanized): "Zahlungspflichtig bestellen", Widerrufsbelehrung and
form, Grundpreise, Lieferzeiten, prices "inkl. MwSt., zzgl. Versand", invoices as PDF. Payments in test mode for
the acceptance tests. Theme templates for shop, product, cart, checkout as block templates (WooCommerce blocks).

## 8. Demo content (`seed.php`)

Runs after `wp-load.php`, must be idempotent (look up by slug before inserting). Fixed German slugs —
WordPress turns "Über uns" into `uber-uns` without the de_DE locale, so set `post_name` explicitly
(`ueber-uns`). Content: every page of the spec built from the theme's patterns with real text (no lorem ipsum),
entries for every post type, a primary navigation (`wp_navigation` post), front page set
(`show_on_front`/`page_on_front`), images from `wordpress/seed-media/` imported with `media_handle_sideload`
(no hotlinking). The gate creates the demo users from `demo.accounts`.

## 9. Operations and handover

- `wp-config` for production from environment variables; `WP_ENVIRONMENT_TYPE`; automatic minor updates.
- Deployment script with WP-CLI: code from git, `wp search-replace` for URL changes, `wp cache flush`;
  never edit code in the live admin.
- Backups (database + uploads) daily, restore documented and tested on staging; staging behind password + noindex.
- Delivery report: admin URL, the editor guide (how to add a page from patterns, edit posts, swap images,
  SEO fields), the plugin list with why each one is there, update policy.

## 10. Done means

`python3 "$OC_ROOT/hooks/wp-gate.py" gate --stage all` exits 0. It covers PHP lint, the WordPress rules, the
site starting with your theme, plugins and seed, the acceptance tests, the UI tour (screenshots, design audit,
third-party requests, performance budget), and no PHP fatal errors in `debug.log`. Then review the
screenshots like every other build.
