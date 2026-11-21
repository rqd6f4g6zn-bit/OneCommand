---
name: unslop
description: Edit or audit prose for AI writing patterns. Use when someone wants to humanize a draft, remove slop, flag robotic phrasing, or learn and write in an author's voice.
license: MIT
user-invocable: true
argument-hint: "[teach · cleanup · rewrite · mimic] [input]"
metadata:
  author: claytonkim
  version: "2.3.0"
---

# Unslop

Open the matching command before acting. Input can be pasted text, a file, or stdin.
For audits and rewrites, [the core contract](references/core-contract.md) governs what to edit and preserve.

## Routing by phrase

| Request | Command |
|---------|---------|
| `rewrite`, humanize a draft, or bare `/unslop <text>` | [references/commands/rewrite.md](references/commands/rewrite.md) |
| `cleanup`, propose edits I can accept or reject | [references/commands/cleanup.md](references/commands/cleanup.md) |
| audit, review before publication, flag only, or `--report` | [references/commands/cleanup.md](references/commands/cleanup.md#report-only) |
| `teach`, build a voice profile | [references/commands/teach.md](references/commands/teach.md) |
| harvest writing samples, what writing of mine do you have? | [references/commands/teach.md](references/commands/teach.md#1-gather-samples-harvest) |
| calibrate my voice profile, quiz me on paired samples | [references/commands/teach.md](references/commands/teach.md#calibrate) |
| `mimic` or draft in my voice | [references/commands/mimic.md](references/commands/mimic.md) |
| refine until it sounds like me | [references/commands/mimic.md](references/commands/mimic.md#refine) |
| voice check, does this sound like me? | [references/commands/mimic.md](references/commands/mimic.md#voice-check) |
| add a newly observed AI tell to the library | [references/commands/contribute.md](references/commands/contribute.md) |

## Output Format

Before writing, read the selected voice preset in `presets/`. The default is `crisp`; `--preset` also accepts `warm`, `expert`, and `story`.

Return the cleaned text for a rewrite. For a report, give **Issues Found** (span, category, severity, contextual reason) and **Assessment** (confirmed defects and judgment calls). Preserve the original text in report mode.

For strict or requested analysis, return **Transformed Text** and **Validation**. Report constraints preserved, before/after pattern counts, structure, readability grade, sentence variance, percentage changed, and rubric score. With `--strict`, scores below 32/40 fail. See [the rubric](references/rubric.md).

## Inside OneCommand

This skill is [unslop](https://github.com/theclaymethod/unslop) by Clayton Kim (MIT licence, see `LICENSE`
in this folder), bundled at upstream commit `0f4a07f`. Everything above this section and every file in
`references/`, `presets/`, `scripts/` and `assets/` is upstream, unchanged. The upstream eval suite
(`evals/`) is not bundled: maintainer work (`contribute`, `references/maintenance.md`,
`references/refresh.md`, `evals/run_structure_climb.py`) belongs in the upstream repository.

Run the scanners from the skill root: `cd "$OC_ROOT/skills/unslop"` (with `/unslop` outside a build the
command resolves `OC_ROOT`). They need Python 3.8+ and nothing else.

### Phase 3 (marketing-agent)

Every piece of prose the build ships goes through `rewrite` before the phase ends: README.md, landing-page
copy, docs pages, CHANGELOG entries, e-mail templates. Write the text first, then edit it under the core
contract — confirmed defects only, facts, numbers, code, commands and links byte-for-byte.

- **English text:** run the rewrite scanners and the validation block of `references/core-contract.md` on
  each file (Markdown: `--genre docs` for the structure scanner). An introduced hard hit or a preservation
  loss blocks the file until it is fixed.
- **German or other non-English text:** the scanners decline it by design (`non_english`), so they prove
  nothing. Apply `references/core-contract.md` and the categories of `references/taboo-phrases.md` by
  meaning ("In der heutigen schnelllebigen Welt", "nahtlos", "Lassen Sie uns eintauchen", hedge stacks,
  significance inflation, closing recaps), and still run `scripts/validate_preservation.py original.txt
  transformed.txt`: its patterns catch versions, URLs, API paths and § references in German text too.
  German dates and amounts (21. November, 1.000 €) can slip past its English patterns, so compare those
  by hand.
- Code blocks, commands, API names and quoted user text are never edited.
- No interactive steps inside a build: `teach`, `calibrate` and `mimic` need the user's own samples and run
  only through `/unslop` outside a build. Default preset `crisp`; `expert` for technical documentation.
- Record files you left untouched because a hit was protected (literal use, quotation, genre) in
  `.onecommand/decisions.md` with one line each.

### /unslop

`/unslop <command> <text or file>` runs the routing table above directly on the user's text, with the
upstream defaults: `rewrite` returns the cleaned text, `cleanup` proposes edits, `--report` changes nothing.
