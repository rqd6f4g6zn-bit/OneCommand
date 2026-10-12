---
description: Emil Kowalski's design-engineering skills in one command — polish a UI, build or review animations, audit motion, make a web app feel native on phones, stress-test with worst-case data, prototype variants, pick libraries.
argument-hint: "<task, e.g. 'review the animations in components/' or 'break the contacts table'>"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Resolve the plugin root and load the skill:

```bash
OC_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.claude/plugins/installed_plugins.json')));print([e[0]['installPath'] for k,e in d['plugins'].items() if k.startswith('onecommand@')][0])" 2>/dev/null)}"
[ -f "$OC_ROOT/skills/emil/SKILL.md" ] || OC_ROOT="$HOME/OneCommand"
echo "$OC_ROOT/skills/emil"
```

1. Read `$OC_ROOT/skills/emil/SKILL.md`.
2. Pick the guide(s) from its table that fit this task: **$ARGUMENTS**
   (no task given → read `emil-design-eng` and ask what to polish).
3. Read each chosen `guides/<name>/GUIDE.md` and the files it links, then do the task in the current
   project exactly as the guide says — its order of decisions, its values, its checklist.
4. Report what you changed or found, with `file:line`, and which guide each point comes from.
