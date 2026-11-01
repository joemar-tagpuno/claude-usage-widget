#!/bin/bash
# Set the panel width (points) and refresh SwiftBar immediately.
#   ./set-width.sh 500
set -e
[ -z "$1" ] && { echo "usage: $0 <width-in-points, 260-900>"; exit 1; }
CFG="$HOME/.claude/usage-widget/config.json"
python3 - "$1" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.claude/usage-widget/config.json")
c = json.load(open(p))
c["panel_width"] = max(260, min(900, int(sys.argv[1])))
json.dump(c, open(p, "w"), indent=2)
print("panel_width =", c["panel_width"])
PY
open -g "swiftbar://refreshallplugins" 2>/dev/null || true
echo "SwiftBar refreshed - reopen the menu to see it."
