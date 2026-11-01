#!/usr/bin/env python3
"""Collect Claude Code usage stats from ccusage into a cache file.

Usage:  collect.py --fast    # active 5h block only (~5s)
        collect.py --full    # block + daily history + per-project (~17s)
"""
import json, os, subprocess, sys, time, datetime, tempfile

HOME = os.path.expanduser("~")
DIR = os.path.join(HOME, ".claude", "usage-widget")
CACHE = os.path.join(DIR, "cache.json")
LOCK = os.path.join(DIR, "collect.lock")
CCUSAGE = os.environ.get("CCUSAGE_BIN") or ""

def find_ccusage():
    global CCUSAGE
    if CCUSAGE and os.path.exists(CCUSAGE):
        return CCUSAGE
    for p in os.environ.get("PATH", "").split(":"):
        c = os.path.join(p, "ccusage")
        if os.path.exists(c):
            CCUSAGE = c
            return c
    # nvm fallback
    nvm = os.path.join(HOME, ".nvm", "versions", "node")
    if os.path.isdir(nvm):
        for v in sorted(os.listdir(nvm), reverse=True):
            c = os.path.join(nvm, v, "bin", "ccusage")
            if os.path.exists(c):
                CCUSAGE = c
                return c
    return None

def run(args, timeout=120):
    exe = find_ccusage()
    if not exe:
        return None
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    node_bin = os.path.dirname(exe)
    env["PATH"] = node_bin + ":" + env.get("PATH", "")
    try:
        out = subprocess.run([exe] + args + ["--json"], capture_output=True,
                             text=True, timeout=timeout, env=env)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except Exception:
        return None

def acquire_lock(max_age=300):
    try:
        if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) > max_age:
            os.unlink(LOCK)
    except OSError:
        pass
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except OSError:
        return False

def release_lock():
    try:
        os.unlink(LOCK)
    except OSError:
        pass

