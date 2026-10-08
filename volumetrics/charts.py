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
import os
from dataclasses import dataclass, field
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
DPI = 120
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
_FAILED: set[str] = set()  # don't retry a dead URL for every chart it appears on
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (volumetrics)", "Accept": "image/png,image/*;q=0.8"})


_MEM: dict[str, Image.Image] = {}  # in-process cache: each photo is used up to 8 times per team


def fetch_image(url: str | None) -> Image.Image | None:
    if not url or url in _FAILED:
        return None
    if url in _MEM:
        return _MEM[url]
    img = _fetch_image(url)
    if img is None:
        _FAILED.add(url)  # remember the original URL too, so it's never retried this run
    else:
        _MEM[url] = img
    return img


def _fetch_image(url: str) -> Image.Image | None:
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
        r = _SESSION.get(url, timeout=8)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        img.save(tmp, format="PNG")
        os.replace(tmp, path)  # atomic, so parallel workers never read a half-written file
        return img
    except Exception as exc:
        log.debug("image fetch failed %s (%s)", url, exc)
        _FAILED.add(url)
        return None


def _font(size: int, weight="SemiBold"):
    f = FONT_DIR / f"Jost-{weight}.ttf"
    return ImageFont.truetype(str(f), size) if f.exists() else ImageFont.load_default()


_AVATARS: dict[tuple, np.ndarray] = {}


def avatar(player: PlayerLine, fill, px: int = 256) -> np.ndarray:
    """Round headshot on a white disk; falls back to initials on the player's color."""
    key = (player.headshot, player.headshot_alt, player.full_name, tuple(round(c, 3) for c in fill[:3]), px)
    if key not in _AVATARS:
        _AVATARS[key] = _avatar(player, fill, px)
    return _AVATARS[key]


def _avatar(player: PlayerLine, fill, px: int = 256) -> np.ndarray:
    ss = px * 2  # supersample for clean edges
    canvas = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    mask = Image.new("L", (ss, ss), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, ss - 1, ss - 1), fill=255)

    head = fetch_image(player.headshot) or fetch_image(player.headshot_alt)
    if head is not None:
        disk = Image.new("RGBA", (ss, ss), (246, 247, 249, 255))
        w, h = head.size
        side = int(min(w, h) * 0.86)
        # Headshots are framed head-and-shoulders: crop a slightly tight, top-centered square
        top = int(h * 0.02)
        crop = head.crop(((w - side) // 2, top, (w - side) // 2 + side, top + side)).resize((ss, ss), Image.LANCZOS)
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
# --------------------------------------------------------------------------- #
# Layouts: "landscape" (1920x1080, like the reference, for desktop/posting)
#          "portrait"  (1080x1920, story-sized, what phones get)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Layout:
    name: str
    size: tuple[float, float]  # inches at DPI
    font: dict  # point sizes by role
    tiers: tuple  # wedge label tiers: (headshot px, (name, stat, sub) pt), biggest first
    radial_head: int  # headshot px on thin slices
    bar_head: int  # max headshot px on bars
    logo: tuple  # header logo rect
    text_x: tuple[float, float]  # header text x (with logo, without)
    head_y: tuple[float, float, float]  # team name, "Target Share", subscript
    donut: tuple
    snap_xy: tuple[float, float, float]  # x, title y, subscript y
    bars: tuple
    watermark: tuple
    glow: tuple  # (x, y) of the team-color glow, 0..1 from top-left
    footer: bool  # brand + credit at the bottom instead of top-right
    name_rows_px: tuple = (8, 1.35)  # bar name stagger: first row offset, row gap (x font px)


LANDSCAPE = Layout(
    name="landscape", size=(16, 9),
    font=dict(team=31, ts=20, sub=13, brand=12, credit=9.5, center_num=46, center_lbl=12,
              snap_title=21, snap_sub=13, pct=12.5, names=11.5, ytick=10.5, radial=9, radial_plus=8.5),
    tiers=((118, (21, 15, 11)), (84, (16, 12, 9.5)), (56, (12, 9.5, 8)), (42, (10.5, 8.5, 7))),
    radial_head=40, bar_head=62,
    logo=(0.018, 0.865, 0.06, 0.11), text_x=(0.082, 0.026), head_y=(0.958, 0.893, 0.848),
    donut=(0.01, 0.015, 0.52, 0.80), snap_xy=(0.575, 0.835, 0.793),
    bars=(0.605, 0.125, 0.37, 0.62), watermark=(0.60, 0.08, 0.38, 0.68),
    glow=(0.18, 0.15), footer=False,
)

PORTRAIT = Layout(
    name="portrait", size=(9, 16),
    font=dict(team=38, ts=25, sub=18, brand=15, credit=12, center_num=66, center_lbl=17,
              snap_title=28, snap_sub=18, pct=19, names=16.5, ytick=14, radial=13, radial_plus=12),
    tiers=((158, (28, 20, 15)), (112, (21.5, 16.5, 13)), (78, (16.5, 13, 11.5)), (58, (13.5, 11.5, 10.5))),
    radial_head=54, bar_head=78,
    logo=(0.035, 0.910, 0.13, 0.074), text_x=(0.185, 0.045), head_y=(0.977, 0.942, 0.915),
    donut=(0.0, 0.403, 1.0, 0.492), snap_xy=(0.06, 0.392, 0.366),
    bars=(0.135, 0.100, 0.83, 0.225), watermark=(0.12, 0.06, 0.82, 0.30),
    glow=(0.20, 0.06), footer=True,
)


def _background(fig, tw: TeamWeek, L: Layout):
    w, h = (480, 270) if L.size[0] > L.size[1] else (270, 480)
    yy, xx = np.mgrid[0:h, 0:w]
    xx, yy = xx / w, yy / h
    base = np.array(to_rgb(BG))
    glow = np.array(to_rgb(tw.colors[0])) if tw.colors else base
    gx, gy = L.glow
    g1 = np.exp(-(((xx - gx) ** 2) / 0.10 + ((yy - gy) ** 2) / 0.14))[..., None]
    g2 = np.exp(-(((xx - (1 - gx)) ** 2) / 0.08 + ((yy - (1 - gy)) ** 2) / 0.10))[..., None]
    img = base + (glow - base) * (0.20 * g1 + 0.07 * g2)
    vign = 1 - 0.25 * (((xx - 0.5) ** 2) + ((yy - 0.5) ** 2))[..., None]
    bg = fig.add_axes((0, 0, 1, 1), zorder=-100)
    bg.imshow(np.clip(img * vign, 0, 1), aspect="auto", extent=(0, 1, 0, 1))
    bg.set_axis_off()

    logo = fetch_image(tw.logo_url)
    if logo is not None:  # faint watermark behind the bars, like the reference
        wm = fig.add_axes(L.watermark, zorder=-90)
        a = np.asarray(logo).astype(float) / 255
        a[..., 3] *= 0.06
        wm.imshow(a)
        wm.set_axis_off()
    return logo


def _header(fig, tw: TeamWeek, logo, brand: str, L: Layout, kind: str = "targets"):
    F = L.font
    x0 = L.text_x[1]
    if logo is not None:
        lax = fig.add_axes(L.logo)
        lax.imshow(logo)
        lax.set_axis_off()
        x0 = L.text_x[0]
    y_name, y_ts, y_sub = L.head_y
    fig.text(x0, y_name, tw.team_name, fontsize=F["team"], color=TEXT, weight="medium", va="top")
    title, subtitle = (tw.rb_title, tw.rb_subtitle) if kind == "rb" else (tw.title, tw.subtitle)
    fig.text(x0, y_ts, title, fontsize=F["ts"], color=accent(tw.colors), weight="medium", va="top")
    fig.text(x0, y_sub, subtitle, fontsize=F["sub"], color=MUTED, va="top")  # subscript

    credit = "Data: nflverse (pbp, PFR snaps)" + (", FTN charting" if tw.drops_available else "")
    if L.footer:
        fig.text(0.045, 0.022, brand, fontsize=F["brand"], color=MUTED, ha="left", va="bottom", weight="medium")
        fig.text(0.955, 0.022, credit, fontsize=F["credit"], color="#5d6573", ha="right", va="bottom")
    else:
        fig.text(0.978, 0.962, brand, fontsize=F["brand"], color=MUTED, ha="right", va="top", weight="medium")
        fig.text(0.978, 0.932, credit, fontsize=F["credit"], color="#5d6573", ha="right", va="top")


def _donut_slices(tw: TeamWeek, metric: str = "targets"):
    if metric == "carries":
        ranked, val, share = tw.by_carries(), (lambda p: p.carries), (lambda p: p.rush_share)
    else:
        ranked, val, share = tw.by_targets(), (lambda p: p.targets), (lambda p: p.tgt_share)
    small = [p for p in ranked if share(p) < MIN_SHARE_SOLO or val(p) <= 1]
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
            while ang < theta1:  # unwrap into [theta1, theta1 + 360)
                ang += 360
            while ang >= theta1 + 360:
                ang -= 360
            margin = math.degrees(pad_px / ppd / max(rad, 1e-6))
            if not (theta1 + margin <= ang <= theta2 - margin):
                return False
    return True


def _wedge_label(ax, p: PlayerLine | None, color, theta1, theta2, share, targets, L: Layout, rest_n=0,
                 metric: str = "targets"):
    mid = math.radians((theta1 + theta2) / 2)
    text_c = DARK_TEXT if (p is not None and luminance(color) > 0.55) else TEXT
    sub_c = (0.15, 0.17, 0.2) if text_c == DARK_TEXT else (1, 1, 1, 0.62)
    stat = f"{share:.0%} · {targets} {'car' if metric == 'carries' else 'tgt'}"
    if p is not None:
        if metric == "carries":  # subscript: yards, plus goal-line carries when he got any
            sub = f"{p.rush_yds} yds" + (f" · {p.gl_carries} GL" if p.gl_carries else "")
        else:
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
    first = 0 if share >= 0.18 else 1 if share >= 0.10 else 2
    # Also slide the label along the slice (big diagonal slices fit a tall label better
    # nearer 3 or 9 o'clock than at their exact middle).
    sweep_deg = theta2 - theta1
    angles = [mid] + [math.radians((theta1 + theta2) / 2 + sgn * f * sweep_deg)
                      for f in (0.12, 0.22, 0.30) for sgn in (1, -1)]
    r = diam = fs = None
    for i, (td, tfs) in enumerate(L.tiers[first:], start=first):
        tr = 0.64 + 0.01 * i
        stack_h = (td + (tfs[0] + tfs[1] + (tfs[2] if sub else 0)) * 1.25 * pt) / ppd
        text_w = max(len(name) * tfs[0], len(stat) * tfs[1], td / pt) * 0.52 * pt / ppd
        for ang in angles:
            for rr in (tr, tr + 0.04, tr - 0.04):
                if _box_in_slice(rr * math.cos(ang), rr * math.sin(ang), text_w, stack_h, theta1, theta2, ppd):
                    r, diam, fs, mid = rr, td, tfs, ang
                    break
            if r is not None:
                break
        if r is not None:
            break

    F = L.font
    if r is None:
        mid = math.radians((theta1 + theta2) / 2)
        # thin slice: small headshot near the rim, text running along the radius
        deg = (theta1 + theta2) / 2
        rot = deg if -90 <= ((deg + 180) % 360 - 180) <= 90 else deg + 180
        hx, hy = 0.885 * math.cos(mid), 0.885 * math.sin(mid)
        if p is not None:
            _circle_image(ax, avatar(p, color), hx, hy, L.radial_head, zorder=6)
        else:
            ax.add_patch(Circle((hx, hy), L.radial_head / 2 / ppd, fill=False, ec=TEXT, lw=1.2, zorder=6))
            ax.text(hx, hy, f"+{rest_n}", ha="center", va="center", fontsize=F["radial_plus"], color=TEXT, zorder=7)
        # Text runs along the radius between the center hole and the headshot. Use two lines
        # (name / stat) when the slice is wide enough, otherwise one; shrink until it fits.
        r0 = R_IN + 8 / ppd
        r1 = 0.885 - (L.radial_head / 2 + 8) / ppd
        rc = (r0 + r1) / 2
        arc_px = rc * math.radians(theta2 - theta1) * ppd  # slice width at the text, px
        size = F["radial"]
        while True:
            two = arc_px >= 2 * 1.2 * size * pt + 6
            longest = max(len(name), len(stat)) if two else len(f"{name}  {stat}")
            if size <= 6 or longest * size * 0.50 * pt / ppd <= (r1 - r0):
                break
            size -= 0.5
        line = f"{name}\n{stat}" if two else f"{name}  {stat}"
        ax.text(rc * math.cos(mid), rc * math.sin(mid), line, rotation=rot,
                rotation_mode="anchor", ha="center", va="center", multialignment="center",
                fontsize=size, color=text_c, weight="medium", zorder=7, linespacing=1.15)
        return

    cx, cy = r * math.cos(mid), r * math.sin(mid)
    # vertical stack: [headshot] name / stat / subscript, centered on the slice anchor
    stack = diam / ppd + (fs[0] + fs[1] + (fs[2] if sub else 0)) * 1.25 * pt / ppd
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
        y -= size * 1.25 * pt / ppd


def _donut(fig, tw: TeamWeek, colors: dict, L: Layout, metric: str = "targets"):
    # Square axes (in inches) so the ring is a true circle: the round headshots use
    # aspect="auto" images, which would otherwise stretch the donut into an oval.
    x, y, w, h = L.donut
    W, H = fig.get_figwidth(), fig.get_figheight()
    side = min(w * W, h * H)
    rect = (x + (w * W - side) / 2 / W, y + (h * H - side) / 2 / H, side / W, side / H)
    ax = fig.add_axes(rect)
    lim = 1.06 if L.name == "landscape" else 1.03
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_axis_off()

    val = (lambda p: p.carries) if metric == "carries" else (lambda p: p.targets)
    solo, rest = _donut_slices(tw, metric)
    slices = [(p, colors.get(p.name, to_rgb(OTHER_GRAY)), val(p)) for p in solo]
    if rest:
        slices.append((None, to_rgb(OTHER_GRAY), sum(val(p) for p in rest)))

    total = (tw.team_carries if metric == "carries" else tw.total_targets) or 1
    angle = 90.0  # start at 12 o'clock, go clockwise, biggest first, "Other" last
    for p, col, n in slices:
        sweep = 360.0 * n / total
        t1, t2 = angle - sweep, angle
        ax.add_patch(Wedge((0, 0), R_OUT, t1, t2, width=R_OUT - R_IN, fc=col, ec=BG, lw=2.6, zorder=2))
        _wedge_label(ax, p, col, t1, t2, n / total, n, L, rest_n=len(rest), metric=metric)
        angle = t1

    F = L.font
    ax.add_patch(Circle((0, 0), R_IN - 0.015, fc=CENTER_FILL, ec="#272b34", lw=3, zorder=3))
    ax.text(0, 0.045, f"{tw.team_carries if metric == 'carries' else tw.total_targets}", ha="center", va="center",
            fontsize=F["center_num"], color=TEXT, weight="medium", zorder=4)
    ax.text(0, -0.135, "CARRIES" if metric == "carries" else "TARGETS", ha="center", va="center",
            fontsize=F["center_lbl"], color=MUTED, zorder=4)


def _bars(fig, tw: TeamWeek, colors: dict, L: Layout):
    F = L.font
    x0, ty, sy = L.snap_xy
    fig.text(x0, ty, "Snap %", fontsize=F["snap_title"], color=TEXT, weight="medium", va="top")
    fig.text(x0, sy, tw.snap_subtitle, fontsize=F["snap_sub"], color=MUTED, va="top")  # subscript

    players = tw.by_snaps()[:MAX_BARS]
    ax = fig.add_axes(L.bars)
    n = max(len(players), 1)
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_ylim(0, 1.12)
    ax.set_axis_off()

    for lvl in (0, 0.25, 0.5, 0.75, 1.0):
        ax.plot([-0.6, n - 0.4], [lvl, lvl], color=GRID, lw=1, zorder=0)
        ax.text(-0.7, lvl, f"{lvl:.0%}", ha="right", va="center", fontsize=F["ytick"], color="#6b7380")

    pt = fig.dpi / 72
    ppy = ax.get_position().height * fig.get_figheight() * fig.dpi / 1.12  # px per data unit (y)
    bar_w = 0.64
    ppx = ax.get_position().width * fig.get_figwidth() * fig.dpi / (n + 0.2)
    diam = min(L.bar_head, bar_w * ppx * 0.92)
    row1 = L.name_rows_px[0] / ppy
    row2 = (L.name_rows_px[0] + F["names"] * pt * L.name_rows_px[1]) / ppy
    for i, p in enumerate(players):
        col = colors.get(p.name, to_rgb(OTHER_GRAY))
        ax.add_patch(Rectangle((i - bar_w / 2, 0), bar_w, p.snap_pct, fc=col, ec="none", zorder=2))
        ry = _circle_image(ax, avatar(p, col), i, p.snap_pct, diam, zorder=5)
        ax.text(i, p.snap_pct + ry + 6 / ppy, f"{p.snap_pct:.0%}", ha="center", va="bottom",
                fontsize=F["pct"], color=TEXT, weight="medium", zorder=6)
        # staggered names, two rows, like the reference
        ax.text(i, -(row1 if i % 2 == 0 else row2), p.name, ha="center", va="top",
                fontsize=F["names"], color="#c9ced6", clip_on=False)


def _mix(c, t):
    """Blend a color toward white by t (0..1)."""
    r, g, b = to_rgb(c)
    return (r + (1 - r) * t, g + (1 - g) * t, b + (1 - b) * t)


RB_METRICS = (("SNAP", "snap_pct", 0.0), ("RUSH", "rush_share", 0.30), ("TGT", "tgt_share", 0.55))


def _rb_bars(fig, tw: TeamWeek, colors: dict, L: Layout):
    """One group per running back: snap %, rush share, target share side by side,
    with the back's name and his high-value touches / expected points underneath."""
    F = L.font
    x0, ty, sy = L.snap_xy
    fig.text(x0, ty, "RB Usage", fontsize=F["snap_title"], color=TEXT, weight="medium", va="top")
    fig.text(x0, sy, tw.rb_bar_subtitle, fontsize=F["snap_sub"], color=MUTED, va="top")  # subscript

    backs = [p for p in tw.rbs() if p.snap_pct >= 0.05 or p.carries >= 2][:3]  # three groups stay readable
    bx, by, bwid, bh = L.bars
    lift = 0.07 if L.name == "portrait" else 0.10  # room for headshot, name and stats under the bars
    ax = fig.add_axes((bx, by + lift, bwid, bh - lift))
    n = max(len(backs), 1)
    ax.set_xlim(-0.55, n - 0.45)
    ax.set_ylim(0, 1.12)
    ax.set_axis_off()
    for lvl in (0, 0.25, 0.5, 0.75, 1.0):
        ax.plot([-0.55, n - 0.45], [lvl, lvl], color=GRID, lw=1, zorder=0)
        ax.text(-0.62, lvl, f"{lvl:.0%}", ha="right", va="center", fontsize=F["ytick"], color="#6b7380")

    pt = fig.dpi / 72
    ppy = ax.get_position().height * fig.get_figheight() * fig.dpi / 1.12
    bw = 0.25
    small = F["ytick"]
    diam = L.bar_head * 0.72  # headshot sits under the group, above the name
    for i, p in enumerate(backs):
        base = colors.get(p.name, to_rgb(OTHER_GRAY))
        for j, (lbl, attr, tint) in enumerate(RB_METRICS):
            v = getattr(p, attr) or 0.0
            x = i + (j - 1) * (bw + 0.03)
            ax.add_patch(Rectangle((x - bw / 2, 0), bw, v, fc=_mix(base, tint), ec="none", zorder=2))
            ax.text(x, v + 6 / ppy, f"{v:.0%}", ha="center", va="bottom", fontsize=F["pct"] * 0.82,
                    color=TEXT, weight="medium", zorder=6)
            ax.text(x, -6 / ppy, lbl, ha="center", va="top", fontsize=small * 0.85, color=MUTED, clip_on=False)
        y = -(6 + small * 0.85 * pt * 1.35 + 6) / ppy  # below the SNAP / RUSH / TGT labels
        _circle_image(ax, avatar(p, base), i, y - diam / 2 / ppy, diam, zorder=5)
        y -= (diam + 4) / ppy
        ax.text(i, y, p.name, ha="center", va="top", fontsize=F["names"], color="#dfe3e9",
                weight="medium", clip_on=False)
        y -= F["names"] * pt * 1.3 / ppy
        rolling = hasattr(tw, "weeks")  # window view: expected points per game played, not the total
        xfp = None if p.xfp is None else (p.xfp / max(p.games, 1) if rolling else p.xfp)
        extra = f"{p.carries} car · {p.hvt} HVT" + (f" · {xfp:.1f} xFP{'/g' if rolling else ''}" if xfp is not None else "")
        ax.text(i, y, extra, ha="center", va="top", fontsize=small, color=MUTED, clip_on=False)


def render_team(tw: TeamWeek, out_path: Path, brand: str = "VOLUMETRICS", layout: Layout = LANDSCAPE,
                kind: str = "targets") -> Path:
    """kind="targets": target-share donut + snap % bars. kind="rb": carry-share donut + RB usage groups."""
    if kind == "rb":
        order = [p.name for p in tw.by_carries()]
        order += [p.name for p in tw.rbs() if p.name not in order]
    else:  # one color per player, shared by donut and bars: target order first, then snap-only guys
        order = [p.name for p in tw.by_targets()]
        order += [p.name for p in tw.by_snaps() if p.name not in order]
    pal = team_palette(tw.colors, max(len(order), 1))
    colors = {name: pal[i] for i, name in enumerate(order)}

    fig = plt.figure(figsize=layout.size, dpi=DPI, facecolor=BG)
    logo = _background(fig, tw, layout)
    _header(fig, tw, logo, brand, layout, kind)
    if kind == "rb":
        _donut(fig, tw, colors, layout, metric="carries")
        _rb_bars(fig, tw, colors, layout)
    else:
        _donut(fig, tw, colors, layout)
        _bars(fig, tw, colors, layout)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------- #
# Batch rendering (parallel). Workers are *spawned*, not forked: forking a process that
# has already used polars can deadlock. Workers only draw; all numbers come in ready-made.
# --------------------------------------------------------------------------- #
def _render_card(job) -> str:
    tw, webp_path, layout, brand, *rest = job
    kind = rest[0] if rest else "targets"
    webp_path = Path(webp_path)
    png = webp_path.with_suffix(".png")
    render_team(tw, png, brand=brand, layout=PORTRAIT if layout == "portrait" else LANDSCAPE, kind=kind)
    Image.open(png).convert("RGB").save(webp_path, "WEBP", quality=90, method=6)  # ~3x smaller than PNG
    png.unlink()
    return str(webp_path)


def render_cards(jobs: list, workers: int | None = None) -> list[str]:
    """jobs: [(team_data, out .webp path, "portrait"|"landscape", brand)]"""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    workers = workers or min(len(jobs), os.cpu_count() or 1, 8)
    if workers <= 1:
        return [_render_card(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        return list(ex.map(_render_card, jobs, chunksize=2))
