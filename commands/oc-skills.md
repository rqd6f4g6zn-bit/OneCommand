---
description: Show the OneCommand skill library — every skill the plugin can use (its own and all installed ones), or search it by topic.
argument-hint: "[topic, e.g. pdf invoice | landing page | voice]"
allowed-tools: Bash
---

Resolve the plugin root, then show the library. With an argument, search it.

```bash
OC_ROOT="${CLAUDE_PLUGIN_ROOT:-$(python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.claude/plugins/installed_plugins.json')));print([e[0]['installPath'] for k,e in d['plugins'].items() if k.startswith('onecommand@')][0])" 2>/dev/null)}"
[ -f "$OC_ROOT/hooks/skill-catalog.py" ] || OC_ROOT="$HOME/OneCommand"
if [ -n "$ARGUMENTS" ]; then
  python3 "$OC_ROOT/hooks/skill-catalog.py" --project-dir . library --search "$ARGUMENTS"
else
  python3 "$OC_ROOT/hooks/skill-catalog.py" --project-dir . library
fi
```

Show the output to the user as it is, grouped as printed. Then add, in one or two sentences:
- for a search, which skill fits best and in which build phase OneCommand uses it;
- under "recommended, not installed", that installing those plugins adds their skills to every build.

Do not load or run any skill here — this command only shows the library.
