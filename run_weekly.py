#!/usr/bin/env python3
"""
Build the weekly Volumetrics report.

  python run_weekly.py                       # latest completed week, current season
  python run_weekly.py --season 2026 --week 4
  python run_weekly.py --teams CAR DAL CLE   # just a few teams
  python run_weekly.py --embed               # also write one self-contained report file
  python run_weekly.py --skip-if-exists      # used by the scheduler; no-op if already complete

Output (GitHub Pages serves ./docs):
  docs/<season>/week-<NN>/index.html   chart + take for every team
  docs/<season>/week-<NN>/img/<TEAM>.png
  docs/<season>/week-<NN>/data.csv     every number used, one row per player
  docs/<season>/week-<NN>/takes.json   takes + the signals/evidence behind them
  docs/<season>/week-<NN>/manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from volumetrics import data as D
from matplotlib.colors import to_hex

from volumetrics.charts import FONT_DIR, LANDSCAPE, PORTRAIT, accent, render_team
from volumetrics.insights import detect_signals, write_take
from volumetrics.narrator import narrate
from volumetrics.report import build_index, build_page

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("volumetrics")


def current_season(today: date | None = None) -> int:
    t = today or date.today()
    return t.year if t.month >= 3 else t.year - 1  # Jan/Feb playoff weeks belong to last season


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--teams", nargs="*", default=None, help="team abbreviations, e.g. CAR DAL")
    ap.add_argument("--out", type=Path, default=ROOT / "docs")
    ap.add_argument("--brand", default=os.getenv("VOLUMETRICS_BRAND") or "VOLUMETRICS",
                    help="text in the top-right corner of every chart (your handle)")
    ap.add_argument("--no-llm", action="store_true", help="skip the Claude voice pass even if a key is set")
    ap.add_argument("--embed", action="store_true", help="also write report-standalone.html with everything inlined")
    ap.add_argument("--skip-if-exists", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    season = a.season or current_season()
    week = a.week or D.latest_completed_week(season)
    if not week:
        log.info("No completed weeks for %s yet. Nothing to do.", season)
        return 0

    out_dir = a.out / str(season) / f"week-{week:02d}"
    manifest_path = out_dir / "manifest.json"
    if a.skip_if_exists and manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        if m.get("complete"):
            log.info("Week %s already complete at %s. Skipping.", week, out_dir)
            _gh_output(built="false", season=season, week=week, complete="true",
                       teams=len(m.get("teams", [])), missing="", path=f"{season}/week-{week:02d}/")
            return 0

    played = D.teams_that_played(season, week)
    with_snaps = D.teams_with_snaps(season, week)
    wanted = [t.upper() for t in a.teams] if a.teams else played
    todo = [t for t in wanted if t in played and t in with_snaps]
    missing = [t for t in wanted if t in played and t not in with_snaps]
    if missing:
        log.warning("Snap counts not posted yet for: %s", ", ".join(missing))
    log.info("Season %s Week %s: building %d teams", season, week, len(todo))

    use_llm = bool(os.getenv("ANTHROPIC_API_KEY")) and not a.no_llm
    entries, rows, takes = [], [], {}
    for team in todo:
        tw = D.build_team_week(season, week, team)
        if tw is None or tw.total_targets == 0:
            log.warning("%s: no usable data, skipped", team)
            missing.append(team)
            continue
        # Phone card (PNG kept so it can be saved/posted) + WebP copies the page actually loads
        img_m = render_team(tw, out_dir / "img" / f"{team}-m.png", brand=a.brand, layout=PORTRAIT)
        land_png = render_team(tw, out_dir / "img" / f"{team}.png", brand=a.brand, layout=LANDSCAPE)
        webp_m = _webp(img_m)
        img = _webp(land_png, remove_png=True)
        take = write_take(tw, detect_signals(tw))
        if use_llm:
            take = narrate(tw, take)
        entries.append({
            "team": team, "team_name": tw.team_name, "color": to_hex(accent(tw.colors)),
            "img_path": img, "img_rel": f"img/{img.name}",
            "img_path_m": img_m, "img_rel_m": f"img/{webp_m.name}", "img_png_m": f"img/{img_m.name}",
            "take": take.text, "evidence": [s.evidence for s in take.signals],
        })
        rows.extend(D.to_rows(tw))
        takes[team] = {"team_name": tw.team_name, "take": take.text, "source": take.source,
                       "signals": [{"key": s.key, "evidence": s.evidence} for s in take.signals]}
        log.info("%-3s done (%s)", team, take.source)

    if not entries:
        log.error("Nothing rendered.")
        return 1

    entries.sort(key=lambda e: e["team_name"])  # same order as the reference: by city
    source = "claude" if any(t["source"] == "claude" for t in takes.values()) else "template"
    color = {e["team"]: e["color"] for e in entries}
    leaders = [  # top target shares of the week (8+ targets), linked to each team
        {"label": r["label"], "team": r["team"], "share": r["tgt_share"], "color": color[r["team"]]}
        for r in sorted((r for r in rows if r["targets"] >= 8), key=lambda r: -r["tgt_share"])[:5]
    ]
    build_page(season, week, entries, out_dir / "index.html", missing=missing,
               take_source=source, leaders=leaders)
    if a.embed:
        build_page(season, week, entries, out_dir / "report-standalone.html", embed=True,
                   missing=missing, take_source=source, leaders=leaders)

    with open(out_dir / "data.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (out_dir / "takes.json").write_text(json.dumps(takes, indent=2))

    # fonts for the hosted pages
    assets = a.out / "assets" / "fonts"
    assets.mkdir(parents=True, exist_ok=True)
    for f in FONT_DIR.glob("*"):
        shutil.copy2(f, assets / f.name)
    build_index(a.out)

    complete = not missing and (a.teams is None)
    manifest_path.write_text(json.dumps({
        "season": season, "week": week, "complete": complete,
        "teams": [e["team"] for e in entries], "missing": missing, "take_source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2))
    log.info("Wrote %s (%d teams, complete=%s)", out_dir / "index.html", len(entries), complete)
    _gh_output(built="true", season=season, week=week, complete=str(complete).lower(),
               teams=len(entries), missing=" ".join(missing), path=f"{season}/week-{week:02d}/")
    return 0


def _webp(png: Path, remove_png: bool = False) -> Path:
    """WebP is ~3x smaller than PNG at the same sharpness, so the page loads fast on phones."""
    from PIL import Image

    out = png.with_suffix(".webp")
    Image.open(png).convert("RGB").save(out, "WEBP", quality=90, method=6)
    if remove_png:
        png.unlink()
    return out


def _gh_output(**kv):
    """When running in GitHub Actions, expose results to later steps (e.g. the email step)."""
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            for k, v in kv.items():
                fh.write(f"{k}={v}\n")


if __name__ == "__main__":
    sys.exit(main())
