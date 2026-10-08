"""
report.py: the weekly page. Built phone-first:

  - phones get a tall 1080x1920 card per team (big type, full-bleed), wider screens get
    the 1920x1080 card, via <picture>
  - a sticky row of team chips that highlights the team you're looking at
  - a short "Top target shares" table up top that jumps to each team
  - the take under each card, with a collapsible "Why this take" showing the numbers

embed=True writes one self-contained file (phone cards inlined as JPEG, fonts inlined).
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
@font-face{font-family:Jost;src:url(%(regular)s) format("truetype");font-weight:400;font-display:swap}
@font-face{font-family:Jost;src:url(%(medium)s) format("truetype");font-weight:500;font-display:swap}
@font-face{font-family:Jost;src:url(%(semibold)s) format("truetype");font-weight:600;font-display:swap}
:root,:root[data-theme="dark"],:root[data-theme="light"]{
  --bg:#0f1218;--raise:#161a22;--ink:#eef0f4;--muted:#8f97a4;--faint:#5f6775;--line:#212632;
  --banner:#f6c945;--banner-ink:#1b1505;--team:#8f97a4}
:root{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);
      color-scheme:dark}
*,*::before,*::after{box-sizing:inherit}
html{scroll-padding-top:calc(58px + env(safe-area-inset-top,0px));-webkit-text-size-adjust:100%%}
body{margin:0;background:var(--bg);color:var(--ink);font:400 17px/1.55 Jost,"Avenir Next",Futura,system-ui,sans-serif;
     -webkit-font-smoothing:antialiased}
a{color:inherit}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.wrap{max-width:1000px;margin:0 auto;padding:0 18px 56px}

/* Header */
.top{padding:22px 0 6px}
.banner{margin:0;background:var(--banner);color:var(--banner-ink);border-radius:10px;font-weight:600;
        font-size:clamp(21px,6.2vw,40px);line-height:1.1;letter-spacing:-.01em;text-align:center;padding:14px 10px;white-space:nowrap}
.dek{color:var(--muted);text-align:center;margin:10px 0 0;font-size:15px;text-wrap:balance}

/* Headliners */
.leaders{margin:22px auto 4px;max-width:560px}
.leaders h2{font-size:15px;font-weight:500;color:var(--muted);margin:0 0 6px}
.leaders table{width:100%%;border-collapse:collapse;font-size:16px}
.leaders td{padding:9px 0;border-top:1px solid var(--line)}
.leaders td:first-child a{text-decoration:none;font-weight:500}
.leaders td:first-child a:hover{text-decoration:underline}
.leaders .tm{color:var(--muted);width:4.2em}
.leaders .tm i{display:inline-block;width:8px;height:8px;border-radius:50%%;background:var(--team);margin-right:7px;vertical-align:1px}
.leaders .num{text-align:right;font-variant-numeric:tabular-nums;font-weight:500;width:4em}

/* Sticky bar: view tabs + team chips */
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:color-mix(in srgb,var(--bg) 92%%,transparent);
     backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);margin:16px -18px 0;padding:9px 0 9px 18px;
     border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px}
.tabs{display:none;flex:none;background:var(--raise);border:1px solid var(--line);border-radius:999px;padding:3px}
.js .tabs{display:flex}
.tabs button{font:inherit;font-size:14px;font-weight:500;color:var(--muted);background:none;border:0;border-radius:999px;
             padding:6px 12px;cursor:pointer;white-space:nowrap}
.tabs button[aria-selected="true"]{background:var(--ink);color:var(--bg)}
.tabs button:focus-visible{outline:2px solid var(--banner);outline-offset:2px}
nav{overflow-x:auto;white-space:nowrap;scrollbar-width:none;flex:1;min-width:0;padding-right:18px}
nav::-webkit-scrollbar{display:none}
nav a{display:inline-flex;align-items:center;gap:6px;color:var(--muted);text-decoration:none;font-weight:500;
      font-size:14px;padding:6px 10px;border-radius:999px;border:1px solid var(--line);margin-right:6px}
nav a i{width:7px;height:7px;border-radius:50%%;background:var(--team)}
nav a[aria-current="true"]{color:var(--ink);border-color:var(--team);background:color-mix(in srgb,var(--team) 18%%,transparent)}
nav a:focus-visible{outline:2px solid var(--banner);outline-offset:2px}
.panel-h{font-size:15px;font-weight:500;color:var(--muted);margin:22px 0 0;text-align:center}

/* Week-by-week table under each last-4 card */
.trend{width:100%%;border-collapse:separate;border-spacing:3px;margin:14px 0 0;font-size:14.5px;
       font-variant-numeric:tabular-nums}
.trend th{font-weight:500;color:var(--muted);font-size:12.5px;text-align:center;padding:2px 0}
.trend th[scope="row"]{text-align:left;color:var(--ink);font-size:14.5px;white-space:nowrap;padding-right:6px;
       max-width:8.5em;overflow:hidden;text-overflow:ellipsis}
.trend td{text-align:center;padding:7px 0;border-radius:6px;min-width:2.9em}
.trend td.dnp{color:var(--faint)}
.trend td.tot{font-weight:600;background:var(--raise)}

/* Team sections */
section{padding:26px 0 22px;border-bottom:1px solid var(--line)}
.card{display:block;border-radius:12px;overflow:hidden;background:var(--raise)}
.card img{display:block;width:100%%;height:auto}
.card:focus-visible{outline:2px solid var(--banner);outline-offset:3px}
.take{margin:18px 0 0;padding-left:14px;border-left:3px solid var(--team);max-width:66ch;font-size:18px;line-height:1.6}
details{margin:12px 0 0 17px;color:var(--muted);font-size:14.5px}
summary{cursor:pointer;width:max-content;padding:4px 0;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"+";display:inline-block;width:1em;color:var(--faint)}
details[open] summary::before{content:"\\2212"}
summary:focus-visible{outline:2px solid var(--banner);outline-offset:3px;border-radius:4px}
details ul{margin:6px 0 0;padding-left:18px}
details li{margin:3px 0}

footer{color:var(--faint);font-size:13px;margin-top:28px;line-height:1.6}

/* Phones: cards go edge to edge so the type is as big as possible */
@media (max-width:720px){
  .wrap{padding:0 14px 48px}
  .bar{margin:16px -14px 0;padding:9px 0 9px 14px;gap:8px}
  .tabs button{padding:6px 10px}
  nav{padding-right:14px}
  section{padding:18px 0 20px}
  .card{margin:0 -14px;border-radius:0}
  .take{font-size:17.5px;margin-top:16px}
}
%(embed_css)s
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
"""

