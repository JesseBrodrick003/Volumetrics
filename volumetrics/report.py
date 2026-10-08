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
@font-face{font-family:"Big Shoulders";src:url(%(display)s) format("truetype");font-weight:800;font-display:swap}
@font-face{font-family:Oxanium;src:url(%(ox6)s) format("truetype");font-weight:600;font-display:swap}
@font-face{font-family:Oxanium;src:url(%(ox8)s) format("truetype");font-weight:800;font-display:swap}
:root,:root[data-theme="dark"],:root[data-theme="light"]{
  --bg:#0f1218;--raise:#161a22;--ink:#eef0f4;--muted:#8f97a4;--faint:#5f6775;--line:#212632;
  --banner:#f6c945;--banner-ink:#1b1505;--team:#8f97a4}
:root{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);
      color-scheme:dark}
*,*::before,*::after{box-sizing:inherit}
html{scroll-padding-top:calc(128px + env(safe-area-inset-top,0px));-webkit-text-size-adjust:100%%}
body{margin:0;background:var(--bg);color:var(--ink);font:400 17px/1.55 Jost,"Avenir Next",Futura,system-ui,sans-serif;
     -webkit-font-smoothing:antialiased}
a{color:inherit}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.wrap{max-width:1000px;margin:0 auto;padding:0 18px 56px}

/* Hero: futuristic broadcast title. Neon smoke, moving grid floor, the shield behind glowing bars,
   chrome title with a light sweep, HUD corners, scanlines. All decoration is aria-hidden. */
.hero{position:relative;isolation:isolate;overflow:hidden;margin:16px 0 0;border-radius:18px;
      padding:24px 22px 26px;min-height:350px;background:#03050a;border:1px solid rgba(80,230,255,.18);
      box-shadow:0 24px 70px -36px rgba(22,214,232,.55),0 0 90px -50px rgba(255,43,110,.6)}
.hero .fx{position:absolute;pointer-events:none}
.hero .glow{inset:-25%%;z-index:-6;filter:blur(12px) saturate(1.3);
      background:
        radial-gradient(38%% 50%% at 14%% 14%%,rgba(22,224,240,.85),transparent 70%%),
        radial-gradient(32%% 44%% at 92%% 18%%,rgba(98,72,255,.55),transparent 72%%),
        radial-gradient(44%% 54%% at 84%% 98%%,rgba(255,34,112,.85),transparent 70%%),
        radial-gradient(40%% 44%% at 36%% 110%%,rgba(255,140,24,.85),transparent 70%%)}
.hero .smoke{inset:0;z-index:-5;opacity:.7;mix-blend-mode:multiply;
      background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='720' height='360'><filter id='s'><feTurbulence type='fractalNoise' baseFrequency='.0055 .011' numOctaves='5' seed='11'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -1.6 0 0 0 1.05'/></filter><rect width='100%%' height='100%%' filter='url(%%23s)'/></svg>");
      background-size:720px 360px;background-position:center}
