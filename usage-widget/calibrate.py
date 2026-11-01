#!/usr/bin/env python3
"""Turn the estimated LIMITS bars into real ones.

Run /usage inside Claude Code, read off the percentages, then:

    python3 calibrate.py --session 7 --weekly 7 --model 12

Each percentage is paired with the token count ccusage currently reports for
that window, which yields the underlying budget. Re-run whenever the numbers
drift; Anthropic does not publish these limits, so this is the only honest way
to anchor them.
"""
import argparse, datetime, json, os, sys

DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(DIR, "cache.json")
CONFIG = os.path.join(DIR, "config.json")


def load(p, d):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return d


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", type=float, help="Session %% shown by /usage")
    ap.add_argument("--weekly", type=float, help="Weekly %% shown by /usage")
    ap.add_argument("--model", type=float,
                    help="Model-specific weekly %% (e.g. Opus Weekly)")
    ap.add_argument("--plan", help='Plan label, e.g. "MAX 5X"')
    a = ap.parse_args()

    cache = load(CACHE, {})
    cfg = load(CONFIG, {})
    hist = cache.get("history") or {}
    blk = cache.get("block") or {}
    series = {s["date"]: s for s in (hist.get("series") or [])}

    today = datetime.date.today()
    ws = today - datetime.timedelta(days=(today.weekday() + 1) % 7)
    week_tokens = sum((series.get((ws + datetime.timedelta(days=i)).isoformat())
                       or {}).get("tokens", 0) for i in range(7))

    budgets = cfg.setdefault("budgets", {})
    changed = []

    if a.plan:
        cfg["plan_label"] = a.plan
        changed.append(f"plan label -> {a.plan}")

    if a.session is not None:
        if a.session <= 0:
            sys.exit("--session must be > 0 (a 0% reading carries no information)")
        used = blk.get("tokens", 0) or 0
        if not used:
            sys.exit("No active 5-hour block right now; run this while one is open.")
        budgets["session_tokens"] = int(used / (a.session / 100.0))
        changed.append(f"session budget -> {budgets['session_tokens']:,} tokens")

    if a.weekly is not None:
        if a.weekly <= 0:
            sys.exit("--weekly must be > 0")
        budgets["weekly_tokens"] = int(week_tokens / (a.weekly / 100.0))
        changed.append(f"weekly budget  -> {budgets['weekly_tokens']:,} tokens")

    if a.model is not None:
        if a.model <= 0:
            sys.exit("--model must be > 0")
        mw = budgets.setdefault("model_weekly", {"model": "opus", "tokens": None})
        fam = (mw.get("model") or "opus").lower()
        tot = 0
        for i in range(7):
            dt = (ws + datetime.timedelta(days=i)).isoformat()
            for name, tk in ((series.get(dt) or {}).get("models") or {}).items():
                if fam in name.lower():
                    tot += tk
        if not tot:
            sys.exit(f"No {fam} tokens recorded this week.")
        mw["tokens"] = int(tot / (a.model / 100.0))
        changed.append(f"{fam} weekly    -> {mw['tokens']:,} tokens")

    if not changed:
        ap.print_help()
        return

    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    print("Calibrated:")
    for c in changed:
        print("  " + c)
    print("\nThe panel will show real percentages on its next refresh.")


if __name__ == "__main__":
    main()