JS = """
(()=>{const panels={wk:document.getElementById('p-wk'),l4:document.getElementById('p-l4')};
const tabs=[...document.querySelectorAll('.tabs button')];const nav=document.querySelector('nav');
const chips=[...nav.querySelectorAll('a')];const chip=t=>chips.find(a=>a.dataset.team===t);
const rm=matchMedia('(prefers-reduced-motion:reduce)').matches;let view='wk',cur=null;
const sec=(t,v)=>document.getElementById(v==='l4'?t+'-l4':t);
function mark(t){const a=chip(t);if(!a||a===cur)return;if(cur)cur.removeAttribute('aria-current');
 a.setAttribute('aria-current','true');cur=a;nav.scrollTo({left:a.offsetLeft-nav.offsetLeft-nav.clientWidth/2+a.clientWidth/2,behavior:rm?'auto':'smooth'});}
function show(v,keepTeam){if(!panels[v])return;view=v;for(const k in panels){if(panels[k])panels[k].hidden=k!==v;}
 tabs.forEach(b=>b.setAttribute('aria-selected',b.dataset.view===v?'true':'false'));
 const t=keepTeam&&cur?cur.dataset.team:null;const target=t?sec(t,v):panels[v];
 if(target)target.scrollIntoView({block:'start'});history.replaceState(null,'',v==='l4'?(t?'#'+t+'-l4':'#l4'):(t?'#'+t:'#'));}
tabs.forEach(b=>b.addEventListener('click',()=>show(b.dataset.view,true)));
chips.forEach(a=>a.addEventListener('click',e=>{const s=sec(a.dataset.team,view);if(!s)return;e.preventDefault();
 s.scrollIntoView({behavior:rm?'auto':'smooth',block:'start'});history.replaceState(null,'','#'+s.id);mark(a.dataset.team);}));
const io=new IntersectionObserver(es=>{for(const e of es)if(e.isIntersecting)mark(e.target.dataset.team);},
 {rootMargin:'-35% 0px -60% 0px'});document.querySelectorAll('section[data-team]').forEach(s=>io.observe(s));
const h=location.hash.slice(1);const start=(h==='l4'||h.endsWith('-l4'))&&panels.l4?'l4':'wk';
for(const k in panels){if(panels[k])panels[k].hidden=k!==start;}view=start;
tabs.forEach(b=>b.setAttribute('aria-selected',b.dataset.view===start?'true':'false'));
if(h&&h!=='l4'){const s=document.getElementById(h);if(s)s.scrollIntoView({block:'start'});}})();
"""


