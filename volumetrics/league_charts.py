"""
league_charts.py: the four league-wide backfield charts (one image each, phone-sized).

  1. quad_scatter   Efficiency vs. volume: RB carries per game (x) vs. EPA per rush (y)
  2. quad_scatter   Rushing vs. receiving: rush success rate (x) vs. RB target share (y)
  3. split_bars     Blocked vs. created: yards before contact (line) + after contact (back) per carry
  4. share_bars     Who owns the backfield: each back's share of RB carries + targets, 100% stacked,
                    with the goal-line (inside the 5) carries at the right

Team logos are the dots. Quadrant lines sit at the league median so "above the line" means
better than the typical team this span.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

from .charts import BG, DPI, GRID, MUTED, TEXT, _mix, fetch_image, team_palette  # noqa: E402

TEAL, PINK, ORANGE = "#16d6e8", "#ff2b6e", "#ff8a1e"
BRAND_TEXT = "WELL HERE'S A GUY VOLUMETRICS"
_LOGOS: dict[str, np.ndarray | None] = {}


def _logo(team: str, url: str | None, folder: Path | None = None) -> np.ndarray | None:
    if team in _LOGOS:
        return _LOGOS[team]
    img = None
    if folder is not None and (folder / f"{team}.png").exists():
        img = Image.open(folder / f"{team}.png").convert("RGBA")
    if img is None:
        img = fetch_image(url)
    arr = None
    if img is not None:
        img = img.copy()
        img.thumbnail((128, 128))
        arr = np.asarray(img)
    _LOGOS[team] = arr
    return arr


def _place(ax, arr, x, y, size_px, zorder=5):
    """Image centered at data (x, y), size_px tall on screen, aspect kept."""
    fig = ax.figure
    bb = ax.get_position()
    xr, yr = ax.get_xlim(), ax.get_ylim()
    ppx = bb.width * fig.get_figwidth() * fig.dpi / (xr[1] - xr[0])
    ppy = bb.height * fig.get_figheight() * fig.dpi / (yr[1] - yr[0])
    h, w = arr.shape[:2]
    rx, ry = size_px * (w / h) / 2 / ppx, size_px / 2 / ppy
    ax.imshow(arr, extent=(x - rx, x + rx, y - ry, y + ry), zorder=zorder, aspect="auto",
              interpolation="antialiased", clip_on=False)
    ax.set_xlim(xr)
    ax.set_ylim(yr)


def _x_left(ax, px: float) -> float:
    fig = ax.figure
    xr = ax.get_xlim()
    ppx = ax.get_position().width * fig.get_figwidth() * fig.dpi / (xr[1] - xr[0])
    return xr[0] - px / ppx


def _frame(w_in: float, h_in: float, title: str, sub: str):
    fig = plt.figure(figsize=(w_in, h_in), dpi=DPI, facecolor=BG)
    bg = fig.add_axes((0, 0, 1, 1), zorder=-100)
    yy, xx = np.mgrid[0:200, 0:200] / 200
    base = np.array(to_rgb(BG))
    glow = np.exp(-(((xx - 0.15) ** 2) / 0.08 + ((yy - 0.05) ** 2) / 0.05))[..., None]
    glow2 = np.exp(-(((xx - 0.9) ** 2) / 0.06 + ((yy - 0.95) ** 2) / 0.06))[..., None]
    img = base + (np.array(to_rgb(TEAL)) - base) * 0.10 * glow + (np.array(to_rgb(PINK)) - base) * 0.07 * glow2
    bg.imshow(np.clip(img, 0, 1), aspect="auto", extent=(0, 1, 0, 1))
    bg.set_axis_off()
    top = 1 - 0.55 / h_in
    fig.text(0.06, top, title, fontsize=30, color=TEXT, weight="medium", va="top")
    fig.text(0.06, top - 0.62 / h_in, sub, fontsize=17, color=MUTED, va="top")  # subscript
    fig.text(0.06, 0.28 / h_in, BRAND_TEXT, fontsize=14, color=MUTED, weight="medium", va="bottom")
    fig.text(0.94, 0.28 / h_in, "Data: nflverse (pbp, PFR)", fontsize=12, color="#5d6573", ha="right", va="bottom")
    return fig


def quad_scatter(rows: list[dict], x: str, y: str, xlabel: str, ylabel: str, title: str, sub: str,
                 corners: tuple[str, str, str, str], out: Path, logos: dict, logo_dir: Path | None = None,
                 xfmt="{:.0f}", yfmt="{:+.2f}") -> Path:
    """corners: (top-left, top-right, bottom-left, bottom-right) labels."""
    rows = [r for r in rows if r.get(x) is not None and r.get(y) is not None]
    W, H = 9, 10
    fig = _frame(W, H, title, sub)
    ax = fig.add_axes((0.13, 0.11, 0.81, 0.70))
    xs, ys = np.array([r[x] for r in rows]), np.array([r[y] for r in rows])
    padx, pady = (xs.max() - xs.min()) * 0.10 + 1e-6, (ys.max() - ys.min()) * 0.12 + 1e-6
    ax.set_xlim(xs.min() - padx, xs.max() + padx)
    ax.set_ylim(ys.min() - pady, ys.max() + pady)
    ax.set_facecolor("none")
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors="#7c8492", labelsize=13, length=0)
    ax.grid(color=GRID, lw=1)
    ax.set_axisbelow(True)
    mx, my = float(np.median(xs)), float(np.median(ys))
    ax.axvline(mx, color="#4a5262", lw=1.6, ls=(0, (5, 4)), zorder=1)
    ax.axhline(my, color="#4a5262", lw=1.6, ls=(0, (5, 4)), zorder=1)
    # tinted quadrants: top-right teal, bottom-left pink
    xl, yl = ax.get_xlim(), ax.get_ylim()
    ax.add_patch(Rectangle((mx, my), xl[1] - mx, yl[1] - my, fc=TEAL, alpha=0.06, ec="none", zorder=0))
    ax.add_patch(Rectangle((xl[0], yl[0]), mx - xl[0], my - yl[0], fc=PINK, alpha=0.05, ec="none", zorder=0))
    kw = dict(fontsize=15, weight="medium", alpha=0.95, zorder=2)
    ax.text(xl[0] + padx * 0.15, yl[1] - pady * 0.15, corners[0], ha="left", va="top", color="#9fb3c8", **kw)
    ax.text(xl[1] - padx * 0.15, yl[1] - pady * 0.15, corners[1], ha="right", va="top", color=TEAL, **kw)
    ax.text(xl[0] + padx * 0.15, yl[0] + pady * 0.15, corners[2], ha="left", va="bottom", color=PINK, **kw)
    ax.text(xl[1] - padx * 0.15, yl[0] + pady * 0.15, corners[3], ha="right", va="bottom", color="#c9a46b", **kw)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: xfmt.format(v)))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: yfmt.format(v)))
    ax.set_xlabel(xlabel, color=MUTED, fontsize=16, labelpad=10)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=16, labelpad=10)
    for r in rows:
        arr = _logo(r["team"], logos.get(r["team"]), logo_dir)
        if arr is not None:
            ax.scatter([r[x]], [r[y]], s=2600, color="white", alpha=0.07, zorder=4, linewidths=0)
            _place(ax, arr, r[x], r[y], 60)
        else:
            ax.scatter([r[x]], [r[y]], s=500, color=r.get("color", TEAL), zorder=5, edgecolors="white", linewidths=1.5)
            ax.text(r[x], r[y], r["team"], ha="center", va="center", fontsize=9, color="white", weight="bold", zorder=6)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return out


def _row_frame(n: int, title: str, sub: str, legend: list[tuple[str, str]]):
    row_h = 0.52  # inches per team
    H = 2.9 + n * row_h  # title + legend on top, axis numbers + footer below
    W = 9
    fig = _frame(W, H, title, sub)
    lx = 0.06
    ly = 1 - 1.76 / H
    for label, col in legend:
        fig.patches.append(Rectangle((lx, ly - 0.06 / H), 0.025, 0.2 / H, transform=fig.transFigure, fc=col, ec="none"))
        fig.text(lx + 0.035, ly + 0.04 / H, label, fontsize=15, color=TEXT, va="center")
        lx += 0.06 + len(label) * 0.0145
    ax = fig.add_axes((0.15, 1.05 / H, 0.70, (n * row_h) / H))
    ax.set_ylim(n - 0.5, -0.5)
    ax.set_axis_off()
    return fig, ax


def split_bars(rows: list[dict], title: str, sub: str, out: Path, logos: dict, logo_dir: Path | None = None) -> Path:
    rows = sorted([r for r in rows if r.get("ybc_att") is not None], key=lambda r: -(r["ybc_att"] + r["yac_att"]))
    n = len(rows)
    fig, ax = _row_frame(n, title, sub, [("Blocked: yards before contact", TEAL), ("Created: yards after contact", ORANGE)])
    lo = min(0.0, min(r["ybc_att"] for r in rows))
    hi = max(r["ybc_att"] + r["yac_att"] for r in rows)
    ax.set_xlim(lo - 0.1, hi * 1.18)
    for v in range(int(np.floor(lo)), int(np.ceil(hi)) + 1):
        ax.plot([v, v], [-0.5, n - 0.5], color=GRID, lw=1, zorder=0)
        ax.text(v, n - 0.15, f"{v}", ha="center", va="top", fontsize=12, color="#6b7380")
    for i, r in enumerate(rows):
        b, c = r["ybc_att"], r["yac_att"]
        ax.add_patch(Rectangle((min(0, b), i - 0.32), abs(b), 0.64, fc=TEAL, ec="none", zorder=2))
        ax.add_patch(Rectangle((max(0, b), i - 0.32), c, 0.64, fc=ORANGE, ec="none", zorder=2))
        if b >= 0.55:
            ax.text(max(0, b) - 0.06, i, f"{b:.1f}", ha="right", va="center", fontsize=12.5, color="#04161a", weight="medium", zorder=3)
        if c >= 0.55:
            ax.text(max(0, b) + c - 0.06, i, f"{c:.1f}", ha="right", va="center", fontsize=12.5, color="#1f1300", weight="medium", zorder=3)
        ax.text(max(0, b) + c + 0.08, i, f"{b + c:.1f} ypc", ha="left", va="center", fontsize=13, color=TEXT, zorder=3)
        arr = _logo(r["team"], logos.get(r["team"]), logo_dir)
        x_logo = _x_left(ax, 42)
        if arr is not None:
            _place(ax, arr, x_logo, i, 46)
        else:
            ax.text(x_logo, i, r["team"], ha="center", va="center", fontsize=12, color=TEXT)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return out


def share_bars(rows: list[dict], title: str, sub: str, out: Path, logos: dict, colors: dict,
               logo_dir: Path | None = None) -> Path:
    rows = sorted([r for r in rows if r.get("split")], key=lambda r: -r["split"][0]["share"])
    n = len(rows)
    fig, ax = _row_frame(n, title, sub, [("RB1", "#c9ced6"), ("RB2", "#7b8494"), ("RB3+", "#3a3e47")])
    ax.set_xlim(0, 1.16)
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        ax.plot([v, v], [-0.5, n - 0.5], color=GRID if v not in (0.5,) else "#4a5262", lw=1,
                ls="-" if v != 0.5 else (0, (4, 4)), zorder=0)
        ax.text(v, n - 0.15, f"{v:.0%}", ha="center", va="top", fontsize=12, color="#6b7380")
    for i, r in enumerate(rows):
        pal = team_palette(colors.get(r["team"], ["#8b93a1"]), 3)
        segs = r["split"][:2] + ([{"name": "", "share": sum(s["share"] for s in r["split"][2:])}] if len(r["split"]) > 2 else [])
        x = 0.0
        for j, sgm in enumerate(segs):
            col = pal[0] if j == 0 else (_mix(pal[0], 0.45) if j == 1 else to_rgb("#3a3e47"))
            ax.add_patch(Rectangle((x, i - 0.32), sgm["share"], 0.64, fc=col, ec=BG, lw=1.5, zorder=2))
            label = f"{sgm['name']} {sgm['share']:.0%}" if sgm["name"] else ""
            seg_px = sgm["share"] * ax.get_position().width * fig.get_figwidth() * fig.dpi / 1.16
            fits = seg_px > len(label) * 12.5 * DPI / 72 * 0.52 + 16
            if label and fits:
                lum = 0.2126 * col[0] + 0.7152 * col[1] + 0.0722 * col[2]
                ax.text(x + 0.012, i, label, ha="left", va="center", fontsize=12.5,
                        color="#14171d" if lum > 0.55 else TEXT, weight="medium", zorder=3)
            elif sgm["name"] and seg_px > 44:  # no room for the name: just the share
                ax.text(x + 0.012, i, f"{sgm['share']:.0%}", ha="left", va="center", fontsize=12,
                        color="#14171d" if (0.2126 * col[0] + 0.7152 * col[1] + 0.0722 * col[2]) > 0.55 else TEXT, zorder=3)
            x += sgm["share"]
        rb1 = r["split"][0]
        gl = f"GL {rb1['gl']}/{r['gl_total']}" if r.get("gl_total") else "GL \u2013"
        ax.text(1.02, i, gl, ha="left", va="center", fontsize=13,
                color=TEAL if r.get("gl_total") and rb1["gl"] / r["gl_total"] >= 0.67 else MUTED, zorder=3)
        arr = _logo(r["team"], logos.get(r["team"]), logo_dir)
        if arr is not None:
            _place(ax, arr, _x_left(ax, 42), i, 46)
        else:
            ax.text(_x_left(ax, 42), i, r["team"], ha="center", va="center", fontsize=12, color=TEXT)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return out


def render_league(rows: list[dict], span: str, out_dir: Path, logos: dict, colors: dict,
                  logo_dir: Path | None = None) -> list[dict]:
    """Render all four charts for one span ("Week 4" or "Weeks 1-4"). Returns [{key, path, title, how}]."""
    out_dir.mkdir(parents=True, exist_ok=True)
    charts = []
    p = quad_scatter(rows, "rb_carries_pg", "epa_per_rush", "RB carries per game", "EPA per rush",
                     "Efficiency vs. volume", f"RB carries per game vs. EPA per rush · {span}",
                     ("Efficient, underused", "Efficient workhorse", "Struggling", "Volume, inefficient"),
                     out_dir / "quad-volume.png", logos, logo_dir)
    charts.append({"key": "quad-volume", "path": p, "title": "Efficiency vs. volume",
                   "how": "Right = runs the backs more. Up = gains more value per carry (EPA). Top right is the "
                          "dream: lots of carries, used well. Bottom right is forcing the run without results, "
                          "often a line problem. Top left is efficient but underused."})
    p = quad_scatter(rows, "success", "rb_tgt_share", "Rush success rate", "RB share of team targets",
                     "Rushing vs. receiving", f"Rush success rate vs. RB target share · {span}",
                     ("Pass-game backfield", "Does both", "Limited role", "Ground-game backfield"),
                     out_dir / "quad-dual.png", logos, logo_dir, xfmt="{:.0%}", yfmt="{:.0%}")
    charts.append({"key": "quad-dual", "path": p, "title": "Rushing vs. receiving",
                   "how": "Right = more carries that gain positive value. Up = more of the team's targets go to "
                          "the backs. Top right backfields help in both phases, which is where PPR value lives."})
    if any(r.get("ybc_att") is not None for r in rows):
        p = split_bars(rows, "Blocked vs. created yards", f"Per RB carry: before contact + after contact · {span}",
                       out_dir / "split.png", logos, logo_dir)
        charts.append({"key": "split", "path": p, "title": "Blocked vs. created yards",
                       "how": "Teal is yards before contact, mostly the line and scheme. Orange is yards after "
                              "contact, mostly the back. A long teal bar with a short orange one means the line is "
                              "doing the work; the reverse means the backs are carrying a weak line."})
    p = share_bars(rows, "Who owns the backfield", f"Share of RB carries + targets · goal-line carries (RB1) at right · {span}",
                   out_dir / "shares.png", logos, colors, logo_dir)
    charts.append({"key": "shares", "path": p, "title": "Who owns the backfield",
                   "how": "Each bar splits the team's RB carries and targets between its backs. Past the dashed 50% "
                          "line is a lead back; 70%+ is a workhorse. GL shows how many of the team's carries inside "
                          "the 5 went to RB1 (teal when he gets two-thirds or more)."})
    return charts
