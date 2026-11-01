#!/usr/bin/env python3
"""Render the Claude Code usage panel as a PNG for SwiftBar.

Outputs base64 PNGs: the dropdown panel and the menu bar asterisk icon.
Requires Pillow. Falls back are handled by the caller.
"""
import base64, io, json, math, os, subprocess, sys, datetime

from PIL import Image, ImageDraw, ImageFont

HOME = os.path.expanduser("~")
DIR = os.path.join(HOME, ".claude", "usage-widget")
CACHE = os.path.join(DIR, "cache.json")
CONFIG = os.path.join(DIR, "config.json")

S = 2                      # render scale (retina)
W = 440                    # logical panel width (config: panel_width)
PAD = 18
LEFT = 0                   # extra left padding to offset macOS menu chrome

# SF Pro, with fallbacks for systems where it is absent
FONT_CANDIDATES = [
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]
SFNS = next((f for f in FONT_CANDIDATES if os.path.exists(f)), FONT_CANDIDATES[0])

# Drawn on a transparent background so the panel sits in the menu as native
# content rather than as an opaque block. Two palettes, picked from the system
# appearance; translucent greys so they read against menu vibrancy.
DARK = {
    "ORANGE":     (224, 128, 95, 255),
    "TEXT":       (240, 237, 232, 255),
    "TEXT_DIM":   (176, 170, 162, 255),
    "TEXT_FAINT": (140, 134, 126, 255),
    "TRACK":      (255, 255, 255, 38),
    "BAR_GREY":   (198, 193, 186, 255),
    "PILL_BG":    (255, 255, 255, 20),
    "PILL_FILL":  (255, 255, 255, 40),
    "DIVIDER":    (255, 255, 255, 28),
}
LIGHT = {
    "ORANGE":     (192, 94, 62, 255),
    "TEXT":       (26, 25, 23, 255),
    "TEXT_DIM":   (95, 90, 84, 255),
    "TEXT_FAINT": (130, 124, 117, 255),
    "TRACK":      (0, 0, 0, 36),
    "BAR_GREY":   (92, 88, 82, 255),
    "PILL_BG":    (0, 0, 0, 18),
    "PILL_FILL":  (0, 0, 0, 38),
    "DIVIDER":    (0, 0, 0, 26),
}
ORANGE = TEXT = TEXT_DIM = TEXT_FAINT = TRACK = BAR_GREY = None
PILL_BG = PILL_FILL = DIVIDER = None


def detect_appearance():
    try:
        r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                           capture_output=True, text=True, timeout=3)
        return "dark" if "Dark" in r.stdout else "light"
    except Exception:
        return "dark"


def set_theme(mode="auto"):
    if mode not in ("dark", "light"):
        mode = detect_appearance()
    globals().update(DARK if mode == "dark" else LIGHT)
    return mode


def px(v):
    return int(round(v * S))


_font_cache = {}


def sf(size, weight=400):
    key = (size, weight)
    if key in _font_cache:
        return _font_cache[key]
    f = ImageFont.truetype(SFNS, px(size))
    try:
        # axes order: Width, Optical Size, GRAD, Weight
        f.set_variation_by_axes([100, px(size), 0, weight])
    except Exception:
        pass
    _font_cache[key] = f
    return f


def text_w(d, s, font, tracking=0):
    if not tracking:
        return d.textlength(s, font=font)
    return sum(d.textlength(c, font=font) for c in s) + tracking * max(0, len(s) - 1)


def draw_text(d, xy, s, font, fill, tracking=0, anchor_right=False):
    x, y = xy
    if anchor_right:
        x -= text_w(d, s, font, tracking)
    if not tracking:
        d.text((x, y), s, font=font, fill=fill)
        return
    for c in s:
        d.text((x, y), c, font=font, fill=fill)
        x += d.textlength(c, font=font) + tracking


def asterisk(d, cx, cy, r, color, rays=8, rot=0.0):
    """Claude's tapered asterisk mark."""
    w0 = r * 0.30   # width at centre
    w1 = r * 0.085  # width at tip
    for i in range(rays):
        a = rot + i * 2 * math.pi / rays
        dx, dy = math.cos(a), math.sin(a)
        pxp, pyp = -dy, dx
        pts = [
            (cx + pxp * w0 / 2, cy + pyp * w0 / 2),
            (cx + dx * r + pxp * w1 / 2, cy + dy * r + pyp * w1 / 2),
            (cx + dx * r - pxp * w1 / 2, cy + dy * r - pyp * w1 / 2),
            (cx - pxp * w0 / 2, cy - pyp * w0 / 2),
        ]
        d.polygon(pts, fill=color)
    d.ellipse([cx - w0 / 2, cy - w0 / 2, cx + w0 / 2, cy + w0 / 2], fill=color)


def bar(d, x, y, w, h, frac, fill, track=None):
    # resolved at call time: the palette is swapped in by set_theme()
    track = TRACK if track is None else track
    r = h / 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=track)
    fw = max(0.0, min(1.0, frac)) * w
    if fw > 0.5:
        d.rounded_rectangle([x, y, x + max(fw, h), y + h], radius=r, fill=fill)