def _font_src(name: str, embed: bool, rel_assets: str) -> str:
    f = FONT_DIR / f"Jost-{name}.ttf"
    if embed and f.exists():
        return "data:font/ttf;base64," + base64.b64encode(f.read_bytes()).decode()
    return f"{rel_assets}/fonts/Jost-{name}.ttf"


def _jpeg_data_uri(path: Path, max_w: int = 1080, quality: int = 80) -> str:
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _card(e: dict, week: int, embed: bool) -> str:
    alt = html.escape(f"{e['team_name']} week {week}: target share donut and snap share bars")
    if embed:  # one file to text around: phone card only
        return f'<div class="card"><img src="{_jpeg_data_uri(e["img_path_m"])}" alt="{alt}" loading="lazy" width="1080" height="1920"></div>'
    return (
        f'<a class="card" href="{e["img_png_m"]}" aria-label="Open the full-size {html.escape(e["team_name"])} chart">'
        f"<picture>"
        f'<source media="(max-width: 720px)" srcset="{e["img_rel_m"]}" type="image/webp" width="1080" height="1920">'
        f'<img src="{e["img_rel"]}" alt="{alt}" loading="lazy" decoding="async" width="1920" height="1080">'
        f"</picture></a>"
    )


def _leaders_html(leaders: list[dict], title: str) -> str:
    if not leaders:
        return ""
    rows = "".join(
        f'<tr style="--team:{html.escape(r["color"])}"><td><a href="#{r["anchor"]}">{html.escape(r["label"])}</a></td>'
        f'<td class="tm"><i aria-hidden="true"></i>{r["team"]}</td>'
        f'<td class="num">{r["share"]:.0%}</td></tr>'
        for r in leaders
    )
    return (f'<div class="leaders"><h2>{html.escape(title)}</h2>'
            f'<table><caption class="sr">{html.escape(title)}</caption><tbody>{rows}</tbody></table></div>')


def _trend_html(trend: dict | None) -> str:
    """Week-by-week target share for the top receivers in the window, heat-shaded by share."""
    if not trend or not trend.get("rows"):
        return ""
    head = "".join(f'<th scope="col">Wk {w}</th>' for w in trend["weeks"])
    body = ""
    for r in trend["rows"]:
        cells = ""
        for x in r["shares"]:
            if x is None:
                cells += '<td class="dnp" title="Did not play">\u2013</td>'
            else:
                a = min(60, round(x * 140))  # shade by share, capped so text stays readable
                cells += f'<td style="background:color-mix(in srgb,var(--team) {a}%,transparent)">{x:.0%}</td>'
        body += (f'<tr><th scope="row">{html.escape(r["name"])}</th>{cells}'
                 f'<td class="tot">{r["total"]:.0%}</td></tr>')
    return (f'<table class="trend"><caption class="sr">Target share by week</caption>'
            f'<thead><tr><th scope="col" style="text-align:left">Target share</th>{head}'
            f'<th scope="col">All</th></tr></thead><tbody>{body}</tbody></table>')


def _sections(entries: list[dict], week: int, embed: bool, suffix: str) -> str:
    out = []
    for e in entries:
        sid = e["team"] + suffix
        why = "".join(f"<li>{html.escape(x)}</li>" for x in e["evidence"])
        out.append(
            f'<section id="{sid}" data-team="{e["team"]}" style="--team:{e["color"]}" aria-labelledby="h-{sid}">'
            f'<h2 class="sr" id="h-{sid}">{html.escape(e["team_name"])}</h2>'
            f"{_card(e, week, embed)}"
            f"{_trend_html(e.get('trend'))}"
            f'<p class="take">{html.escape(e["take"])}</p>'
            + (f"<details><summary>Why this take</summary><ul>{why}</ul></details>" if why else "")
            + "</section>"
        )
    return "".join(out)


