---
description: Turn vibecoded, AI-looking UI into a designed interface — audit the slop, set a direction from the product, fix it in nine passes, optionally render a story video (unslop by Damir Sokolovsky).
argument-hint: "<screen, file or URL, e.g. 'this dashboard' or 'the hero of https://example.com'>"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Resolve the plugin root and load the skill:

```bash
OC_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.claude/plugins/installed_plugins.json')));print([e[0]['installPath'] for k,e in d['plugins'].items() if k.startswith('onecommand@')][0])" 2>/dev/null)}"
[ -f "$OC_ROOT/skills/unslop/SKILL.md" ] || OC_ROOT="$HOME/OneCommand"
echo "$OC_ROOT/skills/unslop"
```

1. Read `$OC_ROOT/skills/unslop/SKILL.md` (the skill folder in its scripts is `$OC_ROOT/skills/unslop`).
2. Run it on: **$ARGUMENTS** (nothing given → ask which screen).
3. Follow "Run it" exactly: look at the screen, audit with `references/signs.md`, decide how much to change, show
   the audit and the five direction lines and wait for the user's answer, then the nine passes, the checklist and
   the report. Read each reference file when the skill points to it.
4. A story video only when the user asks for one; it needs Playwright and ffmpeg.
