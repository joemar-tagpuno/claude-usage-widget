#!/bin/bash
# Install the Claude usage widget: SwiftBar panel + Claude Code status line.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.claude/usage-widget"
PLUGDIR="${SWIFTBAR_PLUGIN_DIR:-$HOME/Library/Application Support/SwiftBar/Plugins}"

say() { printf '  %s\n' "$1"; }

echo "Claude usage widget installer"
echo

# ---- dependencies -----------------------------------------------------------
missing=0
if ! command -v ccusage >/dev/null 2>&1 && [ ! -x "$HOME/.nvm/versions/node"/*/bin/ccusage ]; then
  say "MISSING: ccusage   ->  npm install -g ccusage"; missing=1
else
  say "found: ccusage"
fi

PIL_PY=""
for c in "$(command -v python3 || true)" "$HOME/.pyenv/shims/python3" \
         /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -n "$c" ] && [ -x "$c" ] || continue
  if "$c" -c 'import PIL' >/dev/null 2>&1; then PIL_PY="$c"; break; fi
done
if [ -z "$PIL_PY" ]; then
  say "MISSING: Pillow    ->  python3 -m pip install Pillow"
  say "         (the panel needs it; without it the menu degrades to text)"
  missing=1
else
  say "found: Pillow via $PIL_PY"
fi

if [ ! -d "/Applications/SwiftBar.app" ]; then
  say "MISSING: SwiftBar  ->  brew install --cask swiftbar"; missing=1
else
  say "found: SwiftBar"
fi

[ "$missing" -eq 1 ] && { echo; echo "Install the items above, then re-run."; exit 1; }

# ---- files ------------------------------------------------------------------
echo
mkdir -p "$DEST" "$PLUGDIR"
cp "$SRC/usage-widget/"*.py "$SRC/usage-widget/"*.sh "$DEST/"
chmod +x "$DEST"/*.py "$DEST"/*.sh
[ -f "$DEST/config.json" ] || cp "$SRC/usage-widget/config.example.json" "$DEST/config.json"
cp "$SRC/plugins/claude-usage.1m.py" "$PLUGDIR/"
chmod +x "$PLUGDIR/claude-usage.1m.py"
say "installed to $DEST"
say "plugin   -> $PLUGDIR"

# ---- first collection -------------------------------------------------------
say "collecting usage data (about 15s)..."
python3 "$DEST/collect.py" --full || say "collection failed; run it manually later"

# ---- status line (opt-in) ---------------------------------------------------
echo
read -r -p "Add the Claude Code status line too? [y/N] " reply
if [[ "${reply:-}" =~ ^[Yy]$ ]]; then
  python3 - <<'PY'
import json, os, time
p = os.path.expanduser("~/.claude/settings.json")
d = {}
if os.path.exists(p):
    with open(p) as f:
        d = json.load(f)
    os.replace(p, p + ".bak-%d" % time.time())
d["statusLine"] = {"type": "command",
                   "command": 'python3 "$HOME/.claude/usage-widget/statusline.py"',
                   "padding": 0}
with open(p, "w") as f:
    json.dump(d, f, indent=2)
print("  status line configured (previous settings.json backed up)")
PY
fi

# ---- launch -----------------------------------------------------------------
defaults write com.ameba.SwiftBar PluginDirectory -string "$PLUGDIR" 2>/dev/null || true
open -a SwiftBar 2>/dev/null || true
echo
echo "Done. Look for the asterisk in your menu bar."
echo "Percentages start as estimates - see 'Real limits' in the README."
