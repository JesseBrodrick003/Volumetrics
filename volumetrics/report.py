"""
report.py: weekly HTML page. One section per team: chart, the take underneath,
and a collapsible "Why this take" list showing the exact numbers behind it.

embed=True produces one self-contained file (images + fonts inlined) that you can
email, AirDrop, or open offline.
"""

from __future__ import annotations

import base64
import html
import io
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .charts import FONT_DIR

CSS = """
@font-face{font-family:Jost;src:url(%(regular)s) format("truetype");font-weight:400}
@font-face{font-family:Jost;src:url(%(medium)s) format("truetype");font-weight:500}
:root{--bg:#0b0e13;--ink:#eef0f4;--muted:#8b93a1;--line:#1e232c;--banner:#f6c945;--banner-ink:#1a1405}
*{box-sizing:border-box}
:root{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
html{scroll-padding-top:calc(64px + env(safe-area-inset-top,0px))}
body{margin:0;background:var(--bg);color:var(--ink);font:400 17px/1.55 Jost,"Futura","Avenir Next",system-ui,sans-serif;
     -webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:0 auto;padding:0 16px 64px}
.banner{margin:20px 0 6px;background:var(--banner);color:var(--banner-ink);border-radius:8px;
        font-weight:500;font-size:clamp(24px,5vw,38px);line-height:1.15;text-align:center;padding:12px 16px}
.dek{color:var(--muted);text-align:center;margin:0 0 18px;font-size:15px}
nav{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:rgba(11,14,19,.92);backdrop-filter:blur(6px);
    border-bottom:1px solid var(--line);margin:0 -16px;padding:10px 16px;overflow-x:auto;white-space:nowrap}
nav a{display:inline-block;color:var(--muted);text-decoration:none;font-weight:500;font-size:14px;
      padding:4px 8px;border-radius:6px}
nav a:hover,nav a:focus-visible{color:var(--ink);background:#1a1f28;outline:none}
section{padding:28px 0 8px;border-bottom:1px solid var(--line)}
section img{display:block;width:100%%;height:auto;border-radius:10px}
section a.zoom{display:block;border-radius:10px}
section a.zoom:focus-visible{outline:2px solid var(--banner);outline-offset:3px}
.take{margin:16px 2px 0;max-width:68ch;font-size:18px}
details{margin:10px 2px 0;color:var(--muted);font-size:14px}
summary{cursor:pointer;width:max-content}
summary:focus-visible{outline:2px solid var(--banner);outline-offset:3px;border-radius:4px}
details ul{margin:8px 0 0;padding-left:18px}
footer{color:var(--muted);font-size:13px;margin-top:28px;line-height:1.6}
footer a{color:var(--muted)}
"""


def _font_src(name: str, embed: bool, rel_assets: str) -> str:
    f = FONT_DIR / f"Jost-{name}.ttf"
    if embed and f.exists():
        return "data:font/ttf;base64," + base64.b64encode(f.read_bytes()).decode()
    return f"{rel_assets}/fonts/Jost-{name}.ttf"


def _img_src(path: Path, rel: str, embed: bool) -> str:
    if not embed:
        return rel
    im = Image.open(path).convert("RGB")
    im.thumbnail((1440, 810))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def build_page(season: int, week: int, entries: list[dict], out_file: Path, *, embed: bool = False,
               rel_assets: str = "../../assets", missing: list[str] | None = None,
               take_source: str = "template") -> Path:
    """entries: [{team, team_name, img_path, img_rel, take, evidence: [..]}] in display order."""
    css = CSS % {"regular": _font_src("Regular", embed, rel_assets), "medium": _font_src("Medium", embed, rel_assets)}
    nav = "".join(f'<a href="#{e["team"]}">{e["team"]}</a>' for e in entries)
    sections = []
    for e in entries:
        why = "".join(f"<li>{html.escape(x)}</li>" for x in e["evidence"])
        sections.append(
            f'<section id="{e["team"]}" aria-label="{html.escape(e["team_name"])}">'
            + (f'<a class="zoom" href="{e["img_rel"]}" aria-label="Open full-size chart">' if not embed else "")
            + f'<img src="{_img_src(e["img_path"], e["img_rel"], embed)}" '
            f'alt="{html.escape(e["team_name"])} week {week} target share and snap share" loading="lazy">'
            + ("</a>" if not embed else "")
            + f'<p class="take">{html.escape(e["take"])}</p>'
            f"<details><summary>Why this take</summary><ul>{why}</ul></details>"
            f"</section>"
        )
    miss = ""
    if missing:
        miss = (f"<p>Not included yet (snap counts not posted when this ran): {', '.join(missing)}. "
                f"The Wednesday rerun fills them in.</p>")
    stamp = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    raw = "" if embed else ' Raw numbers: <a href="data.csv">data.csv</a> · <a href="takes.json">takes.json</a>'
    voice = "written by Claude from the numbers above" if take_source == "claude" else "rule-based, from the numbers above"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Week {week} Volumetrics · {season}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📊</text></svg>">
<style>{css}</style></head>
<body><div class="wrap">
<h1 class="banner">📊 Week {week} VOLUMETRICS 📊</h1>
<p class="dek">Target share and snap share for every team, {season} season</p>
<nav aria-label="Teams">{nav}</nav>
{''.join(sections)}
<footer>{miss}
<p>Targets, red-zone targets and receiving lines from nflverse play-by-play. Snap counts from Pro Football Reference via nflverse.
Drops from FTN Data via nflverse (CC-BY-SA 4.0). Red zone means inside the opponent's 20. Takes are {voice}.</p>
<p>Generated {stamp}.{raw}</p>
</footer></div></body></html>"""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(page, encoding="utf-8")
    return out_file


def build_index(docs: Path) -> Path:
    """docs/index.html: links to every week that has been generated, newest first."""
    weeks = sorted(docs.glob("*/week-*/index.html"), reverse=True)
    items = "".join(
        f'<li><a href="{w.relative_to(docs).as_posix()}">{w.parent.parent.name} · Week {int(w.parent.name.split("-")[1])}</a></li>'
        for w in weeks
    )
    latest = weeks[0].relative_to(docs).as_posix() if weeks else ""
    css = CSS % {"regular": "assets/fonts/Jost-Regular.ttf", "medium": "assets/fonts/Jost-Medium.ttf"}
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Volumetrics</title>
<style>{css} li{{margin:8px 0}} li a{{color:var(--ink)}}</style></head>
<body><div class="wrap"><h1 class="banner">📊 VOLUMETRICS 📊</h1>
<p class="dek">{'<a style="color:inherit" href="' + latest + '">Open the latest week</a>' if latest else 'No weeks yet'}</p>
<ul>{items}</ul></div></body></html>"""
    out = docs / "index.html"
    out.write_text(page, encoding="utf-8")
    return out
