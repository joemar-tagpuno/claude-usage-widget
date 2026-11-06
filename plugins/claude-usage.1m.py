#!/usr/bin/env python3
# <xbar.title>Claude Code Usage</xbar.title>
# <xbar.version>v2.0</xbar.version>
# <xbar.author>jt</xbar.author>
# <xbar.desc>Claude Code usage panel (limits, tokens by day, tokens by model)</xbar.desc>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
"""SwiftBar widget rendering the Claude Code usage panel as an image."""
import base64, json, os, struct, subprocess, sys, time, glob

HOME = os.path.expanduser("~")
DIR = os.path.join(HOME, ".claude", "usage-widget")
CACHE = os.path.join(DIR, "cache.json")
COLLECT = os.path.join(DIR, "collect.py")
PANEL = os.path.join(DIR, "panel.py")
PYHINT = os.path.join(DIR, ".pil-python")
FAST_TTL, FULL_TTL = 120, 900
DIMC = "#8a8a8e,#98989d"

# ---------------------------------------------------------------------------
# Menu bar label. Uncomment exactly ONE line below.
#
#   timer       time left in the 5-hour block        2h37
#   icon        asterisk only, no text
#   percent     session % of limit                   47%     (see note)
#   weekly      weekly % of limit                    4%      (see note)
#   tokens      tokens used today                    184M
#   cost        today's API-equivalent spend         $49.46
#   cost_timer  the original pairing                 $49.46 - 2h37
#
# Note: percent/weekly are estimates against your own 4-week norm until you
# run calibrate.py (see "Real limits" in the README). cost/cost_timer show
# API-equivalent pricing, which is NOT what a subscription plan bills you.
# ---------------------------------------------------------------------------
MENUBAR = "timer"
# MENUBAR = "icon"
# MENUBAR = "percent"
# MENUBAR = "weekly"
# MENUBAR = "tokens"
# MENUBAR = "cost"
# MENUBAR = "cost_timer"
MONO = "font=Menlo size=12"


def tidy_swiftbar_artifacts():
    """SwiftBar 2.1.1 recreates an empty mirror of the plugin's absolute path
    inside the plugin folder on every launch. Remove it when truly empty."""
    try:
        stray = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Users")
        if not os.path.isdir(stray):
            return
        for _r, _d, files in os.walk(stray):
            if files:
                return
        import shutil
        shutil.rmtree(stray)
    except Exception:
        pass


def pil_python():
    """Locate a python that can import Pillow; remember the answer."""
    try:
        with open(PYHINT) as f:
            cand = f.read().strip()
        if cand and os.path.exists(cand):
            return cand
    except Exception:
        pass
    cands = [sys.executable, os.path.join(HOME, ".pyenv/shims/python3")]
    cands += sorted(glob.glob(os.path.join(HOME, ".pyenv/versions/*/bin/python3")),
                    reverse=True)
    cands += ["/opt/homebrew/bin/python3", "/usr/local/bin/python3",
              "/usr/bin/python3"]
    for c in cands:
        if not c or not os.path.exists(c):
            continue
        try:
            r = subprocess.run([c, "-c", "import PIL"], capture_output=True,
                               timeout=8)
            if r.returncode == 0:
                try:
                    with open(PYHINT, "w") as f:
                        f.write(c)
                except Exception:
                    pass
                return c
        except Exception:
            continue
    return None


def png_size(b64):
    """Logical (point) size of a base64 PNG rendered at 2x."""
    try:
        raw = base64.b64decode(b64[:64] + "=" * (-len(b64[:64]) % 4))
        w, h = struct.unpack(">II", raw[16:24])
        return max(1, w // 2), max(1, h // 2)
    except Exception:
        return None


def refresh_if_stale(cache):
    now = time.time()
    blk_ts = (cache.get("block") or {}).get("ts", 0)
    hist_ts = (cache.get("history") or {}).get("ts", 0)
    mode = "--full" if now - hist_ts > FULL_TTL else (
        "--fast" if now - blk_ts > FAST_TTL else None)
    if not mode:
        return
    lock = os.path.join(DIR, "collect.lock")
    if os.path.exists(lock) and now - os.path.getmtime(lock) < 300:
        return
    try:
        subprocess.Popen([sys.executable, COLLECT, mode],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass


def render(py, *args):
    try:
        r = subprocess.run([py, PANEL, *args], capture_output=True, text=True,
                           timeout=25)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def money(v):
    v = v or 0
    return f"${v:,.0f}" if v >= 1000 else f"${v:,.2f}"


def toks(v):
    v = v or 0
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= div:
            return f"{v/div:.1f}{unit}"
    return str(int(v))


def block_clock(blk):
    if not blk.get("active"):
        return "idle"
    rem = int(blk.get("remaining_min") or 0)
    h, m = divmod(max(rem, 0), 60)
    return f"{h}h{m:02d}" if h else f"{m}m"


def menubar_label(mode, cache, py):
    """Text shown beside the asterisk. See MENUBAR at the top of this file."""
    blk = cache.get("block") or {}
    today = (cache.get("history") or {}).get("today") or {}
    if mode == "icon":
        # A blank glyph, not an empty string: SwiftBar drops title-less items.
        return "\u2800"
    if mode == "timer":
        return block_clock(blk)
    if mode == "tokens":
        return toks(today.get("tokens"))
    if mode == "cost":
        return money(today.get("cost"))
    if mode == "cost_timer":
        c = money(today.get("cost"))
        return f"{c} \u00b7 {block_clock(blk)}" if blk.get("active") else c
    if mode in ("percent", "weekly") and py:
        return render(py, "--label", mode) or block_clock(blk)
    return block_clock(blk)


def main():
    tidy_swiftbar_artifacts()
    try:
        with open(CACHE) as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    refresh_if_stale(cache)

    blk = cache.get("block") or {}
    today = ((cache.get("history") or {}).get("today") or {})
    py = pil_python()

    out = []

    # ---------- menu bar: Claude asterisk + the configured label ----------
    icon = render(py, "--icon") if py else None
    label = menubar_label(MENUBAR, cache, py)
    if icon:
        out.append(f"{label} | image={icon}")
    else:
        out.append(f"{label} | sfimage=asterisk")

    out.append("---")

    # ---------- dropdown: the panel ----------
    panel = render(py) if py else None
    if panel:
        # SwiftBar skips menu items with an empty title, so use a blank glyph
        # (U+2800) and pin the image to its logical size.
        dims = png_size(panel)
        extra = f" width={dims[0]} height={dims[1]}" if dims else ""
        out.append(f"\u2800 | image={panel}{extra}")
    else:
        if py:
            out.append("Panel failed to render | color=" + DIMC)
            out.append(f"Debug: {os.path.basename(py)} {PANEL} | " + MONO)
        else:
            out.append("Panel needs Pillow | color=" + DIMC)
            out.append("Install: pip3 install Pillow | " + MONO)
        for label_, d in (("Today", today),
                          ("Week", (cache.get("history") or {}).get("week") or {}),
                          ("Month", (cache.get("history") or {}).get("month") or {})):
            out.append(f"{label_:<8}{money(d.get('cost')):>10} | {MONO}")

    # No footer rows: the panel is the only item, so nothing else can widen
    # the menu. Refresh happens automatically; from a terminal use
    #   python3 ~/.claude/usage-widget/collect.py --full
    print("\n".join(out))


if __name__ == "__main__":
    main()
