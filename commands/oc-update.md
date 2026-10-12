---
description: Check for a newer OneCommand release and install it now. Use "/oc-update check" to only look, "/oc-update off|on" to switch automatic updates, "/oc-update background off|on" for the hourly background job.
argument-hint: '[check | off | on | status | background off|on]'
allowed-tools: Bash, Read, Edit
---

You are the OneCommand updater. OneCommand updates itself without this command: at the start of every Claude Code session, and — installed by install.sh — hourly in the background (macOS launchd, systemd user timer or cron), which also keeps Codex current. Never during a running build. This command does it on demand.

Resolve the updater script:

```bash
python3 << 'EOF'
import json, os
from pathlib import Path
cands = [os.environ.get("CLAUDE_PLUGIN_ROOT", ""), "${CLAUDE_PLUGIN_ROOT}"]
try:
    reg = json.loads((Path.home() / ".claude/plugins/installed_plugins.json").read_text())
    cands.append(reg["plugins"]["onecommand@local"][0]["installPath"])
except Exception:
    pass
cands += [str(Path.home() / ".claude/plugins/onecommand"), str(Path.home() / "OneCommand")]
root = next((c for c in cands if c and "${" not in c and (Path(c) / "hooks/update.py").exists()), "")
print(f"OC_ROOT={root}" if root else "OC_ROOT=NOT_FOUND")
EOF
```

If `OC_ROOT=NOT_FOUND`: tell the user to re-run `install.sh` from their OneCommand checkout, then stop.

Then act on `$ARGUMENTS`:

| `$ARGUMENTS` | Run |
|---|---|
| *(empty)* | `python3 "$OC_ROOT/hooks/update.py" apply` |
| `check` | `python3 "$OC_ROOT/hooks/update.py" check` |
| `status` | `python3 "$OC_ROOT/hooks/update.py" status` |
| `off` / `on` | set `"auto_update"` to `false` / `true` in `~/.onecommand/config.json` (keep every other key), then run `status` |
| `background off` | set `"background_update": false` in `~/.onecommand/config.json`, then `python3 "$OC_ROOT/hooks/update.py" schedule remove` |
| `background on` | set `"background_update": true`, then `python3 "$OC_ROOT/hooks/update.py" schedule install` |

Show the script's output unchanged, then add one line:
- after `✅ … updated`: "Restart Claude Code (or start a new session) so the new commands and agents are loaded."
- after `… uncommitted changes`: name the checkout path and suggest `git -C <path> status`.
- after `… failed and was rolled back`: the previous version is still installed and working; show `last.detail` from `~/.onecommand/update-state.json`.
- after `… failed to install before`: a fixed release will be picked up automatically; `/oc-update` retries now.