def load_cache():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_cache(data):
    os.makedirs(DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DIR, prefix=".cache-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, CACHE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass

def collect_block():
    d = run(["blocks", "--active"])
    if not d:
        return None
    blocks = d.get("blocks") or []
    active = next((b for b in blocks if b.get("isActive")), None)
    if not active:
        return {"active": False, "ts": time.time()}
    br = active.get("burnRate") or {}
    pr = active.get("projection") or {}
    tc = active.get("tokenCounts") or {}
    return {
        "active": True,
        "ts": time.time(),
        "cost": active.get("costUSD", 0),
        "tokens": active.get("totalTokens", 0),
        "output_tokens": tc.get("outputTokens", 0),
        "start": active.get("startTime"),
        "end": active.get("endTime"),
        "remaining_min": pr.get("remainingMinutes", 0),
        "burn_cost_hr": br.get("costPerHour", 0),
        "burn_tpm": br.get("tokensPerMinute", 0),
        "proj_cost": pr.get("totalCost", 0),
        "models": active.get("models") or [],
        "entries": active.get("entries", 0),
    }

def collect_history():
    d = run(["daily"])
    if not d:
        return None
    days = d.get("daily") or []
    totals = d.get("totals") or {}
    today = datetime.date.today()
    # ccusage weeks start on Sunday
    week_start = today - datetime.timedelta(days=(today.weekday() + 1) % 7)
    month_start = today.replace(day=1)

    def blank():
        return {"cost": 0.0, "tokens": 0, "output": 0, "days": 0}

    agg = {"today": blank(), "week": blank(), "month": blank()}
    models = {}
    series = []
    for day in days:
        try:
            dt = datetime.date.fromisoformat(day.get("date", ""))
        except ValueError:
            continue
        cost = day.get("totalCost", 0) or 0
        toks = day.get("totalTokens", 0) or 0
        outp = day.get("outputTokens", 0) or 0
        per_model = {}
        for mb in day.get("modelBreakdowns") or []:
            per_model[mb.get("modelName", "?")] = sum(
                mb.get(k, 0) or 0 for k in ("inputTokens", "outputTokens",
                                            "cacheCreationTokens", "cacheReadTokens"))
        series.append({"date": day["date"], "cost": round(cost, 2),
                       "tokens": toks, "models": per_model})
        for key, start in (("today", today), ("week", week_start), ("month", month_start)):
            if dt >= start:
                agg[key]["cost"] += cost
                agg[key]["tokens"] += toks
                agg[key]["output"] += outp
                agg[key]["days"] += 1
        if dt >= month_start:
            for mb in day.get("modelBreakdowns") or []:
                name = mb.get("modelName", "?")
                m = models.setdefault(name, {"cost": 0.0, "tokens": 0})
                m["cost"] += mb.get("cost", 0) or 0
                m["tokens"] += sum(mb.get(k, 0) or 0 for k in
                                   ("inputTokens", "outputTokens",
                                    "cacheCreationTokens", "cacheReadTokens"))
    for v in agg.values():
        v["cost"] = round(v["cost"], 2)
    top = sorted(({"name": k, **v} for k, v in models.items()),
                 key=lambda x: -x["cost"])
    for t in top:
        t["cost"] = round(t["cost"], 2)
    return {
        "ts": time.time(),
        **agg,
        "total": {"cost": round(totals.get("totalCost", 0), 2),
                  "tokens": totals.get("totalTokens", 0)},
        "models": top[:6],
        "series": series[-60:],
    }

def resolve_project(encoded):
    """Map ccusage's dash-encoded project path back to a real directory name.

    '-Users-jt-dev-my-app' is ambiguous (dashes encode '/' but also appear in
    names), so walk the filesystem greedily to disambiguate."""
    raw = (encoded or "").split("/")[0]
    if not raw.startswith("-"):
        return raw or "?"
    tokens = [t for t in raw[1:].split("-")]
    cur = "/"
    i = 0
    resolved = []
    while i < len(tokens):
        matched = False
        for j in range(len(tokens), i, -1):
            cand = "-".join(tokens[i:j])
            if cand and os.path.isdir(os.path.join(cur, cand)):
                cur = os.path.join(cur, cand)
                resolved.append(cand)
                i = j
                matched = True
                break
        if not matched:
            resolved.extend(tokens[i:])
            break
    if not resolved:
        return raw
    name = resolved[-1]
    GENERIC = {"code", "src", "app", "apps", "repo", "main", "www",
               "dev", "projects", "packages"}
    if name.lower() in GENERIC and len(resolved) >= 2:
        name = resolved[-2] + "/" + name
    return name

def collect_projects():
    d = run(["session"])
    if not d:
        return None
    sessions = d.get("sessions") or []
    cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    proj = {}
    cache_names = {}
    for s in sessions:
        last = (s.get("lastActivity") or "")[:10]
        if last and last < cutoff:
            continue
        enc = s.get("projectPath") or ""
        # ccusage labels some rows "Unknown Project" and puts the encoded
        # project path in sessionId instead -- fall back to that.
        if not enc.startswith("-"):
            sid = s.get("sessionId") or ""
            if sid.startswith("-"):
                enc = sid
        key = enc.split("/")[0]
        if key not in cache_names:
            cache_names[key] = resolve_project(enc) or s.get("sessionId", "?")
        name = cache_names[key]
        p = proj.setdefault(name, {"cost": 0.0, "tokens": 0, "sessions": 0})
        p["cost"] += s.get("totalCost", 0) or 0
        p["tokens"] += s.get("totalTokens", 0) or 0
        p["sessions"] += 1
    top = sorted(({"name": k, **v} for k, v in proj.items()), key=lambda x: -x["cost"])
    for t in top:
        t["cost"] = round(t["cost"], 2)
    return {"ts": time.time(), "top": top[:6]}

def main():
    mode = "fast"
    if "--full" in sys.argv:
        mode = "full"
    os.makedirs(DIR, exist_ok=True)
    if not acquire_lock():
        return 0
    try:
        cache = load_cache()
        blk = collect_block()
        if blk:
            cache["block"] = blk
        if mode == "full":
            hist = collect_history()
            if hist:
                cache["history"] = hist
            projs = collect_projects()
            if projs:
                cache["projects"] = projs
        cache["generated_at"] = time.time()
        cache["ok"] = bool(cache.get("block") or cache.get("history"))
        save_cache(cache)
    finally:
        release_lock()
    return 0

if __name__ == "__main__":
    sys.exit(main())