.hero .grid{left:-60%%;right:-60%%;bottom:-4%%;height:62%%;z-index:-4;opacity:.55;
      background-image:linear-gradient(rgba(70,232,255,.55) 1px,transparent 1px),linear-gradient(90deg,rgba(70,232,255,.55) 1px,transparent 1px);
      background-size:44px 44px;transform:perspective(220px) rotateX(64deg);transform-origin:50%% 100%%;
      -webkit-mask-image:linear-gradient(to top,#000 15%%,transparent 92%%);mask-image:linear-gradient(to top,#000 15%%,transparent 92%%);
      animation:vgrid 5s linear infinite}
@keyframes vgrid{to{background-position:0 44px,0 0}}
.hero .emblem{position:absolute;right:-5%%;bottom:0;width:66%%;height:58%%;z-index:-3;pointer-events:none}
.hero .emblem>*{position:absolute;left:54%%;top:50%%;translate:-50%% -50%%}
.hero .halo{height:122%%;aspect-ratio:1;border-radius:50%%;
      background:conic-gradient(from 0deg,transparent 0 8%%,rgba(22,224,240,.9) 14%%,transparent 26%%,rgba(255,43,110,.85) 46%%,
        transparent 58%%,rgba(255,140,24,.8) 74%%,transparent 86%%);
      -webkit-mask:radial-gradient(circle,transparent 60%%,#000 61.5%%,#000 64%%,transparent 65.5%%);
      mask:radial-gradient(circle,transparent 60%%,#000 61.5%%,#000 64%%,transparent 65.5%%);
      animation:spin 12s linear infinite;filter:drop-shadow(0 0 8px rgba(22,224,240,.8))}
.hero .halo.two{height:96%%;animation-duration:18s;animation-direction:reverse;opacity:.7}
@keyframes spin{to{rotate:360deg}}
.hero .core{height:112%%;aspect-ratio:1;border-radius:50%%;
      background:radial-gradient(circle,rgba(22,214,232,.35),rgba(255,43,110,.18) 45%%,transparent 70%%);filter:blur(6px)}
.hero .shield{height:80%%;opacity:.85;
      filter:drop-shadow(0 0 14px rgba(22,224,240,.75)) drop-shadow(0 0 36px rgba(255,43,110,.45)) saturate(1.15) brightness(1.05)}
.hero .emblem>.bars{left:0;top:auto;bottom:0;translate:none;height:82%%;width:100%%;mix-blend-mode:screen}
.hero .bars rect.b{transform-box:fill-box;transform-origin:50%% 100%%;animation:rise 1.2s cubic-bezier(.2,.85,.2,1) both;
      animation-delay:var(--d)}
@keyframes rise{from{transform:scaleY(.04);opacity:.1}to{transform:none;opacity:1}}
.hero .scan{inset:0;z-index:-1;opacity:.5;mix-blend-mode:overlay;
      background:repeating-linear-gradient(0deg,rgba(255,255,255,.07) 0 1px,transparent 1px 3px)}
.hero .grain{inset:0;z-index:-1;opacity:.14;mix-blend-mode:overlay;
      background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='g'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%%' height='100%%' filter='url(%%23g)'/></svg>")}
.hero .hud{position:absolute;width:18px;height:18px;border-color:rgba(110,240,255,.85);border-style:solid;border-width:0;
      filter:drop-shadow(0 0 4px rgba(22,224,240,.9))}
.hud.tl{top:10px;left:10px;border-top-width:2px;border-left-width:2px}
.hud.tr{top:10px;right:10px;border-top-width:2px;border-right-width:2px}
.hud.bl{bottom:10px;left:10px;border-bottom-width:2px;border-left-width:2px}
.hud.br{bottom:10px;right:10px;border-bottom-width:2px;border-right-width:2px}
.hero-in{position:relative}
.chip{display:inline-flex;align-items:center;gap:9px;margin:0;padding:7px 12px 6px;border-radius:999px;
      font:600 11.5px/1 Oxanium,Jost,sans-serif;letter-spacing:.2em;text-transform:uppercase;color:#c9f8ff;
      border:1px solid rgba(80,230,255,.4);background:rgba(4,18,28,.55);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
.chip b{color:#ff7aa8;font-weight:600}
.pulse{width:8px;height:8px;border-radius:50%%;background:#3fe3f0;box-shadow:0 0 0 0 rgba(63,227,240,.8);animation:pulse 1.8s ease-out infinite}
@keyframes pulse{70%%{box-shadow:0 0 0 9px rgba(63,227,240,0)}100%%{box-shadow:0 0 0 0 rgba(63,227,240,0)}}
.hero h1{margin:18px 0 0;font-weight:400}
.brand{display:block;font:600 clamp(13px,3.7vw,22px)/1.1 Oxanium,Jost,sans-serif;letter-spacing:.32em;text-transform:uppercase;
      background:linear-gradient(90deg,#8ff6ff,#ffffff 45%%,#ff9fc4);-webkit-background-clip:text;background-clip:text;color:transparent;
      filter:drop-shadow(0 0 8px rgba(22,224,240,.5))}
.title{position:relative;display:block;margin-top:6px;font:800 clamp(42px,12.2vw,110px)/.98 Oxanium,"Big Shoulders",sans-serif;
      letter-spacing:.005em;text-transform:uppercase;
      background:linear-gradient(105deg,transparent 40%%,rgba(255,255,255,.95) 50%%,transparent 60%%),
                 linear-gradient(180deg,#ffffff 0%%,#ecfcff 32%%,#8beeff 50%%,#ffffff 60%%,#ffcfe1 100%%);
      background-size:280%% 100%%,100%% 100%%;background-position:130%% 0,0 0;background-repeat:no-repeat;
      -webkit-background-clip:text;background-clip:text;color:transparent;
      filter:drop-shadow(0 0 10px rgba(22,224,240,.65)) drop-shadow(0 0 30px rgba(255,43,110,.4));
      animation:sweep 6s ease-in-out 1.4s infinite}
@keyframes sweep{0%%,62%%{background-position:130%% 0,0 0}100%%{background-position:-60%% 0,0 0}}
.title::before,.title::after{content:attr(data-text);position:absolute;inset:0;z-index:-1;-webkit-background-clip:initial;
      background:none;opacity:.55;mix-blend-mode:screen}
.title::before{color:#00f0ff;transform:translate(-2px,0)}
.title::after{color:#ff2b6e;transform:translate(2px,1px)}
.tagline{margin:12px 0 0;color:rgba(235,246,255,.88);font-size:15.5px;max-width:20ch;text-shadow:0 1px 10px rgba(0,0,0,.8)}
@media (min-width:721px){.hero{min-height:330px;padding:36px 36px 32px}.tagline{font-size:17px;max-width:34ch}
  .hero .emblem{right:1%%;width:34%%;height:100%%}.title{font-size:clamp(42px,8.4vw,88px)}}
@media (prefers-reduced-motion:reduce){.hero *{animation:none!important}}
.dek{color:var(--muted);font-size:15px}

/* Headliners */
.leaders{margin:22px auto 4px;max-width:560px}
.leaders h2{font-size:15px;font-weight:500;color:var(--muted);margin:0 0 6px}
.leaders table{width:100%%;border-collapse:collapse;font-size:16px}
.leaders td{padding:9px 0;border-top:1px solid var(--line)}
.leaders td:first-child a{text-decoration:none;font-weight:500}
.leaders td:first-child a:hover{text-decoration:underline}
.leaders .tm{color:var(--muted);width:4.2em}
.leaders .tm i{display:inline-block;width:8px;height:8px;border-radius:50%%;background:var(--team);margin-right:7px;vertical-align:1px}
.leaders .tm img{width:20px;height:20px;object-fit:contain;vertical-align:-5px;margin-right:7px}
.leaders .num{text-align:right;font-variant-numeric:tabular-nums;font-weight:500;width:4em}

/* Sticky bar: view tabs + team chips */
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:color-mix(in srgb,var(--bg) 92%%,transparent);
     backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);margin:16px -18px 0;padding:8px 18px 8px;
     border-bottom:1px solid var(--line)}
.tabs{display:none;background:var(--raise);border:1px solid var(--line);border-radius:12px;padding:3px;
      grid-template-columns:repeat(var(--n,4),1fr);gap:2px}
.js .tabs{display:grid}
.tabs button{font:inherit;font-size:14.5px;font-weight:500;color:var(--muted);background:none;border:0;border-radius:9px;
             padding:8px 6px;cursor:pointer;white-space:nowrap}
.tabs button[aria-selected="true"]{background:var(--ink);color:var(--bg)}
.tabs button:focus-visible{outline:2px solid var(--banner);outline-offset:2px}
nav{overflow-x:auto;white-space:nowrap;scrollbar-width:none;margin:8px -18px 0;padding:0 18px}
nav[hidden]{display:none}
nav::-webkit-scrollbar{display:none}
nav a{display:inline-flex;align-items:center;justify-content:center;color:var(--muted);text-decoration:none;
      font-weight:500;font-size:14px;height:38px;min-width:46px;padding:0 10px;border-radius:999px;
      border:1px solid var(--line);margin-right:6px;vertical-align:middle;background:rgba(255,255,255,.02)}
nav a img{width:26px;height:26px;object-fit:contain;display:block;filter:drop-shadow(0 1px 2px rgba(0,0,0,.5))}
nav a i{width:7px;height:7px;border-radius:50%%;background:var(--team);margin-right:6px}
nav a[aria-current="true"]{color:var(--ink);border-color:var(--team);background:color-mix(in srgb,var(--team) 22%%,transparent);
      box-shadow:0 0 14px color-mix(in srgb,var(--team) 45%%,transparent)}
nav a:focus-visible{outline:2px solid var(--banner);outline-offset:2px}
.panel-h{font-size:15px;font-weight:500;color:var(--muted);margin:22px 0 0;text-align:center}

/* Tabs with two-line labels */
.tabs button{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;line-height:1.15;padding:7px 4px}
.tabs .t1{font-size:11.5px;color:var(--faint);font-weight:500;letter-spacing:.02em}
.tabs .t2{font-size:14.5px;font-weight:600;white-space:normal;text-align:center}
.tabs button[aria-selected="true"] .t1{color:color-mix(in srgb,var(--bg) 60%%,var(--ink))}
@media (max-width:720px){.tabs .t2{font-size:13.5px}.tab-mv .t1{display:none}}
.row2{display:flex;align-items:center;gap:8px;margin-top:8px}
.row2 nav{margin:0 -18px 0 0;padding:0 18px 0 0;flex:1;min-width:0}
.subsw{display:inline-grid;grid-template-columns:1fr 1fr;flex:none;background:var(--raise);border:1px solid var(--line);
       border-radius:10px;padding:3px;gap:2px}
.subsw[hidden]{display:none}
.subsw button{font:inherit;font-size:13.5px;font-weight:500;color:var(--muted);background:none;border:0;border-radius:8px;
       padding:7px 10px;cursor:pointer}
.subsw button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
.subsw button:focus-visible,.chart-tabs button:focus-visible{outline:2px solid var(--banner);outline-offset:2px}
.sub[hidden]{display:none}
.sec-h{font:800 22px/1 "Big Shoulders",Impact,sans-serif;letter-spacing:.05em;text-transform:uppercase;margin:26px 0 10px;color:var(--ink)}

/* Top 8 + league charts + O-line notes */
.top8{margin-top:16px}
.tbl-fit{max-height:none}
.tbl-fit .lbt{font-size:13.5px}
.tbl-fit .lbt th,.tbl-fit .lbt td{padding:9px 5px}
.tbl-fit .lbt th.pl,.tbl-fit .lbt td.pl{padding-left:10px}
.tbl-fit .pl{min-width:7.6em}
.tbl-fit .pl img{width:18px;height:18px}
.chart-tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:4px;background:var(--raise);border:1px solid var(--line);
       border-radius:12px;padding:3px;margin-bottom:10px}
.chart-tabs button{font:inherit;font-size:13.5px;font-weight:500;color:var(--muted);background:none;border:0;border-radius:9px;
       padding:8px 4px;cursor:pointer}
.chart-tabs button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
figure.lg{margin:0}
figure.lg[hidden]{display:none}
figure.lg img{display:block;width:100%%;height:auto;border-radius:12px}
figure.lg figcaption{color:var(--muted);font-size:14.5px;line-height:1.55;margin:10px 2px 0;max-width:66ch}
figure.lg figcaption b{color:var(--ink);font-weight:600}
@media (min-width:721px){figure.lg img{max-width:640px;margin:0 auto}}
@media (max-width:720px){figure.lg img{border-radius:0;margin:0 -14px;width:calc(100%% + 28px);max-width:none}}
.oline{margin-top:28px;padding-top:4px;border-top:1px solid var(--line)}
.ol-list{list-style:none;margin:10px 0 0;padding:0}
.ol-list li{display:grid;grid-template-columns:4.6em 1fr;gap:10px;padding:10px 0;border-bottom:1px solid var(--line);font-size:15px;line-height:1.5}
.ol-team{display:flex;align-items:center;gap:7px;font-weight:600}
.ol-team img{width:22px;height:22px;object-fit:contain}
.ol-notes{color:var(--ink)}

/* RB leaderboard */
.lb{margin:20px 0 6px}
.seg{display:inline-grid;grid-template-columns:1fr 1fr;background:var(--raise);border:1px solid var(--line);border-radius:10px;padding:3px;gap:2px}
.seg button{font:inherit;font-size:14px;font-weight:500;color:var(--muted);background:none;border:0;border-radius:8px;padding:6px 14px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
.seg button:focus-visible{outline:2px solid var(--banner);outline-offset:2px}
.lb-top{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
.lb-top h3{margin:0;font-size:15px;font-weight:500;color:var(--muted)}
.tbl{margin-top:10px;overflow-x:auto;border:1px solid var(--line);border-radius:12px;max-height:70vh;overflow-y:auto;
     -webkit-overflow-scrolling:touch}
.tbl[hidden]{display:none}
table.lbt{border-collapse:separate;border-spacing:0;width:100%%;font-size:14px;font-variant-numeric:tabular-nums}
.lbt th,.lbt td{padding:9px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
.lbt thead th{position:sticky;top:0;background:var(--raise);z-index:2;font-weight:500;color:var(--muted);font-size:12.5px}
.lbt thead th button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}
.lbt thead th[aria-sort] button{color:var(--ink)}
.lbt thead th[aria-sort="descending"] button::after{content:" ↓"}
.lbt thead th[aria-sort="ascending"] button::after{content:" ↑"}
.lbt .pl{text-align:left;position:sticky;left:0;background:var(--bg);z-index:1;min-width:9.5em}
.lbt thead .pl{z-index:3;background:var(--raise)}
.lbt .pl a{text-decoration:none;display:flex;align-items:center;gap:8px;font-weight:500;color:var(--ink)}
.lbt .pl img{width:20px;height:20px;object-fit:contain;flex:none}
.lbt td.hi{color:var(--ink);font-weight:600}
.lbt tbody tr:hover td,.lbt tbody tr:hover .pl{background:var(--raise)}
.lb-note{color:var(--faint);font-size:13px;margin:8px 2px 0;line-height:1.5}

/* Movers */
.mv-intro{color:var(--muted);font-size:15px;margin:10px 0 0;max-width:62ch}
.filters{display:flex;gap:6px;margin:14px 0 4px;flex-wrap:wrap}
.filters button{font:inherit;font-size:14px;font-weight:500;color:var(--muted);background:none;border:1px solid var(--line);
     border-radius:999px;padding:6px 14px;cursor:pointer}
.filters button[aria-pressed="true"]{color:var(--bg);background:var(--ink);border-color:var(--ink)}
.filters button:focus-visible{outline:2px solid var(--banner);outline-offset:2px}
.mv-h{display:flex;align-items:center;gap:8px;font:800 24px/1 "Big Shoulders",Impact,sans-serif;letter-spacing:.04em;
      text-transform:uppercase;margin:22px 0 6px}
.mv-h.up{color:#3fe3f0}.mv-h.down{color:#ff4d86}
ol.movers{list-style:none;margin:0;padding:0}
.movers>li{position:relative;display:grid;grid-template-columns:56px 1fr;gap:12px;align-items:start;padding:14px 0;border-bottom:1px solid var(--line)}
.movers>li .spark{position:absolute;right:0;top:14px}
.movers .mv-top,.movers .mv-sub,.movers .mv-stat,.movers .mv-meta{margin-right:92px}
.movers>li[hidden]{display:none}
.movers .av{width:56px;height:56px;border-radius:50%%;display:block;box-shadow:0 0 0 2px var(--team)}
.mv-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.mv-name{font-weight:600;font-size:17px}
.mv-tag{font-size:12px;font-weight:600;letter-spacing:.02em;padding:2px 8px;border-radius:999px;white-space:nowrap}
.tag-waiver{background:#16d6e8;color:#04161a}.tag-buy{background:#3ddc97;color:#04170e}
.tag-buylow{background:#ffb02e;color:#1f1300}.tag-sell{background:#ff4d86;color:#22030d}.tag-watch{background:#2a3040;color:var(--ink)}
.mv-sub{color:var(--muted);font-size:13.5px;display:flex;align-items:center;gap:6px;margin-top:1px}
.mv-sub img{width:18px;height:18px;object-fit:contain}
.mv-stat{font-size:15px;margin-top:4px}
.mv-d{font-weight:600;margin-left:4px}.mv-d.up{color:#3fe3f0}.mv-d.down{color:#ff4d86}
.mv-meta{color:var(--muted);font-size:13px;margin-top:2px}
.spark{width:84px;height:40px;display:block}
.ev{margin-top:8px}
.ev-grade{display:inline-block;font:600 11.5px/1 Oxanium,Jost,sans-serif;letter-spacing:.12em;text-transform:uppercase;
      padding:5px 9px 4px;border-radius:6px;border:1px solid currentColor}
.ev-strong .ev-grade{color:#3fe3f0;background:rgba(63,227,240,.08)}
.ev-solid .ev-grade{color:#ffb02e;background:rgba(255,176,46,.08)}
.ev-thin .ev-grade{color:#8f97a4}
ul.chips{list-style:none;margin:7px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:5px}
ul.chips li{font-size:12.5px;line-height:1.3;padding:4px 8px;border-radius:7px;background:#161b25;border:1px solid #232937;color:var(--ink)}
ul.chips li span{color:var(--muted)}
ul.chips li.pro b{color:#3fe3f0}
.movers>li[data-dir="down"] ul.chips li.pro b{color:#ff4d86}
ul.chips li.con{background:transparent;border-style:dashed;color:var(--muted)}
ul.chips li.con b{color:#ffb02e}
.ev-info{margin:6px 0 0;color:var(--faint);font-size:12.5px}
.mv-empty{color:var(--muted);font-size:15px;padding:10px 0}

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
@media (min-width:721px){.hero{min-height:250px;padding:38px 34px 32px}.tagline{font-size:17px}}
@media (max-width:720px){
  .wrap{padding:0 14px 48px}
  .hero{margin:0 -14px;border-radius:0;padding:28px 18px 24px}
  .bar{margin:16px -14px 0;padding:8px 14px}
  nav{margin:8px -14px 0;padding:0 14px}
  section{padding:18px 0 20px}
  .card{margin:0 -14px;border-radius:0}
  .take{font-size:17.5px;margin-top:16px}
}
%(embed_css)s
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
"""

JS = """
(()=>{const panels={};document.querySelectorAll('.panel').forEach(p=>panels[p.id.slice(2)]=p);
const tabs=[...document.querySelectorAll('.tabs button')];const nav=document.querySelector('nav');
const subsw=document.querySelector('.subsw');const subBtns=subsw?[...subsw.querySelectorAll('button')]:[];
const chips=[...nav.querySelectorAll('a')];const chip=t=>chips.find(a=>a.dataset.team===t);
const rm=matchMedia('(prefers-reduced-motion:reduce)').matches;let view='wk',sub='tgt',cur=null;
const suffix=()=>view==='wk'?'':view==='rb'?'-rb':view==='tr'?(sub==='bf'?'-l4rb':'-l4'):null;
const sec=t=>{const s=suffix();return s===null?null:document.getElementById(t+s);};
function mark(t){const a=chip(t);if(!a||a===cur)return;if(cur)cur.removeAttribute('aria-current');
 a.setAttribute('aria-current','true');cur=a;nav.scrollTo({left:a.offsetLeft-nav.offsetLeft-nav.clientWidth/2+a.clientWidth/2,behavior:rm?'auto':'smooth'});}
function setSub(sv){sub=sv;subBtns.forEach(b=>b.setAttribute('aria-pressed',b.dataset.sub===sv?'true':'false'));
 if(panels.tr)panels.tr.querySelectorAll(':scope > .sub').forEach(d=>d.hidden=d.dataset.sub!==sv);}
function apply(v){view=v;for(const k in panels)panels[k].hidden=k!==v;
 tabs.forEach(b=>b.setAttribute('aria-selected',b.dataset.view===v?'true':'false'));
 nav.hidden=(v==='mv');if(subsw)subsw.hidden=(v!=='tr');}
function go(keepTeam){const t=keepTeam&&cur?cur.dataset.team:null;const target=(t&&sec(t))||panels[view];
 target.scrollIntoView({block:'start'});const tag=view==='tr'&&sub==='bf'?'tr-bf':view;
 history.replaceState(null,'',t&&sec(t)?'#'+sec(t).id:(view==='wk'?'#':'#'+tag));}
tabs.forEach(b=>b.addEventListener('click',()=>{apply(b.dataset.view);go(true);}));
subBtns.forEach(b=>b.addEventListener('click',()=>{setSub(b.dataset.sub);go(true);}));
chips.forEach(a=>a.addEventListener('click',e=>{const s=sec(a.dataset.team);if(!s)return;e.preventDefault();
 s.scrollIntoView({behavior:rm?'auto':'smooth',block:'start'});history.replaceState(null,'','#'+s.id);mark(a.dataset.team);}));
const io=new IntersectionObserver(es=>{for(const e of es)if(e.isIntersecting)mark(e.target.dataset.team);},
 {rootMargin:'-35% 0px -60% 0px'});document.querySelectorAll('section[data-team]').forEach(s=>io.observe(s));
document.querySelectorAll('main a[href^="#"]').forEach(a=>a.addEventListener('click',()=>{const el=document.getElementById(a.hash.slice(1));
 if(!el)return;const p=el.closest('.panel');if(p&&p.hidden)apply(p.id.slice(2));const sd=el.closest('.sub');if(sd&&sd.hidden)setSub(sd.dataset.sub);}));
/* sortable tables */
document.querySelectorAll('table.sortable').forEach(tb=>{const ths=[...tb.tHead.rows[0].cells];
 ths.forEach((th,i)=>{const b=th.querySelector('button');if(!b)return;b.addEventListener('click',()=>{
  const dir=th.getAttribute('aria-sort')==='descending'?'ascending':'descending';ths.forEach(x=>x.removeAttribute('aria-sort'));
  th.setAttribute('aria-sort',dir);const rows=[...tb.tBodies[0].rows];const val=r=>{const v=parseFloat(r.cells[i].dataset.v);return isNaN(v)?-1e9:v;};
  rows.sort((x,y)=>dir==='descending'?val(y)-val(x):val(x)-val(y));rows.forEach(r=>tb.tBodies[0].appendChild(r));});});});
/* league chart switcher */
document.querySelectorAll('.chart-tabs').forEach(g=>{const bs=[...g.querySelectorAll('button')];bs.forEach(b=>b.addEventListener('click',()=>{
 bs.forEach(x=>{x.setAttribute('aria-pressed',x===b?'true':'false');const f=document.getElementById(x.dataset.chart);if(f)f.hidden=x!==b;});}));});
/* movers position filter */
document.querySelectorAll('.filters').forEach(g=>{const bs=[...g.querySelectorAll('button')];const root=g.closest('.panel');
 const run=pos=>{root.querySelectorAll('ol.movers').forEach(ol=>{let shown=0;ol.querySelectorAll(':scope > li').forEach(li=>{
  const ok=pos==='all'?li.dataset.all==='1':(li.dataset.pos===pos&&+li.dataset.pr<=8);li.hidden=!ok;if(ok)shown++;});
  const em=ol.nextElementSibling;if(em&&em.classList.contains('mv-empty'))em.hidden=shown>0;});};
 bs.forEach(b=>b.addEventListener('click',()=>{bs.forEach(x=>x.setAttribute('aria-pressed',x===b?'true':'false'));run(b.dataset.pos);}));run('all');});
/* start view from the link: #rb #tr #tr-bf #mv, a team (#CAR, #CAR-rb, #CAR-l4, #CAR-l4rb); old #l4 links -> trends */
const h=location.hash.slice(1);let v='wk',sv='tgt';
if(h==='l4'||h==='tr')v='tr';else if(h==='tr-bf'){v='tr';sv='bf';}else if(panels[h])v=h;
else if(/-l4rb$/.test(h)){v='tr';sv='bf';}else if(/-l4$/.test(h))v='tr';else if(/-rb$/.test(h))v='rb';
if(!panels[v])v='wk';setSub(sv);apply(v);
if(h&&!panels[h]&&!['l4','tr','tr-bf'].includes(h)){const s=document.getElementById(h);if(s)s.scrollIntoView({block:'start'});}})();
"""


def _font_src(name: str, embed: bool, rel_assets: str, full: bool = False) -> str:
    fname = f"{name}.ttf" if full else f"Jost-{name}.ttf"
    f = FONT_DIR / fname
    if embed and f.exists():
        return "data:font/ttf;base64," + base64.b64encode(f.read_bytes()).decode()
    return f"{rel_assets}/fonts/{fname}"


BARS_SVG = (  # glass bars with bright caps, rising on load, in front of the shield
    '<svg class="bars" viewBox="0 0 120 100" preserveAspectRatio="xMaxYMax meet" aria-hidden="true">'
    '<defs><linearGradient id="hbc" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#bafcff" stop-opacity=".95"/>'
    '<stop offset=".55" stop-color="#16d6e8" stop-opacity=".45"/><stop offset="1" stop-color="#16d6e8" stop-opacity="0"/></linearGradient>'
    '<linearGradient id="hbp" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd0e2" stop-opacity=".95"/>'
    '<stop offset=".55" stop-color="#ff2b6e" stop-opacity=".5"/><stop offset="1" stop-color="#ff2b6e" stop-opacity="0"/></linearGradient></defs>'
    + "".join(
        f'<rect class="b" style="--d:{0.15 + i * 0.09:.2f}s" x="{6 + i * 18.5}" y="{100 - h}" width="11" height="{h}" rx="1.2" '
        f'fill="url(#{"hbp" if i == 5 else "hbc"})"/>'
        f'<rect class="b" style="--d:{0.15 + i * 0.09:.2f}s" x="{6 + i * 18.5}" y="{100 - h}" width="11" height="1.8" rx=".9" '
        f'fill="#ffffff" opacity=".95"/>'
        for i, h in enumerate((30, 48, 40, 64, 56, 88)))
    + "</svg>"
)

BRAND = "Well Here\u2019s A Guy"


def hero(week_label: str, season_label: str, tagline: str, shield_src: str | None = None) -> str:
    shield = f'<img class="shield" src="{shield_src}" alt="">' if shield_src else ""
    return (
        '<header class="hero">'
        '<div class="fx glow" aria-hidden="true"></div><div class="fx smoke" aria-hidden="true"></div>'
        '<div class="fx grid" aria-hidden="true"></div>'
        f'<div class="emblem" aria-hidden="true"><div class="core"></div><div class="halo"></div>'
        f'<div class="halo two"></div>{shield}{BARS_SVG}</div>'
        '<div class="fx scan" aria-hidden="true"></div><div class="fx grain" aria-hidden="true"></div>'
        '<span class="hud tl" aria-hidden="true"></span><span class="hud tr" aria-hidden="true"></span>'
        '<span class="hud bl" aria-hidden="true"></span><span class="hud br" aria-hidden="true"></span>'
        '<div class="hero-in">'
        f'<p class="chip"><i class="pulse" aria-hidden="true"></i>{html.escape(week_label.upper())} <b>/</b> '
        f'{html.escape(season_label.upper())}</p>'
        f'<h1><span class="brand">{html.escape(BRAND)}</span>'
        f'<span class="title" data-text="Volumetrics">Volumetrics</span></h1>'
        f'<p class="tagline">{html.escape(tagline)}</p>'
        "</div></header>"
    )


def _head_app(root: str) -> str:
    """Home-screen app bits: manifest, icons, iOS full-screen."""
    return (f'<link rel="manifest" href="{root}/manifest.webmanifest">'
            f'<link rel="apple-touch-icon" href="{root}/assets/brand/icon-180.png">'
            '<meta name="apple-mobile-web-app-capable" content="yes">'
            '<meta name="mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
            '<meta name="apple-mobile-web-app-title" content="Volumetrics">')


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


def _logo_img(team: str, logos: dict, size: int) -> str:
    src = (logos or {}).get(team)
    return f'<img src="{src}" alt="" width="{size}" height="{size}" loading="lazy" decoding="async">' if src else ""


def _leaders_html(leaders: list[dict], title: str, logos: dict | None = None) -> str:
    if not leaders:
        return ""
    rows = "".join(
        f'<tr style="--team:{html.escape(r["color"])}"><td><a href="#{r["anchor"]}">{html.escape(r["label"])}</a></td>'
        f'<td class="tm">{_logo_img(r["team"], logos, 20) or "<i aria-hidden=true></i>"}{r["team"]}</td>'
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
            f'<thead><tr><th scope="col" style="text-align:left">{html.escape(trend.get("label", "Target share"))}</th>{head}'
            f'<th scope="col">All</th></tr></thead><tbody>{body}</tbody></table>')



LB_COLS = (  # (header, key, kind, tooltip)
    ("Snap %", "snap", "pct", "Share of the team's offensive snaps"),
    ("Rush %", "rush", "pct", "Share of the team's carries (designed runs)"),
    ("Tgt %", "tgt_share", "pct", "Share of the team's targets"),
    ("Opp %", "opp", "pct", "Backfield share: his carries + targets / all RB carries + targets"),
    ("Car", "car", "int", "Carries"),
    ("Tgts", "tgt", "int", "Targets"),
    ("HVT", "hvt", "int", "High-value touches: catches + carries inside the 10"),
    ("GL", "gl", "int", "Carries inside the 5"),
    ("xFP", "xfp", "dec", "Expected PPR points from his usage (nflverse model)"),
    ("PPR", "fp", "dec", "Actual PPR points"),
)


def _lb_table(rows: list[dict], logos: dict, per_game: bool, limit: int = 40) -> str:
    rows = sorted(rows, key=lambda r: -(r["xfp"] if r["xfp"] is not None else -1))[:limit]
    head = '<th scope="col" class="pl">RB</th>'
    for h, k, kind, tip in LB_COLS:
        label = h + ("/g" if per_game and k in ("xfp", "fp") else "")
        sort = ' aria-sort="descending"' if k == "xfp" else ""
        head += f'<th scope="col"{sort} title="{html.escape(tip)}"><button type="button">{label}</button></th>'
    if per_game:
        head += '<th scope="col" title="Games played"><button type="button">G</button></th>'
    body = ""
    for r in rows:
        cells = ""
        for _, k, kind, _ in LB_COLS:
            v = r.get(k)
            if v is None:
                cells += '<td data-v="">\u2013</td>'
                continue
            txt = f"{v:.0%}" if kind == "pct" else (f"{v:.1f}" if kind == "dec" else f"{v}")
            hi = ' class="hi"' if k == "xfp" else ""
            cells += f'<td data-v="{v}"{hi}>{txt}</td>'
        if per_game:
            cells += f'<td data-v="{r.get("games") or 0}">{r.get("games") or 0}</td>'
        body += (f'<tr><th scope="row" class="pl"><a href="#{r["team"]}-rb" title="{html.escape(r["full_name"])}">'
                 f'{_logo_img(r["team"], logos, 20)}{html.escape(r["name"])}</a></th>{cells}</tr>')
    return f'<table class="lbt sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _rb_panel(p: dict, week: int, embed: bool, logos: dict) -> str:
    n = p.get("n", 4)
    lb = (
        '<div class="lb"><div class="lb-top"><h3>RB usage, every team</h3>'
        '<div class="seg" role="group" aria-label="Table view">'
        f'<button type="button" data-lb="wk" aria-pressed="true">Week {week}</button>'
        f'<button type="button" data-lb="l4" aria-pressed="false">Last {n}</button></div></div>'
        f'<div class="tbl" data-lb="wk">{_lb_table(p["lb_wk"], logos, False)}</div>'
        f'<div class="tbl" data-lb="l4" hidden>{_lb_table(p["lb_l4"], logos, True)}</div>'
        '<p class="lb-note">Tap a column to sort; tap a back to jump to his team. Sorted by xFP: the PPR points an '
        'average back would score on that workload, the best single read on RB value. Opp % is his share of '
        'the backfield\'s carries and targets. HVT = catches plus carries inside the 10. GL = carries inside the 5.</p></div>'
    )
    return lb + _sections(p["entries"], week, embed, "-rb")


def _spark(series: list, up: bool) -> str:
    pts = [(i, v) for i, v in enumerate(series)]
    n = max(len(series) - 1, 1)
    vals = [v for _, v in pts if v is not None]
    hi = max(vals + [0.01])
    color = "#3fe3f0" if up else "#ff4d86"
    xy = lambda i, v: (4 + 76 * i / n, 36 - 30 * (v / hi))  # noqa: E731
    segs, cur = [], []
    for i, v in pts:
        if v is None:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(xy(i, v))
    if cur:
        segs.append(cur)
    lines = "".join(
        f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in sg)}" fill="none" stroke="{color}" '
        f'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>' for sg in segs if len(sg) > 1)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>' for sg in segs for x, y in sg)
    miss = "".join(f'<circle cx="{xy(i, 0)[0]:.1f}" cy="36" r="2.4" fill="none" stroke="#5f6775"/>'
                   for i, v in pts if v is None)
    return (f'<svg class="spark" viewBox="0 0 84 40" role="img" aria-label="Game by game">'
            f'<line x1="2" y1="37" x2="82" y2="37" stroke="#262b35"/>{lines}{dots}{miss}</svg>')


TAG_CLASS = {"Waiver add": "tag-waiver", "Buy": "tag-buy", "Buy low": "tag-buylow", "Sell": "tag-sell", "Watch": "tag-watch"}


def _movers_list(items: list[dict], logos: dict, up: bool, embed: bool) -> str:
    lis = ""
    for it in items:
        m = it["m"]
        arrow, cls = ("\u25B2", "up") if up else ("\u25BC", "down")
        d = round(abs(m.delta) * 100)
        snap = (f"Snaps {m.snap_before:.0%} \u2192 {m.snap_after:.0%}"
                if m.snap_before is not None and m.snap_after is not None else "")
        xfp = (f"xFP/g {m.xfp_before:.1f} \u2192 {m.xfp_after:.1f}"
               if m.xfp_before is not None and m.xfp_after is not None else "")
        meta = " \u00b7 ".join(x for x in (snap, xfp) if x)
        src = it["avatar"]
        if embed:
            src = "data:image/webp;base64," + base64.b64encode(Path(it["avatar_path"]).read_bytes()).decode()
        anchor = f"#{m.team}-l4"
        lis += (
            f'<li data-dir="{"up" if up else "down"}" data-pos="{m.position}" data-all="{1 if it["all"] else 0}" data-pr="{it["pos_rank"]}" '
            f'style="--team:{m.color}">'
            f'<img class="av" src="{src}" alt="" width="56" height="56" loading="lazy">'
            f'<div><div class="mv-top"><a class="mv-name" href="{anchor}" style="text-decoration:none">'
            f'{html.escape(m.player.name)}</a>'
            f'<span class="mv-tag {TAG_CLASS.get(m.tag, "tag-watch")}">{m.tag}</span></div>'
            f'<div class="mv-sub">{m.position} \u00b7 {_logo_img(m.team, logos, 18)}{m.team}</div>'
            f'<div class="mv-stat">{m.metric} <b>{m.before:.0%} \u2192 {m.after:.0%}</b>'
            f'<span class="mv-d {cls}">{arrow}{d}</span></div>'
            f'<div class="mv-meta">{meta}</div>{_evidence_html(m, up)}</div>'
            f'{_spark(m.series, up)}</li>'
        )
    return f'<ol class="movers">{lis}</ol><p class="mv-empty" hidden>Nobody at this position moved enough to make the list.</p>'


GRADE_LABEL = {"Strong": "Strong evidence", "Solid": "Solid evidence", "Thin": "Thin evidence"}


def _evidence_html(m, up: bool) -> str:
    """Grade + the stats that back the call (and the ones that argue against it)."""
    ev = getattr(m, "ev", None) or {}
    if not ev:
        return ""
    pro_mark = "\u25B2" if up else "\u25BC"
    chips = "".join(f'<li class="pro"><b>{pro_mark}</b> {html.escape(a)} <span>{html.escape(b)}</span></li>'
                    for a, b in ev.get("support", [])[:5])
    con_mark = "\u2715" if up else "\u21BA"  # x = argues against a riser; loop = role still intact for a faller
    chips += "".join(f'<li class="con"><b>{con_mark}</b> {html.escape(a)} <span>{html.escape(b)}</span></li>'
                     for a, b in ev.get("counter", [])[:2])
    info = ev.get("info", {})
    extra = ""
    if "wopr" in info:
        a, b = info["wopr"]
        extra = f'<p class="ev-info">WOPR {a:.2f} \u2192 {b:.2f}</p>'
    g = ev.get("grade", "Thin")
    return (f'<div class="ev ev-{g.lower()}"><span class="ev-grade">{GRADE_LABEL.get(g, g)}</span>'
            f'<ul class="chips">{chips or "<li class=con>No supporting stats yet</li>"}</ul>{extra}</div>')


def _movers_panel(p: dict, logos: dict, embed: bool) -> str:
    n = p.get("n", 4)
    k = n // 2
    return (
        f'<p class="mv-intro">Whose role grew or shrank across each team\'s last {n} games: the last {k} vs the first '
        f'{k}, counting only games he played. Receivers and tight ends move on target share, running backs on '
        f'backfield share. Then every move is checked against the stats that confirm a real role change, and graded '
        f'<b>Strong</b>, <b>Solid</b> or <b>Thin</b>. Only Strong or Solid moves get a Waiver add, Buy or Sell tag.</p>'
        '<div class="filters" role="group" aria-label="Position">'
        + "".join(f'<button type="button" data-pos="{v}" aria-pressed="{"true" if v == "all" else "false"}">{lbl}</button>'
                  for v, lbl in (("all", "All"), ("RB", "RB"), ("WR", "WR"), ("TE", "TE")))
        + '</div>'
        f'<h3 class="mv-h up">\u25B2 Risers</h3>{_movers_list(p["risers"], logos, True, embed)}'
        f'<h3 class="mv-h down">\u25BC Fallers</h3>{_movers_list(p["fallers"], logos, False, embed)}'
        '<p class="lb-note"><b>What counts as evidence.</b> Receivers: snaps, air yards share (deeper looks, not just '
        'more), end-zone targets, targets per route and yards per route (2.0+ is excellent). Backs: snaps, goal-line '
        'and red-zone carry share, targets per game, yards after contact, broken tackles, expected points per game. '
        'WOPR is shown but not counted, since it moves with target share. Routes aren\'t public for 2026, so they\'re '
        'estimated as snap share \u00d7 team dropbacks (marked est.; generous for blocking tight ends). '
        '<b>Tags.</b> Waiver add: barely used early, real role now. Buy: had a role and it grew. Buy low: looks dipped '
        'but the role signs held. Sell: the role is shrinking on several fronts. Watch: thin or mixed. Players who '
        'missed the latest game are left out (that\'s an injury question).</p>'
    )



TOP8_COLS = (  # (header, key, kind, tooltip)
    ("Car", "car", "int", "Carries"),
    ("Yds", "yds", "int", "Rushing yards"),
    ("Rush", "rush", "pct", "Rush share: his share of the team's carries"),
    ("Snap", "snap", "pct", "Snap share: his share of the team's offensive snaps"),
    ("HVT", "hvt", "int", "High-value touches: catches + carries inside the 10"),
    ("xFP", "xfp", "dec", "Expected PPR points from his usage"),
)


def _top8(rows: list[dict], logos: dict, per_game: bool) -> str:
    rows = sorted(rows, key=lambda r: (-r["car"], -(r["xfp"] or 0)))[:8]
    head = '<th scope="col" class="pl">Top 8 rushers</th>' + "".join(
        f'<th scope="col" title="{html.escape(tip)}"{" aria-sort=" + chr(34) + "descending" + chr(34) if k == "car" else ""}>'
        f'<button type="button">{h + ("/g" if per_game and k == "xfp" else "")}</button></th>'
        for h, k, _, tip in TOP8_COLS)
    body = ""
    for r in rows:
        cells = ""
        for _, k, kind, _ in TOP8_COLS:
            v = r.get(k)
            if v is None:
                cells += '<td data-v="">\u2013</td>'
                continue
            txt = f"{v:.0%}" if kind == "pct" else (f"{v:.1f}" if kind == "dec" else f"{v}")
            cells += f'<td data-v="{v}"{" class=hi" if k == "car" else ""}>{txt}</td>'
        anchor = f'{r["team"]}-{"l4rb" if per_game else "rb"}'
        body += (f'<tr><th scope="row" class="pl"><a href="#{anchor}" title="{html.escape(r["full_name"])}">'
                 f'{_logo_img(r["team"], logos, 20)}{html.escape(r["name"])}</a></th>{cells}</tr>')
    note = ("Carries and yards are totals over the span; xFP/g is per game played. " if per_game else "")
    return (f'<div class="top8"><div class="tbl tbl-fit"><table class="lbt sortable"><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>'
            f'<p class="lb-note">{note}Tap a back to jump to his team, or a column to re-sort. '
            f'HVT = catches plus carries inside the 10. xFP = the PPR points an average back would score on that '
            f'workload.</p></div>')


CHART_TABS = {"quad-volume": "Volume", "quad-dual": "Run vs. pass", "split": "Blocking", "shares": "Splits"}


def _league(charts: list[dict], embed: bool, uid: str) -> str:
    """The four league-wide charts behind a small switcher, one visible at a time."""
    if not charts:
        return ""
    btns = "".join(
        f'<button type="button" data-chart="{uid}-{c["key"]}" aria-pressed="{"true" if i == 0 else "false"}">'
        f'{CHART_TABS.get(c["key"], c["title"])}</button>' for i, c in enumerate(charts))
    figs = ""
    for i, c in enumerate(charts):
        src = c["rel"]
        if embed:
            im = Image.open(c["path"]).convert("RGB")
            im.thumbnail((900, 2400))
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=74, method=6)
            src = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
        img = f'<img src="{src}" alt="{html.escape(c["title"])}" loading="lazy">'
        if not embed:
            img = f'<a href="{c["rel"]}" aria-label="Open full size">{img}</a>'
        figs += (f'<figure class="lg" id="{uid}-{c["key"]}"{" hidden" if i else ""}>{img}'
                 f'<figcaption><b>How to read it.</b> {html.escape(c["how"])}</figcaption></figure>')
    return (f'<div class="league"><h3 class="sec-h">League view</h3>'
            f'<div class="chart-tabs" role="group" aria-label="Chart">{btns}</div>{figs}</div>')


def _oline(notes: list[dict], logos: dict, week: int) -> str:
    from .league import note_text
    if not notes:
        return ""
    items = "".join(
        f'<li><span class="ol-team">{_logo_img(t["team"], logos, 22)}{t["team"]}</span>'
        f'<span class="ol-notes">{"<br>".join(html.escape(note_text(n, week)) for n in t["notes"])}</span></li>'
        for t in notes)
    return (f'<section class="oline" aria-labelledby="ol-h"><h3 class="sec-h" id="ol-h">O-line injury notes</h3>'
            f'<p class="lb-note">Starting linemen (80%+ of snaps when playing) who missed time over each team\'s last '
            f'games, with the injury from the official report and how they\'re practicing for Week {week + 1} when that '
            f'report is out. Lines missing starters tend to show up as short teal bars in the Blocking chart.</p>'
            f'<ul class="ol-list">{items}</ul></section>')


def _bf_block(p: dict, week: int, embed: bool, logos: dict, suffix: str, uid: str) -> str:
    return (_top8(p["top8"], logos, p["per_game"]) + _league(p.get("charts", []), embed, uid)
            + '<h3 class="sec-h">Team by team</h3>' + _sections(p["entries"], week, embed, suffix))


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
               take_source: str = "template", logos: dict | None = None, shield: str | None = None) -> Path:
    """
    logos: {team: image src} for the team buttons (falls back to the abbreviation).
    panels: [{key: "wk"|"l4", label, entries, leaders, leaders_title}] - first one shows by default.
    entries: [{team, team_name, color, img_path, img_rel, img_path_m, img_rel_m, img_png_m, take,
               evidence, trend?}]
    """
    css = CSS % {
        "regular": _font_src("Regular", embed, rel_assets),
        "medium": _font_src("Medium", embed, rel_assets),
        "semibold": _font_src("SemiBold", embed, rel_assets),
        "display": _font_src("BigShouldersDisplay-ExtraBold", embed, rel_assets, full=True),
        "ox6": _font_src("Oxanium-SemiBold", embed, rel_assets, full=True),
        "ox8": _font_src("Oxanium-ExtraBold", embed, rel_assets, full=True),
        "embed_css": "@media (min-width:721px){.card{max-width:520px;margin:0 auto}}" if embed else "",
    }
    def all_entries(p):
        if p.get("kind") == "tr":
            return p["tgt"]["entries"] + p["bf"]["entries"]
        return p.get("entries", [])

    teams = {e["team"]: e for p in panels for e in all_entries(p)}
    order = sorted(teams.values(), key=lambda e: e["team_name"])
    nav = "".join(
        f'<a href="#{e["team"]}" data-team="{e["team"]}" style="--team:{e["color"]}" '
        f'aria-label="{html.escape(e["team_name"])}" title="{html.escape(e["team_name"])}">'
        f'{_logo_img(e["team"], logos, 26) or ("<i aria-hidden=true></i>" + e["team"])}</a>'
        for e in order
    )
    tabs = "".join(
        f'<button type="button" role="tab" data-view="{p["key"]}" aria-controls="p-{p["key"]}" '
        f'aria-selected="{"true" if i == 0 else "false"}" class="tab-{p["key"]}">'
        f'<span class="t1">{html.escape(p.get("t1", ""))}</span><span class="t2">{html.escape(p.get("t2", p["label"]))}</span>'
        f'</button>'
        for i, p in enumerate(panels)
    )
    has_tr = any(p.get("kind") == "tr" for p in panels)
    subsw = ('<div class="subsw" role="group" aria-label="Trends view" hidden>'
             '<button type="button" data-sub="tgt" aria-pressed="true">Targets</button>'
             '<button type="button" data-sub="bf" aria-pressed="false">Backfield</button></div>') if has_tr else ""
    body = ""
    for p in panels:
        kind = p.get("kind", "cards")
        if kind == "bf":
            inner = _bf_block(p, week, embed, logos, "-rb", "wkc")
        elif kind == "tr":
            t, b = p["tgt"], p["bf"]
            inner = (f'<div class="sub" data-sub="tgt">{_leaders_html(t.get("leaders"), t.get("leaders_title", ""), logos)}'
                     f'{_sections(t["entries"], week, embed, "-l4")}</div>'
                     f'<div class="sub" data-sub="bf" hidden>{_bf_block(b, week, embed, logos, "-l4rb", "trc")}</div>'
                     f'{_oline(p.get("oline", []), logos, week)}')
        elif kind == "mv":
            inner = _movers_panel(p, logos, embed)
        else:
            inner = (f'{_leaders_html(p.get("leaders"), p.get("leaders_title", ""), logos)}'
                     f'{_sections(p["entries"], week, embed, "")}')
        body += (f'<div class="panel" id="p-{p["key"]}" role="tabpanel" aria-label="{html.escape(p["label"])}">'
                 f'<h2 class="panel-h">{html.escape(p.get("heading", p["label"]))}</h2>{inner}</div>')

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
<meta name="theme-color" content="#03050a">
<title>Week {week} · Well Here's A Guy Volumetrics</title>
<meta name="description" content="Week {week} NFL usage report: target share, snap share, backfields, rolling trends and buy/sell risers and fallers for every team.">
{_head_app(rel_assets.rsplit('/', 1)[0])}
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📊</text></svg>">
<script>document.documentElement.classList.add('js')</script>
<style>{css}</style></head>
<body><div class="wrap">
{hero(f"Week {week}", f"{season} Season", "Target share, backfields, trends and buy/sell signals for every NFL team", shield)}
<div class="bar"><div class="tabs" role="tablist" aria-label="View" style="--n:{len(panels)}">{tabs}</div>
<div class="row2">{subsw}<nav aria-label="Jump to a team">{nav}</nav></div></div>
<main>{body}</main>
<footer>{miss}
<p>RB numbers: rush share counts designed runs (no QB scrambles or kneels). xFP is nflverse's expected PPR points
model (ffopportunity). High-value touches follow Ben Gretch's definition (catches plus carries inside the 10).</p>
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
                 "semibold": "assets/fonts/Jost-SemiBold.ttf",
                 "display": "assets/fonts/BigShouldersDisplay-ExtraBold.ttf",
                 "ox6": "assets/fonts/Oxanium-SemiBold.ttf", "ox8": "assets/fonts/Oxanium-ExtraBold.ttf", "embed_css": ""}
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#03050a"><title>Well Here's A Guy Volumetrics</title>
{_head_app('.')}
<style>{css}
.go{{display:block;text-align:center;margin:22px 0;padding:14px;border-radius:10px;border:1px solid var(--line);
    text-decoration:none;font-weight:500;font-size:18px}}
.go:focus-visible{{outline:2px solid var(--banner);outline-offset:3px}}
ul.past{{list-style:none;padding:0;margin:0}} ul.past li{{border-top:1px solid var(--line)}}
ul.past a{{display:block;padding:12px 0;text-decoration:none}}</style></head>
<body><div class="wrap">{hero("Every week", "NFL season", "Target share, backfields, trends and buy/sell signals for every NFL team", "assets/brand/nfl.png" if (docs / "assets/brand/nfl.png").exists() else None)}
{latest}
{'<h2 class="dek" style="text-align:left;margin-top:28px">Earlier weeks</h2><ul class="past">' + items + '</ul>' if items else ''}
</div></body></html>"""
    out = docs / "index.html"
    out.write_text(page, encoding="utf-8")
    import json
    (docs / "manifest.webmanifest").write_text(json.dumps({
        "name": "Well Here's A Guy Volumetrics", "short_name": "Volumetrics",
        "description": "Weekly NFL usage: target share, backfields, trends and buy/sell signals.",
        "start_url": "./", "scope": "./", "display": "standalone",
        "background_color": "#03050a", "theme_color": "#03050a",
        "icons": [{"src": "assets/brand/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "assets/brand/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}],
    }, indent=2))
    return out
