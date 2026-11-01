#!/bin/bash
# Balance the left/right margins: adds N points of padding to the left of the
# panel to offset macOS's wider right-hand menu inset. Refreshes immediately.
#   ./set-inset.sh 15
set -e
[ -z "$1" ] && { echo "usage: $0 <points, 0-200>"; exit 1; }
python3 - "$1" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.claude/usage-widget/config.json")
c = json.load(open(p))
c["left_inset"] = max(0, min(200, int(sys.argv[1])))
json.dump(c, open(p, "w"), indent=2)
print("left_inset =", c["left_inset"])
PY
open -g "swiftbar://refreshallplugins" 2>/dev/null || true
echo "Refreshed - reopen the menu."
