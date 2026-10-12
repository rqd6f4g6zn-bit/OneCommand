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
- Style variations (`styles/*.json`) for a dark mode or seasonal look instead of a second theme — and look at
  each one once in the browser (Site Editor → Styles) before delivery; an untested variation is not delivered.
- Every card (journal, events, team) has an image: `seed.php` sets a featured image (`_thumbnail_id`) for every
  post it creates; a card without an image looks broken in the screenshots and to visitors.
- Native date fields follow the visitor's browser language: set `lang="de-DE"` on `<html>` (core does it from the
  site language), add the format as a hint ("TT.MM.JJJJ") and validate server-side; never a US-format placeholder.
- The core navigation overlay removes `is-menu-open` instantly — an exit animation needs a closing class removed
  on `transitionend`; if you skip it, say so in design.md instead of promising it.

## 3. Site plugin and blocks

- Post types and taxonomies for every blueprint entity (case studies, team, jobs, services …):
  `show_in_rest: true`, German labels, `rewrite` slugs in German, `template` + `template_lock` for their block
  layout, archive templates in the theme, `supports` incl. `editor`, `thumbnail`, `excerpt`, `custom-fields`
  (the block editor and its meta panels need them).
- **Permalinks:** a structure with a front (`/journal/%postname%/`) prefixes every taxonomy and post type that
  keeps `with_front` — categories become `/journal/category/…`. Decide whether that is wanted
  (`'rewrite' => array( 'with_front' => false )` otherwise), and when the seed changes the structure, the rules
  are only right after a flush in a new request (the gate does that; in production `wp rewrite flush` after the
  seed). The tour's link check fails on every link that answers 404.
- **Rewrite order:** when a taxonomy's slug starts with a post type's slug (`/feiern/anlass/…` under the post
  type `/feiern/…`), register the taxonomy **before** the post type — otherwise the post type's rule catches
  the URL and the term archive is a 404. The tour's link check fails on such links.
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

Runs in its own PHP process after `wp-load.php` (the gate activates theme and plugins first, so post types,
taxonomies, blocks and patterns are registered — no manual `register_*` calls in the seed), as the first
administrator. Must be idempotent (look up by slug before inserting). `OC_SEED_MODE=worst` (`serve --seed-mode
worst`) adds worst-case content for `emil`'s break-ui: the longest German compound words, 40 dishes in one
category, empty lists, a 300-character title. Fixed German slugs —
WordPress turns "Über uns" into `uber-uns` and drops `ß` without the de_DE locale, so set `post_name` explicitly
(`ueber-uns`, `strasse`) and add a `sanitize_title` filter with German rules (ä→ae, ö→oe, ü→ue, ß→ss) in the
site plugin for slugs editors create later.
Every invented business fact (address, owner, VAT ID, phone, hours, prices, menu, team, video IDs) is listed in
`spec.demo_facts` — the delivery report turns it into the "Vor dem Livegang ersetzen" checklist. No invented
reviews, star ratings, awards or named testimonials (UWG § 5): use offers, facts and a note from the owner. Content: every page of the spec built from the theme's patterns with real text (no lorem ipsum),
entries for every post type, a primary navigation (`wp_navigation` post), front page set
(`show_on_front`/`page_on_front`), images from `wordpress/seed-media/` imported with `media_handle_sideload`
(no hotlinking). The gate creates the demo users from `demo.accounts`.

## 8b. Language, test mode, caching

- The gate installs the core language pack for the spec's `ui_language` (cached in
  `~/.onecommand/cache/wordpress/languages`) and sets `WPLANG`. Offline the admin stays English and the gate
  says so — then translate the core strings the front end shows ("Menu", "Skip to content", "Search") with a
  `gettext` filter in the site plugin, never by editing core.
- Test mode has one switch: `getenv( 'ONECOMMAND_E2E' )` (the gate sets it for the PHP server; its wp-config
  also sets `WP_ENVIRONMENT_TYPE=local`). Test mail goes to an outbox the site plugin keeps in an option and
  exposes through a REST route that exists only in test mode — never in production.
- Page caching serves stale nonces: exclude pages with forms from the cache, or fetch the nonce with a small
  uncached REST call before submit.

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
