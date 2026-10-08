"""
charts.py: render one team card (target-share donut + snap % bars).

Layout (1920 x 1080):

  [logo] Team Name                                         brand / credit
         Target Share
         Week 4 · vs DET · W 32–26 · 39 targets      <- subscript
                                                    Snap %
     ┌──── donut ────┐                              Share of the team's 75 offensive snaps
     │  headshot     │                              100% ─ ▇ ▇ ▇ ──────────
     │  T McMillan   │   ( 39 )                      75% ─ █ █ █ ──────────
     │  41% · 16 tgt │  TARGETS                      50% ─ █ █ █ ▇ ▇ ──────
     │  1 RZ         │  <- subscript per wedge        25% ─ █ █ █ █ █ ▆ ───
     └───────────────┘                                     names (staggered)

Each player keeps the same color in the donut and in the bars.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
import logging
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import requests  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402
from matplotlib.patches import Circle, Rectangle, Wedge  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from .data import TeamWeek, PlayerLine  # noqa: E402

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "assets" / "fonts"
CACHE_DIR = ROOT / ".cache" / "images"

# ---- look & feel ---------------------------------------------------------- #
W_IN, H_IN, DPI = 16, 9, 120
BG = "#0f1218"
TEXT = "#f2f4f7"
MUTED = "#8b93a1"
GRID = "#262b35"
OTHER_GRAY = "#3a3e47"
CENTER_FILL = "#14171d"
DARK_TEXT = "#14171d"

R_OUT, R_IN = 1.0, 0.36  # donut ring radii
MIN_SHARE_SOLO = 0.05  # players under 5% (or with a single target) go into "Other (n)" ...
MIN_POOL = 2  # ... but only if at least 2 of them (a lone 3% guy keeps his own wedge)
MAX_BARS = 9

# ---- fonts ---------------------------------------------------------------- #
for f in FONT_DIR.glob("*.ttf"):
    font_manager.fontManager.addfont(str(f))
FAMILY = "Jost" if any(FONT_DIR.glob("Jost-*.ttf")) else "DejaVu Sans"
plt.rcParams["font.family"] = FAMILY


# --------------------------------------------------------------------------- #
# Color helpers
# --------------------------------------------------------------------------- #
def _hls(c):
    return colorsys.rgb_to_hls(*to_rgb(c))


def _rgb(h, l, s):
    return colorsys.hls_to_rgb(h % 1.0, max(0, min(1, l)), max(0, min(1, s)))


def luminance(c) -> float:
    r, g, b = to_rgb(c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def team_palette(colors: list[str], n: int) -> list[tuple]:
    """
    Build n distinct, dark-background-friendly colors from the team's official colors.
    Order: primary, secondary, then hue shifts / tints / shades of those, then a slate.
    Near-black colors are lifted so they read on the dark card.
    """
    chroma, neutral = [], []
    for c in colors:
        h, l, s = _hls(c)
        if s > 0.25 and 0.08 < l < 0.85:
            l = max(l, 0.34)  # lift navy / dark brown so wedges don't vanish
            target = chroma
        else:
            target = neutral
        rgb = _rgb(h, l, s)
        if all(np.linalg.norm(np.subtract(rgb, x)) > 0.18 for x in chroma + neutral):
            target.append(rgb)
    if not chroma:
        chroma = [_rgb(0.6, 0.45, 0.5)]

    p = chroma[0]
    ph, pl_, ps = colorsys.rgb_to_hls(*p)
    candidates = list(chroma) + [
        _rgb(ph + 0.045, pl_ + 0.10, ps * 0.9),  # analogous, lighter
        _rgb(ph, 0.42, 0.22),  # team-tinted slate
        _rgb(ph, pl_ - 0.12, ps),  # shade
        _rgb(ph - 0.045, pl_ + 0.04, ps * 0.85),  # analogous other way
        _rgb(ph, pl_ + 0.20, ps * 0.8),  # tint
    ]
    for c in chroma[1:]:
        h, l, s = colorsys.rgb_to_hls(*c)
        candidates += [_rgb(h, l + 0.15, s * 0.85), _rgb(h, l - 0.10, s)]
    candidates += [x for x in neutral if 0.2 < colorsys.rgb_to_hls(*x)[1] < 0.8]
    candidates += [_rgb(ph, 0.30, 0.18), _rgb(ph + 0.5, 0.55, 0.15), _rgb(ph, 0.62, 0.12)]

    out = []
    for c in candidates:
        if all(np.linalg.norm(np.subtract(c, x)) > 0.13 for x in out):
            out.append(c)
    while len(out) < n:  # long tail: alternate lighter/darker versions of what we have
        h, l, s = colorsys.rgb_to_hls(*out[len(out) % max(1, len(chroma))])
        out.append(_rgb(h, 0.25 + 0.5 * ((len(out) * 0.37) % 1), s * 0.7))
    return out[:n]


def accent(colors: list[str]):
    """Brightest usable team color for 'Target Share' text."""
    best = None
    for c in colors:
        h, l, s = _hls(c)
        if s > 0.25:
            cand = _rgb(h, max(l, 0.55), max(s, 0.6))
            if best is None or luminance(cand) > luminance(best):
                best = cand
    return best or to_rgb(MUTED)


# --------------------------------------------------------------------------- #
# Images (headshots, logos) with an on-disk cache and graceful fallback
# --------------------------------------------------------------------------- #
def fetch_image(url: str | None) -> Image.Image | None:
    if not url:
        return None
    # NFL headshots are Cloudinary URLs with f_auto (format chosen per browser); ask for PNG
    url = url.replace("/f_auto,", "/f_png,")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".png")
    if path.exists():
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            path.unlink(missing_ok=True)
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (volumetrics)",
                                                   "Accept": "image/png,image/*;q=0.8"})
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        img.save(path)
        return img
    except Exception as exc:
        log.debug("image fetch failed %s (%s)", url, exc)
        return None


def _font(size: int, weight="SemiBold"):
    f = FONT_DIR / f"Jost-{weight}.ttf"
    return ImageFont.truetype(str(f), size) if f.exists() else ImageFont.load_default()


def avatar(player: PlayerLine, fill, px: int = 256) -> np.ndarray:
    """Round headshot on a white disk; falls back to initials on the player's color."""
    ss = px * 2  # supersample for clean edges
    canvas = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    mask = Image.new("L", (ss, ss), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, ss - 1, ss - 1), fill=255)

    head = fetch_image(player.headshot) or fetch_image(player.headshot_alt)
    if head is not None:
        disk = Image.new("RGBA", (ss, ss), (246, 247, 249, 255))
        w, h = head.size
        side = min(w, h)
        # NFL headshots are framed head-and-shoulders: crop a top-centered square
        crop = head.crop(((w - side) // 2, 0, (w - side) // 2 + side, side)).resize((ss, ss), Image.LANCZOS)
        disk.alpha_composite(crop)
        canvas.paste(disk, (0, 0), mask)
    else:
        r, g, b = [int(v * 255) for v in fill]
        disk = Image.new("RGBA", (ss, ss), (int(r * 0.7), int(g * 0.7), int(b * 0.7), 255))
        canvas.paste(disk, (0, 0), mask)
        initials = "".join(w[0] for w in player.full_name.replace(".", "").split()[:2]).upper()
        d = ImageDraw.Draw(canvas)
        fnt = _font(int(ss * 0.38))
        d.text((ss / 2, ss / 2), initials, font=fnt, fill=(255, 255, 255, 235), anchor="mm")

    ring = ImageDraw.Draw(canvas)
    ring.ellipse((2, 2, ss - 3, ss - 3), outline=(255, 255, 255, 230), width=max(4, ss // 45))
    return np.asarray(canvas.resize((px, px), Image.LANCZOS))


def _circle_image(ax, arr, x, y, diam_px, zorder=5):
    """Draw a round image centered at data (x, y) with an exact on-screen diameter."""
    fig = ax.figure
    bbox = ax.get_position()
    xr, yr = ax.get_xlim(), ax.get_ylim()
    ppx = bbox.width * fig.get_figwidth() * fig.dpi / (xr[1] - xr[0])
    ppy = bbox.height * fig.get_figheight() * fig.dpi / (yr[1] - yr[0])
    rx, ry = diam_px / 2 / ppx, diam_px / 2 / ppy
    ax.imshow(arr, extent=(x - rx, x + rx, y - ry, y + ry), zorder=zorder, aspect="auto",
              interpolation="antialiased", clip_on=False)
    ax.set_xlim(xr)
    ax.set_ylim(yr)
    return ry  # half-height in data units (handy for stacking labels)


# --------------------------------------------------------------------------- #
# Card
# --------------------------------------------------------------------------- #
def _background(fig, tw: TeamWeek):
    h, w = 270, 480
    yy, xx = np.mgrid[0:h, 0:w]
    xx, yy = xx / w, yy / h
    base = np.array(to_rgb(BG))
    glow = np.array(to_rgb(tw.colors[0])) if tw.colors else base
    g1 = np.exp(-(((xx - 0.18) ** 2) / 0.10 + ((yy - 0.15) ** 2) / 0.14))[..., None]
    g2 = np.exp(-(((xx - 0.80) ** 2) / 0.08 + ((yy - 0.75) ** 2) / 0.10))[..., None]
    img = base + (glow - base) * (0.20 * g1 + 0.07 * g2)
    vign = 1 - 0.25 * (((xx - 0.5) ** 2) + ((yy - 0.5) ** 2))[..., None]
    bg = fig.add_axes((0, 0, 1, 1), zorder=-100)
    bg.imshow(np.clip(img * vign, 0, 1), aspect="auto", extent=(0, 1, 0, 1))
    bg.set_axis_off()

    logo = fetch_image(tw.logo_url)
    if logo is not None:  # faint watermark behind the bars, like the reference
        wm = fig.add_axes((0.60, 0.08, 0.38, 0.68), zorder=-90)
        a = np.asarray(logo).astype(float) / 255
        a[..., 3] *= 0.06
        wm.imshow(a)
        wm.set_axis_off()
    return logo


def _header(fig, tw: TeamWeek, logo, brand: str):
    x0 = 0.026
    if logo is not None:
        lax = fig.add_axes((0.018, 0.865, 0.06, 0.11))
        lax.imshow(logo)
        lax.set_axis_off()
        x0 = 0.082
    fig.text(x0, 0.958, tw.team_name, fontsize=31, color=TEXT, weight="medium", va="top")
    fig.text(x0, 0.893, "Target Share", fontsize=20, color=accent(tw.colors), weight="medium", va="top")
    score = f"{tw.result} {tw.team_score}\u2013{tw.opp_score}"
    sub = f"Week {tw.week} · {tw.matchup} · {score} · {tw.total_targets} targets"
    fig.text(x0, 0.848, sub, fontsize=13, color=MUTED, va="top")  # subscript

    fig.text(0.978, 0.962, brand, fontsize=12, color=MUTED, ha="right", va="top", weight="medium")
    credit = "Data: nflverse (pbp, PFR snaps)" + (", FTN charting" if tw.drops_available else "")
    fig.text(0.978, 0.932, credit, fontsize=9.5, color="#5d6573", ha="right", va="top")


def _donut_slices(tw: TeamWeek):
    ranked = tw.by_targets()
    small = [p for p in ranked if p.tgt_share < MIN_SHARE_SOLO or p.targets <= 1]
    solo = [p for p in ranked if p not in small]
    rest = small
    if len(rest) < MIN_POOL:
        solo, rest = solo + rest, []
    return solo, rest


def _box_in_slice(cx, cy, w, h, theta1, theta2, ppd, pad_px=5):
    """True if a w x h label box centered at (cx, cy) sits fully inside the ring slice."""
    for fx in (-0.5, 0, 0.5):
        for fy in (-0.5, 0, 0.5):
            x, y = cx + fx * w, cy + fy * h
            rad = math.hypot(x, y)
            if not (R_IN + pad_px / ppd <= rad <= R_OUT - pad_px / ppd):
                return False
            ang = math.degrees(math.atan2(y, x))
            # unwrap into [theta1, theta1 + 360)
            while ang < theta1:
                ang += 360
            while ang >= theta1 + 360:
                ang -= 360
            margin = math.degrees(pad_px / ppd / max(rad, 1e-6))
            if not (theta1 + margin <= ang <= theta2 - margin):
                return False
    return True


def _wedge_label(ax, p: PlayerLine | None, color, theta1, theta2, share, targets, tw, rest_n=0):
    mid = math.radians((theta1 + theta2) / 2)
    text_c = DARK_TEXT if (p is not None and luminance(color) > 0.55) else TEXT
    sub_c = (0.15, 0.17, 0.2) if text_c == DARK_TEXT else (1, 1, 1, 0.62)
    stat = f"{share:.0%} · {targets} tgt"
    if p is not None:
        sub = f"{p.rz_targets} RZ" + (f" · {p.drops} drop{'s' if p.drops > 1 else ''}" if p.drops else "")
        name = p.name
    else:
        sub, name = None, f"Other ({rest_n})"

    # Pick the biggest label tier that physically fits inside this slice.
    # Size starts from the slice's share (bigger slice -> bigger label, like the reference)
    # and steps down until the stack fits; if nothing fits, text runs along the radius.
    fig = ax.figure
    ppd = ax.get_position().height * fig.get_figheight() * fig.dpi / np.ptp(ax.get_ylim())
    pt = fig.dpi / 72
    tiers = [(0.64, 118, (21, 15, 11)), (0.66, 84, (16, 12, 9.5)),
             (0.67, 56, (12, 9.5, 8)), (0.68, 42, (10.5, 8.5, 7))]
    first = 0 if share >= 0.18 else 1 if share >= 0.10 else 2
    r = diam = fs = None
    for tr, td, tfs in tiers[first:]:
        stack_h = (td + (tfs[0] + tfs[1] + (tfs[2] if sub else 0)) * 1.25 * pt) / ppd
        text_w = max(len(name) * tfs[0], len(stat) * tfs[1], td / pt) * 0.52 * pt / ppd
        for rr in (tr, tr + 0.04, tr - 0.04):
            if _box_in_slice(rr * math.cos(mid), rr * math.sin(mid), text_w, stack_h, theta1, theta2, ppd):
                r, diam, fs = rr, td, tfs
                break
        if r is not None:
            break

    if r is None:
        # thin slice: small headshot near the rim, text running along the radius
        deg = (theta1 + theta2) / 2
        rot = deg if -90 <= ((deg + 180) % 360 - 180) <= 90 else deg + 180
        hx, hy = 0.885 * math.cos(mid), 0.885 * math.sin(mid)
        if p is not None:
            _circle_image(ax, avatar(p, color), hx, hy, 40, zorder=6)
        else:
            ax.add_patch(Circle((hx, hy), 0.05, fill=False, ec=TEXT, lw=1.2, zorder=6))
            ax.text(hx, hy, f"+{rest_n}", ha="center", va="center", fontsize=8.5, color=TEXT, zorder=7)
        ax.text(0.63 * math.cos(mid), 0.63 * math.sin(mid), f"{name}  {stat}", rotation=rot,
                rotation_mode="anchor", ha="center", va="center", fontsize=9, color=text_c,
                weight="medium", zorder=7)
        return

    cx, cy = r * math.cos(mid), r * math.sin(mid)
    # vertical stack: [headshot] name / stat / subscript, centered on the slice anchor
    stack = diam / ppd + (fs[0] + fs[1] + (fs[2] if sub else 0)) * 1.25 / 72 * ax.figure.dpi / ppd
    top = cy + stack / 2
    hy = top - diam / ppd / 2
    if p is not None:
        _circle_image(ax, avatar(p, color), cx, hy, diam, zorder=6)
    else:
        ax.add_patch(Circle((cx, hy), diam / ppd / 2 * 0.9, fill=False, ec=TEXT, lw=1.6, zorder=6))
        ax.text(cx, hy, f"+{rest_n}", ha="center", va="center", fontsize=fs[0], color=TEXT, zorder=7)
    y = top - diam / ppd - 0.012
    for txt, size, col, wt in ((name, fs[0], text_c, "medium"), (stat, fs[1], text_c, "normal"),
                               (sub, fs[2], sub_c, "normal")):
        if not txt:
            continue
        ax.text(cx, y, txt, ha="center", va="top", fontsize=size, color=col, weight=wt, zorder=7)
        y -= size * 1.25 / 72 * ax.figure.dpi / ppd


def _donut(fig, tw: TeamWeek, colors: dict):
    ax = fig.add_axes((0.005, 0.015, 0.52, 0.80))
    ax.set_xlim(-1.06, 1.06)
    ax.set_ylim(-1.06, 1.06)
    ax.set_aspect("equal")
    ax.set_axis_off()

    solo, rest = _donut_slices(tw)
    slices = [(p, colors[p.name], p.targets) for p in solo]
    if rest:
        slices.append((None, to_rgb(OTHER_GRAY), sum(p.targets for p in rest)))

    total = tw.total_targets or 1
    angle = 90.0  # start at 12 o'clock, go clockwise, biggest first, "Other" last
    for p, col, n in slices:
        sweep = 360.0 * n / total
        t1, t2 = angle - sweep, angle
        ax.add_patch(Wedge((0, 0), R_OUT, t1, t2, width=R_OUT - R_IN, fc=col, ec=BG, lw=2.6, zorder=2))
        _wedge_label(ax, p, col, t1, t2, n / total, n, tw, rest_n=len(rest))
        angle = t1

    ax.add_patch(Circle((0, 0), R_IN - 0.015, fc=CENTER_FILL, ec="#272b34", lw=3, zorder=3))
    ax.text(0, 0.045, f"{tw.total_targets}", ha="center", va="center", fontsize=46, color=TEXT,
            weight="medium", zorder=4)
    ax.text(0, -0.135, "TARGETS", ha="center", va="center", fontsize=12, color=MUTED, zorder=4)


def _bars(fig, tw: TeamWeek, colors: dict):
    x0 = 0.575
    fig.text(x0, 0.835, "Snap %", fontsize=21, color=TEXT, weight="medium", va="top")
    fig.text(x0, 0.793, f"Share of the team's {tw.team_snaps} offensive snaps", fontsize=13,
             color=MUTED, va="top")  # subscript

    players = tw.by_snaps()[:MAX_BARS]
    ax = fig.add_axes((x0 + 0.03, 0.125, 0.975 - x0 - 0.03, 0.62))
    n = max(len(players), 1)
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_ylim(0, 1.12)
    ax.set_axis_off()

    for lvl in (0, 0.25, 0.5, 0.75, 1.0):
        ax.plot([-0.6, n - 0.4], [lvl, lvl], color=GRID, lw=1, zorder=0)
        ax.text(-0.7, lvl, f"{lvl:.0%}", ha="right", va="center", fontsize=10.5, color="#6b7380")

    bar_w = 0.64
    ppx = ax.get_position().width * fig.get_figwidth() * fig.dpi / (n + 0.2)
    diam = min(62, bar_w * ppx * 0.92)
    for i, p in enumerate(players):
        col = colors.get(p.name, to_rgb(OTHER_GRAY))
        ax.add_patch(Rectangle((i - bar_w / 2, 0), bar_w, p.snap_pct, fc=col, ec="none", zorder=2))
        ry = _circle_image(ax, avatar(p, col), i, p.snap_pct, diam, zorder=5)
        ax.text(i, p.snap_pct + ry + 0.012, f"{p.snap_pct:.0%}", ha="center", va="bottom",
                fontsize=12.5, color=TEXT, weight="medium", zorder=6)
        # staggered names, two rows, like the reference
        ax.text(i, -0.045 if i % 2 == 0 else -0.105, p.name, ha="center", va="top",
                fontsize=11.5, color="#c9ced6", clip_on=False)


def render_team(tw: TeamWeek, out_path: Path, brand: str = "VOLUMETRICS") -> Path:
    # One color per player, shared by donut and bars: target order first, then snap-only guys
    order = [p.name for p in tw.by_targets()]
    order += [p.name for p in tw.by_snaps() if p.name not in order]
    pal = team_palette(tw.colors, max(len(order), 1))
    colors = {name: pal[i] for i, name in enumerate(order)}

    fig = plt.figure(figsize=(W_IN, H_IN), dpi=DPI, facecolor=BG)
    logo = _background(fig, tw)
    _header(fig, tw, logo, brand)
    _donut(fig, tw, colors)
    _bars(fig, tw, colors)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return out_path