def build_page(season: int, week: int, panels: list[dict], out_file: Path, *, embed: bool = False,
               rel_assets: str = "../../assets", missing: list[str] | None = None,
               take_source: str = "template") -> Path:
    """
    panels: [{key: "wk"|"l4", label, entries, leaders, leaders_title}] - first one shows by default.
    entries: [{team, team_name, color, img_path, img_rel, img_path_m, img_rel_m, img_png_m, take,
               evidence, trend?}]
    """
    css = CSS % {
        "regular": _font_src("Regular", embed, rel_assets),
        "medium": _font_src("Medium", embed, rel_assets),
        "semibold": _font_src("SemiBold", embed, rel_assets),
        "embed_css": "@media (min-width:721px){.card{max-width:520px;margin:0 auto}}" if embed else "",
    }
    teams = {e["team"]: e for p in panels for e in p["entries"]}
    order = sorted(teams.values(), key=lambda e: e["team_name"])
    nav = "".join(
        f'<a href="#{e["team"]}" data-team="{e["team"]}" style="--team:{e["color"]}"><i aria-hidden="true"></i>{e["team"]}</a>'
        for e in order
    )
    tabs = "".join(
        f'<button type="button" role="tab" data-view="{p["key"]}" aria-controls="p-{p["key"]}" '
        f'aria-selected="{"true" if i == 0 else "false"}">{html.escape(p["label"])}</button>'
        for i, p in enumerate(panels)
    )
    body = ""
    for p in panels:
        suffix = "" if p["key"] == "wk" else f"-{p['key']}"
        body += (f'<div class="panel" id="p-{p["key"]}" role="tabpanel" aria-label="{html.escape(p["label"])}">'
                 f'<h2 class="panel-h">{html.escape(p.get("heading", p["label"]))}</h2>'
                 f'{_leaders_html(p.get("leaders"), p.get("leaders_title", ""))}'
                 f'{_sections(p["entries"], week, embed, suffix)}</div>')

    miss = ""
    if missing:
        miss = (f"<p>Not included yet (snap counts weren't posted when this ran): {', '.join(missing)}. "
                f"The Wednesday run adds them.</p>")
    stamp = datetime.now(timezone.utc).strftime("%b %d, %Y")
    voice = "written by Claude from these numbers" if take_source == "claude" else "rule-based, from these numbers"
    raw = "" if embed else ' Raw numbers: <a href="data.csv">data.csv</a>, <a href="data_l4.csv">data_l4.csv</a>, <a href="takes.json">takes.json</a>.'
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f1218">
<title>Week {week} Volumetrics, {season}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📊</text></svg>">
<script>document.documentElement.classList.add('js')</script>
<style>{css}</style></head>
<body><div class="wrap">
<header class="top">
<h1 class="banner">📊 Week {week} VOLUMETRICS 📊</h1>
<p class="dek">Target share and snap % for every team, {season} season</p>
</header>
<div class="bar"><div class="tabs" role="tablist" aria-label="View">{tabs}</div>
<nav aria-label="Jump to a team">{nav}</nav></div>
<main>{body}</main>
<footer>{miss}
<p>"Last 4 games" adds up each team's four most recent games (bye weeks skipped), so the oldest game drops off
each week. Shares there are totals over those games; a game a player missed counts as zero.</p>
<p>Targets, red-zone targets and receiving lines from nflverse play-by-play. Snap counts from Pro Football Reference
via nflverse. Drops from FTN Data via nflverse (CC-BY-SA 4.0). Red zone means inside the opponent's 20.
Takes are {voice}.</p>
<p>Updated {stamp}.{raw}</p>
</footer></div>
<script>{JS}</script></body></html>"""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(page, encoding="utf-8")
    return out_file


def build_index(docs: Path) -> Path:
    """docs/index.html: newest week up top, earlier weeks below."""
    weeks = sorted(docs.glob("*/week-*/index.html"), reverse=True)

    def label(w: Path) -> str:
        return f"Week {int(w.parent.name.split('-')[1])}, {w.parent.parent.name}"

    items = "".join(f'<li><a href="{w.relative_to(docs).as_posix()}">{label(w)}</a></li>' for w in weeks[1:])
    latest = (f'<a class="go" href="{weeks[0].relative_to(docs).as_posix()}">Open {label(weeks[0])}</a>'
              if weeks else "<p class='dek'>No weeks yet.</p>")
    css = CSS % {"regular": "assets/fonts/Jost-Regular.ttf", "medium": "assets/fonts/Jost-Medium.ttf",
                 "semibold": "assets/fonts/Jost-SemiBold.ttf", "embed_css": ""}
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f1218"><title>Volumetrics</title>
<style>{css}
.go{{display:block;text-align:center;margin:22px 0;padding:14px;border-radius:10px;border:1px solid var(--line);
    text-decoration:none;font-weight:500;font-size:18px}}
.go:focus-visible{{outline:2px solid var(--banner);outline-offset:3px}}
ul.past{{list-style:none;padding:0;margin:0}} ul.past li{{border-top:1px solid var(--line)}}
ul.past a{{display:block;padding:12px 0;text-decoration:none}}</style></head>
<body><div class="wrap"><header class="top"><h1 class="banner">📊 VOLUMETRICS 📊</h1>
<p class="dek">Target share and snap % for every NFL team, every week</p></header>
{latest}
{'<h2 class="dek" style="text-align:left;margin-top:28px">Earlier weeks</h2><ul class="past">' + items + '</ul>' if items else ''}
</div></body></html>"""
    out = docs / "index.html"
    out.write_text(page, encoding="utf-8")
    return out
