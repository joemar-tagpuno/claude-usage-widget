#!/usr/bin/env python3
"""Claude Code status line: live 5h block + today/week/month usage.

Reads the cached snapshot written by collect.py (never blocks on ccusage) and
kicks off a detached background refresh when the cache goes stale.
"""
import json, os, subprocess, sys, time

HOME = os.path.expanduser("~")
DIR = os.path.join(HOME, ".claude", "usage-widget")
CACHE = os.path.join(DIR, "cache.json")
COLLECT = os.path.join(DIR, "collect.py")
FAST_TTL = 120     # refresh active-block data after 2 min
FULL_TTL = 900     # refresh daily/project history after 15 min

C = {
    "dim":   "\033[38;5;245m",
    "sep":   "\033[38;5;240m",
    "cyan":  "\033[38;5;80m",
    "blue":  "\033[38;5;75m",
    "green": "\033[38;5;114m",
    "amber": "\033[38;5;215m",
    "red":   "\033[38;5;203m",
    "mag":   "\033[38;5;176m",
    "bold":  "\033[1m",
    "r":     "\033[0m",
}

def c(key, text):
    if os.environ.get("NO_COLOR"):
        return str(text)
    return f"{C[key]}{text}{C['r']}"

def money(v):
    v = v or 0
    if v >= 1000:
        return f"${v/1000:.1f}k"
    if v >= 100:
        return f"${v:.0f}"
    return f"${v:.2f}"

def toks(v):
    v = v or 0
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= div:
            return f"{v/div:.1f}{unit}"
    return str(int(v))

def short_model(name):
    if not name:
        return "?"
    n = name.replace("claude-", "")
    for fam in ("opus", "sonnet", "haiku", "fable"):
        if fam in n:
            parts = n.split("-")
            try:
                idx = parts.index(fam)
                ver = "-".join(parts[idx + 1:])
                return f"{fam}{'-' + ver if ver else ''}"
            except ValueError:
                return fam
    return n

def maybe_refresh(cache):
    now = time.time()
    blk_ts = (cache.get("block") or {}).get("ts", 0)
    hist_ts = (cache.get("history") or {}).get("ts", 0)
    mode = None
    if now - hist_ts > FULL_TTL:
        mode = "--full"
    elif now - blk_ts > FAST_TTL:
        mode = "--fast"
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

def main():
    try:
        ctx = json.load(sys.stdin)
    except Exception:
        ctx = {}

    try:
        with open(CACHE) as f:
            cache = json.load(f)
    except Exception:
        cache = {}

    maybe_refresh(cache)

    # ---- line 1: where you are + what you're using ----
    ws = ctx.get("workspace") or {}
    cwd = ws.get("current_dir") or ctx.get("cwd") or os.getcwd()
    home_rel = cwd.replace(HOME, "~", 1) if cwd.startswith(HOME) else cwd
    parts = home_rel.split("/")
    short_cwd = "/".join(parts[-2:]) if len(parts) > 2 else home_rel

    model = (ctx.get("model") or {}).get("display_name") or \
            short_model((ctx.get("model") or {}).get("id"))

    mark = "\033[38;5;209m\u2733\033[0m" if not os.environ.get("NO_COLOR") else "*"
    seg1 = [mark + " " + c("blue", short_cwd), c("mag", model)]
    sess_cost = (ctx.get("cost") or {}).get("total_cost_usd")
    if sess_cost:
        seg1.append(c("dim", f"session {money(sess_cost)}"))
    if ctx.get("exceeds_200k_tokens"):
        seg1.append(c("amber", "200k+ ctx"))

    sep = c("sep", " │ ")
    line1 = sep.join(seg1)

    # ---- line 2: live block + rolling totals ----
    blk = cache.get("block") or {}
    hist = cache.get("history") or {}
    seg2 = []

    if blk.get("active"):
        rem = int(blk.get("remaining_min") or 0)
        h, m = divmod(max(rem, 0), 60)
        clock = f"{h}h{m:02d}m" if h else f"{m}m"
        col = "green" if rem > 120 else ("amber" if rem > 30 else "red")
        seg2.append(c(col, f"▸ {clock} left"))
        seg2.append(c("cyan", money(blk.get("cost"))))
        burn = blk.get("burn_cost_hr") or 0
        if burn:
            bcol = "green" if burn < 40 else ("amber" if burn < 100 else "red")
            seg2.append(c(bcol, f"{money(burn)}/hr"))
    elif blk:
        seg2.append(c("dim", "▸ idle"))

    if hist:
        t = hist.get("today") or {}
        w = hist.get("week") or {}
        mo = hist.get("month") or {}
        seg2.append(c("dim", "today ") + c("bold", money(t.get("cost"))))
        seg2.append(c("dim", "wk ") + money(w.get("cost")))
        seg2.append(c("dim", "mo ") + money(mo.get("cost")))
        seg2.append(c("dim", toks(t.get("tokens")) + " tok"))

    if not seg2:
        seg2 = [c("dim", "usage: collecting…")]

    line2 = sep.join(seg2)

    print(line1)
    print(line2)

if __name__ == "__main__":
    main()
