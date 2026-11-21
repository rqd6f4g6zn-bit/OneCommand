---
description: Remove AI writing patterns from a text — rewrite a draft, propose reviewable edits, audit without changes, or learn and write in your own voice (unslop by Clayton Kim).
argument-hint: "[rewrite · cleanup · --report · teach · mimic] <text or file>"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Resolve the plugin root and load the skill:

```bash
OC_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.claude/plugins/installed_plugins.json')));print([e[0]['installPath'] for k,e in d['plugins'].items() if k.startswith('onecommand@')][0])" 2>/dev/null)}"
[ -f "$OC_ROOT/skills/unslop/SKILL.md" ] || OC_ROOT="$HOME/OneCommand"
echo "$OC_ROOT/skills/unslop"
```

1. Read `$OC_ROOT/skills/unslop/SKILL.md`.
2. Pick the command from its routing table that fits: **$ARGUMENTS**
   (only text or a file given → `rewrite`; nothing given → ask for the text).
3. Read the command file in `references/commands/` and the files it links, then run its scanners from the
   skill root (`cd "$OC_ROOT/skills/unslop"`) exactly as it says. A file argument is read in place; pasted
   text goes to the scanners on stdin.
4. Return what the command's output format asks for. A rewrite of a file is written back to that file only
   when the user named the file; otherwise return the text.