def fmt_tokens(v):
    v = v or 0
    if v >= 1e9:
        return f"{v/1e9:.1f}B"
    if v >= 1e6:
        return f"{v/1e6:.1f}M"
    if v >= 1e3:
        return f"{v/1e3:.1f}K"
    return str(int(v))


def fmt_dur(minutes):
    minutes = int(max(0, minutes))
    d_, rem = divmod(minutes, 1440)
    h, m = divmod(rem, 60)
    if d_:
        return f"{d_}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def short_model(name):
    n = (name or "").replace("claude-", "")
    parts = n.split("-")
    fam = parts[0].capitalize() if parts else "?"
    ver = ".".join(p for p in parts[1:] if p.isdigit())
    return f"{fam} {ver}".strip() if ver else fam


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def compute(cache, cfg):
    """Build the rows the panel draws."""
    hist = cache.get("history") or {}
    blk = cache.get("block") or {}
    series = hist.get("series") or []
    by_date = {s["date"]: s for s in series}

    today = datetime.date.today()

    # ---- tokens by day: last 7 days ----
    days = []
    for i in range(6, -1, -1):
        dt = today - datetime.timedelta(days=i)
        row = by_date.get(dt.isoformat()) or {}
        label = "Today" if i == 0 else dt.strftime("%a")
        days.append({"label": label, "tokens": row.get("tokens", 0),
                     "is_today": i == 0})

    # ---- tokens by model over those 7 days ----
    models = {}
    for i in range(7):
        dt = (today - datetime.timedelta(days=i)).isoformat()
        for name, tk in ((by_date.get(dt) or {}).get("models") or {}).items():
            models[name] = models.get(name, 0) + tk
    model_rows = sorted(({"name": short_model(k), "tokens": v}
                         for k, v in models.items()), key=lambda r: -r["tokens"])

    # ---- limits ----
    week_start = today - datetime.timedelta(days=(today.weekday() + 1) % 7)
    week_tokens = sum((by_date.get((week_start + datetime.timedelta(days=i)).isoformat())
                       or {}).get("tokens", 0) for i in range(7))
    now = datetime.datetime.now()
    next_week = datetime.datetime.combine(week_start + datetime.timedelta(days=7),
                                          datetime.time.min)
    week_reset_min = (next_week - now).total_seconds() / 60

    budgets = (cfg.get("budgets") or {})
    est = False

    # baseline fallback: median of the last 4 complete weeks
    def baseline_week():
        weeks = {}
        for s in series:
            try:
                dt = datetime.date.fromisoformat(s["date"])
            except Exception:
                continue
            ws = dt - datetime.timedelta(days=(dt.weekday() + 1) % 7)
            if ws >= week_start:
                continue
            weeks[ws] = weeks.get(ws, 0) + s.get("tokens", 0)
        vals = sorted(weeks.values())[-4:]
        return (sorted(vals)[len(vals) // 2] if vals else 0)

    wk_budget = budgets.get("weekly_tokens")
    if not wk_budget:
        wk_budget = baseline_week() or 1
        est = True
    sess_budget = budgets.get("session_tokens")
    if not sess_budget:
        sess_budget = max(1, int(wk_budget / 14))   # ~2 heavy blocks/day
        est = True

    limits = [{
        "name": "Session",
        "pct": (blk.get("tokens", 0) or 0) / sess_budget if blk.get("active") else 0.0,
        "reset": fmt_dur(blk.get("remaining_min", 0)) if blk.get("active") else "idle",
    }, {
        "name": "Weekly",
        "pct": week_tokens / wk_budget,
        "reset": fmt_dur(week_reset_min),
    }]

    focus = (budgets.get("model_weekly") or {}).get("model") or "opus"
    focus_tokens = sum(v for k, v in models.items() if focus in k.lower())
    focus_budget = (budgets.get("model_weekly") or {}).get("tokens") or wk_budget
    limits.append({
        "name": f"{focus.capitalize()} Weekly",
        "pct": focus_tokens / focus_budget if focus_budget else 0,
        "reset": fmt_dur(week_reset_min),
    })

    return {"limits": limits, "days": days, "models": model_rows,
            "estimated": est, "plan": cfg.get("plan_label") or ""}


def render_panel(data):
    rows_h = (len(data["limits"]) * 54 + len(data["days"]) * 24
              + len(data["models"]) * 30)
    H = 96 + 26 + rows_h + 26 + 26 + (24 if data["estimated"] else 0) + 18
    img = Image.new("RGBA", (px(W), px(H)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, x1 = px(PAD + LEFT), px(W - PAD)
    inner_w = x1 - x0

    # ---------- header ----------
    asterisk(d, px(PAD + LEFT + 11), px(34), px(12), ORANGE)
    draw_text(d, (px(PAD + LEFT + 32), px(22)), "Claude Code", sf(15.5, 590), TEXT)
    if data["plan"]:
        draw_text(d, (px(PAD + LEFT + 33), px(44)), data["plan"].upper(), sf(9.5, 560),
                  TEXT_DIM, tracking=px(0.9))

    y = 70
    d.line([x0, px(y), x1, px(y)], fill=DIVIDER, width=max(1, S // 2))
    y += 16

    def section(label, y):
        draw_text(d, (x0, px(y)), label, sf(9.5, 600), TEXT_FAINT, tracking=px(1.0))
        return y + 18

    # ---------- limits ----------
    y = section("LIMITS", y)
    for lim in data["limits"]:
        draw_text(d, (x0, px(y)), lim["name"], sf(13.5, 560), TEXT)
        draw_text(d, (x1, px(y + 1)), f"{lim['pct']*100:.0f}%", sf(11.5, 500),
                  TEXT_DIM, anchor_right=True)
        bar(d, x0, px(y + 21), inner_w, px(4), lim["pct"], ORANGE)
        draw_text(d, (x0, px(y + 31)), f"Resets in {lim['reset']}", sf(10.5, 450),
                  TEXT_FAINT)
        y += 54

    y += 2
    d.line([x0, px(y), x1, px(y)], fill=DIVIDER, width=max(1, S // 2))
    y += 14

    # ---------- tokens by day ----------
    y = section("TOKENS BY DAY", y)
    peak = max((r["tokens"] for r in data["days"]), default=0) or 1
    lab_w, val_w = 46, 62
    bx = x0 + px(lab_w)
    bw = inner_w - px(lab_w + val_w)
    for r in data["days"]:
        strong = r["is_today"]
        draw_text(d, (x0, px(y + 1)), r["label"], sf(11.5, 600 if strong else 450),
                  TEXT if strong else TEXT_DIM)
        bar(d, bx, px(y + 6), bw, px(4), r["tokens"] / peak,
            TEXT if strong else BAR_GREY)
        draw_text(d, (x1, px(y + 1)), fmt_tokens(r["tokens"]), sf(11.5, 500),
                  TEXT if strong else TEXT_DIM, anchor_right=True)
        y += 24

    y += 6
    d.line([x0, px(y), x1, px(y)], fill=DIVIDER, width=max(1, S // 2))
    y += 14

    # ---------- tokens by model ----------
    y = section("TOKENS BY MODEL", y)
    mpeak = max((r["tokens"] for r in data["models"]), default=0) or 1
    for r in data["models"]:
        h = px(24)
        d.rounded_rectangle([x0, px(y), x1, px(y) + h], radius=px(5), fill=PILL_BG)
        fw = max(px(10), (r["tokens"] / mpeak) * inner_w)
        d.rounded_rectangle([x0, px(y), x0 + fw, px(y) + h], radius=px(5),
                            fill=PILL_FILL)
        draw_text(d, (x0 + px(9), px(y + 5)), r["name"], sf(11.5, 520), TEXT)
        draw_text(d, (x1 - px(9), px(y + 5)), fmt_tokens(r["tokens"]),
                  sf(11.5, 480), TEXT_DIM, anchor_right=True)
        y += 30

    if data["estimated"]:
        y += 2
        draw_text(d, (x0, px(y)), "Percentages estimated vs your own 4-week norm",
                  sf(9.5, 450), TEXT_FAINT)

    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(72 * S, 72 * S))
    return base64.b64encode(buf.getvalue()).decode()


def render_icon():
    size = 15
    img = Image.new("RGBA", (px(size), px(size)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    asterisk(d, px(size / 2), px(size / 2), px(size / 2 - 1), ORANGE)
    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(72 * S, 72 * S))
    return base64.b64encode(buf.getvalue()).decode()


def main():
    cache = load(CACHE, {})
    cfg = load(CONFIG, {})
    set_theme(cfg.get("theme", "auto"))
    try:
        w = max(260, min(900, int(cfg.get("panel_width") or W)))
        # macOS reserves ~65pt to the right of an image menu item and ~15pt to
        # its left. Padding the left by the difference centres the content in
        # the menu instead of leaving a one-sided gap.
        left = max(0, min(200, int(cfg.get("left_inset", 50))))
        globals()["LEFT"] = left
        globals()["W"] = w + left
        # The visible margin is macOS menu chrome plus this internal padding.
        # Only the latter is ours, so keep it small to minimise the gap.
        globals()["PAD"] = max(0, min(40, int(cfg.get("padding", 18))))
    except (TypeError, ValueError):
        pass
    data = compute(cache, cfg)
    if "--label" in sys.argv:
        # Text for the menu bar, for modes that need compute()'s derived values.
        mode = sys.argv[sys.argv.index("--label") + 1]
        data = compute(cache, cfg)
        if mode == "percent":
            print(f"{data['limits'][0]['pct'] * 100:.0f}%")
        elif mode == "weekly":
            print(f"{data['limits'][1]['pct'] * 100:.0f}%")
    elif "--icon" in sys.argv:
        print(render_icon())
    elif "--preview" in sys.argv:
        out = sys.argv[sys.argv.index("--preview") + 1]
        with open(out, "wb") as f:
            f.write(base64.b64decode(render_panel(data)))
        print(out)
    else:
        print(render_panel(data))


if __name__ == "__main__":
    main()
