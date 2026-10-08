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

from volumetrics.charts import FONT_DIR, accent, avatar, fetch_image, render_cards
from volumetrics import league
from volumetrics import movers as M
from volumetrics.league_charts import render_league
from volumetrics.insights import detect_rb_signals, detect_signals, detect_window_signals, write_take
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
    ap.add_argument("--week", type=int, nargs="*", default=None, help="one or more weeks (default: latest)")
    ap.add_argument("--force", action="store_true", help="rebuild even if the week is already complete")
    ap.add_argument("--teams", nargs="*", default=None, help="team abbreviations, e.g. CAR DAL")
    ap.add_argument("--out", type=Path, default=ROOT / "docs")
    ap.add_argument("--brand", default=os.getenv("VOLUMETRICS_BRAND") or "WELL HERE'S A GUY VOLUMETRICS",
                    help="text in the top-right corner of every chart (your handle)")
    ap.add_argument("--no-llm", action="store_true", help="skip the Claude voice pass even if a key is set")
    ap.add_argument("--embed", action="store_true", help="also write report-standalone.html with everything inlined")
    ap.add_argument("--window", type=int, default=4, help="games in the rolling tab (0 = no tab)")
    ap.add_argument("--skip-if-exists", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.week and len(a.week) > 1:  # several weeks: build each one in turn
        args = list(argv if argv is not None else sys.argv[1:])
        i = args.index("--week")
        j = i + 1
        while j < len(args) and not args[j].startswith("-"):
            j += 1
        base = args[:i] + args[j:]
        return max(main(base + ["--week", str(w)]) for w in a.week)

    season = a.season or current_season()
    week = (a.week[0] if a.week else None) or D.latest_completed_week(season)
    if not week:
        log.info("No completed weeks for %s yet. Nothing to do.", season)
        return 0

    out_dir = a.out / str(season) / f"week-{week:02d}"
    manifest_path = out_dir / "manifest.json"
    if a.skip_if_exists and not a.force and manifest_path.exists():
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

    if a.teams is None and (out_dir / "img").exists():
        shutil.rmtree(out_dir / "img")  # full rebuild: clear old cards so stale files don't pile up
    use_llm = bool(os.getenv("ANTHROPIC_API_KEY")) and not a.no_llm
    entries, rows, takes = [], [], {}
    D.load_season(season)  # load once here; forked workers inherit it instead of re-downloading
    jobs = [("wk", season, week, t, out_dir, a.brand, use_llm, 1) for t in todo]
    for team, res in zip(todo, _run_parallel(jobs)):
        if res is None:
            log.warning("%s: no usable data, skipped", team)
            missing.append(team)
            continue
        entries.append(res["entry"])
        rows.extend(res["rows"])
        takes[team] = res["take"]
        log.info("%-3s done (%s)", team, res["take"]["source"])

    if not entries:
        log.error("Nothing rendered.")
        return 1

    entries.sort(key=lambda e: e["team_name"])  # same order as the reference: by city
    color = {e["team"]: e["color"] for e in entries}
    leaders = [  # top target shares of the week (8+ targets), linked to each team
        {"label": r["label"], "team": r["team"], "anchor": r["team"], "share": r["tgt_share"], "color": color[r["team"]]}
        for r in sorted((r for r in rows if r["targets"] >= 8), key=lambda r: -r["tgt_share"])[:5]
    ]
    panels = [{"key": "wk", "t1": f"Week {week}", "t2": "Targets", "label": f"Week {week} Targets",
               "heading": f"Week {week} targets", "entries": entries,
               "leaders": leaders, "leaders_title": "Top target shares this week"}]

    rows_l4, takes_l4, takes_rb = [], {}, {}
    if a.window and a.window > 1:
        all_teams = sorted(set(D.load_season(season)["snaps"].filter(D.pl.col("week") <= week)["team"].to_list()))
        wanted_l4 = [t for t in all_teams if not a.teams or t in wanted]
        logo_urls = {r["team_abbr"]: r.get("team_logo_espn") for r in D.load_season(season)["teams"].to_dicts()}
        logo_dir = a.out / "assets" / "logos"

        def league_block(rows, span, key):
            """The four league-wide backfield charts for one span, stored as WebP."""
            rows = [r for r in rows if r]
            if not rows:
                return []
            import volumetrics.league_charts as LC
            LC.BRAND_TEXT = a.brand
            charts = render_league(rows, span, out_dir / "img" / "league" / key, logo_urls,
                                   {r["team"]: r["colors"] for r in rows}, logo_dir)
            for c in charts:
                webp = _webp(Path(c["path"]), True)
                c["rel"], c["path"] = f"img/league/{key}/{webp.name}", webp
            return charts

        # ---- Week N Backfield ----
        rb_entries, lb_wk, lg_wk = [], [], []
        jobs = [("rb", season, week, t, out_dir, a.brand, use_llm, a.window) for t in todo]
        for team, res in zip(todo, _run_parallel(jobs)):
            if res is None:
                continue
            rb_entries.append(res["entry"])
            lb_wk.extend(res.get("lb", []))
            lg_wk.append(res.get("league"))
            takes_rb[team] = res["take"]
        rb_entries.sort(key=lambda e: e["team_name"])
        log.info("Week %s backfields done (%d teams)", week, len(rb_entries))
        if rb_entries:
            panels.append({"key": "rb", "t1": f"Week {week}", "t2": "Backfield", "label": f"Week {week} Backfield",
                           "heading": f"Week {week} backfields", "kind": "bf", "entries": rb_entries,
                           "top8": lb_wk, "per_game": False,
                           "charts": league_block(lg_wk, f"Week {week}", "wk")})

        # ---- Trends (rolling N): targets ----
        entries_l4, movers_all = [], []
        jobs = [("l4", season, week, t, out_dir, a.brand, use_llm, a.window) for t in wanted_l4]
        for team, res in zip(wanted_l4, _run_parallel(jobs)):
            if res is None:
                continue
            entries_l4.append(res["entry"])
            rows_l4.extend(res["rows"])
            takes_l4[team] = res["take"]
            movers_all.extend(res.get("movers", []))
        entries_l4.sort(key=lambda e: e["team_name"])
        n_l4 = max((len(t["weeks"]) for t in takes_l4.values()), default=a.window)
        color_l4 = {e["team"]: e["color"] for e in entries_l4}
        leaders_l4 = [
            {"label": r["label"], "team": r["team"], "anchor": f'{r["team"]}-l4', "share": r["tgt_share"],
             "color": color_l4[r["team"]]}
            for r in sorted((r for r in rows_l4 if r["targets"] >= 20), key=lambda r: -r["tgt_share"])[:5]
        ]

        # ---- Trends (rolling N): backfield ----
        bf_entries, lb_l4, lg_l4 = [], [], []
        jobs = [("l4rb", season, week, t, out_dir, a.brand, use_llm, a.window) for t in wanted_l4]
        for team, res in zip(wanted_l4, _run_parallel(jobs)):
            if res is None:
                continue
            bf_entries.append(res["entry"])
            lb_l4.extend(res.get("lb", []))
            lg_l4.append(res.get("league"))
            takes_rb[f"{team}-rolling"] = res["take"]
        bf_entries.sort(key=lambda e: e["team_name"])
        log.info("Rolling %d done (%d teams)", n_l4, len(entries_l4))
        first_wk = min((min(r["weeks"]) for r in lg_l4 if r), default=week)
        span = f"Weeks {first_wk}\u2013{week}" if first_wk != week else f"Week {week}"
        if entries_l4:
            panels.append({
                "key": "tr", "t1": "Trends", "t2": f"Rolling {n_l4}", "label": f"Trends (rolling {n_l4})",
                "heading": f"Trends: each team's last {n_l4} games", "kind": "tr", "n": n_l4,
                "tgt": {"entries": entries_l4, "leaders": leaders_l4,
                        "leaders_title": f"Top target shares, last {n_l4} games"},
                "bf": {"entries": bf_entries, "top8": lb_l4, "per_game": True,
                       "charts": league_block(lg_l4, span, "l4")},
                "oline": league.oline_notes(season, week, wanted_l4, n=a.window),
            })

        # ---- Risers & fallers (buy / sell) ----
        risers, fallers = M.rank(movers_all)
        from volumetrics import espn
        league_data = espn.fetch(season)  # None unless ESPN secrets are set; never fails the build
        if league_data:
            log.info("ESPN league connected: %d rostered players", len(league_data["players"]))
        M.apply_league(risers + fallers, league_data)
        if risers or fallers:
            av_dir = out_dir / "img" / "movers"
            av_dir.mkdir(parents=True, exist_ok=True)
            from PIL import Image
            from matplotlib.colors import to_rgb as _rgb
            for item in risers + fallers:
                m = item["m"]
                path = av_dir / f"{m.key}.webp"
                if not path.exists():
                    Image.fromarray(avatar(m.player, _rgb(m.color), px=144)).save(path, "WEBP", quality=88)
                item["avatar"] = f"img/movers/{path.name}"
                item["avatar_path"] = path
            panels.append({"key": "mv", "t1": "Buy \u00b7 Sell", "t2": "Risers & Fallers", "label": "Risers & Fallers",
                           "heading": f"Risers & fallers (buy / sell), last {n_l4} games",
                           "kind": "mv", "entries": [], "risers": risers, "fallers": fallers, "n": n_l4,
                           "league": ({"name": league_data["name"]} if league_data else None)})
            (out_dir / "movers.json").write_text(json.dumps({
                k: [{"player": i["m"].player.full_name, "team": i["m"].team, "pos": i["m"].position,
                     "metric": i["m"].metric, "before": round(i["m"].before, 4), "after": round(i["m"].after, 4),
                     "snap_before": i["m"].snap_before, "snap_after": i["m"].snap_after,
                     "xfp_before": i["m"].xfp_before, "xfp_after": i["m"].xfp_after, "tag": i["m"].tag,
                     "evidence": i["m"].ev.get("grade"), "league": i["m"].league}
                    for i in v] for k, v in (("risers", risers), ("fallers", fallers))}, indent=2))

    source = "claude" if any(t["source"] == "claude" for t in [*takes.values(), *takes_l4.values()]) else "template"
    logo_paths = team_logos([e for p in panels for e in p.get("entries", [])], a.out)
    shield = brand_assets(a.out)
    build_page(season, week, panels, out_dir / "index.html", missing=missing, take_source=source,
               logos=_logo_srcs(logo_paths, False), shield="../../assets/brand/nfl.png" if shield else None)
    if a.embed:
        import base64
        build_page(season, week, panels, out_dir / "report-standalone.html", embed=True,
                   missing=missing, take_source=source, logos=_logo_srcs(logo_paths, True),
                   shield=("data:image/png;base64," + base64.b64encode(shield.read_bytes()).decode()) if shield else None)

    for name, data in (("data.csv", rows), ("data_l4.csv", rows_l4)):
        if data:
            with open(out_dir / name, "w", newline="") as fh:
                wr = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
                wr.writeheader()
                wr.writerows(data)
    (out_dir / "takes.json").write_text(json.dumps(
        {"week": takes, f"last{a.window}": takes_l4, "backfield": takes_rb}, indent=2))

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


SHIELD_URL = "https://raw.githubusercontent.com/nflverse/nflverse-pbp/master/NFL.png"  # nflverse's league logo


def brand_assets(docs: Path) -> Path | None:
    """App icons into docs/assets/brand, plus the league shield for the title (downloaded once)."""
    folder = docs / "assets" / "brand"
    folder.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "assets" / "brand").glob("*.png"):
        shutil.copy2(f, folder / f.name)
    path = folder / "nfl.png"
    if not path.exists():
        img = fetch_image(SHIELD_URL)
        if img is not None:
            img.save(path)
    return path if path.exists() else None


def team_logos(entries: list[dict], docs: Path) -> dict[str, Path]:
    """Small team logos for the team buttons, saved once to docs/assets/logos/ and reused."""
    out = {}
    folder = docs / "assets" / "logos"
    folder.mkdir(parents=True, exist_ok=True)
    for e in entries:
        path = folder / f"{e['team']}.png"
        if not path.exists():
            img = fetch_image(e.get("logo_url"))
            if img is None:
                continue
            img = img.copy()
            img.thumbnail((96, 96))
            img.save(path)
        out[e["team"]] = path
    return out


def _logo_srcs(paths: dict[str, Path], embed: bool) -> dict[str, str]:
    if not embed:
        return {t: f"../../assets/logos/{p.name}" for t, p in paths.items()}
    import base64
    return {t: "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode() for t, p in paths.items()}


def _lb_row(p, tw, team, games: int | None = None) -> dict:
    """One RB leaderboard row. Counts are totals; xFP/FP are per game in the window view."""
    g = max(games or 1, 1)
    return {
        "team": team, "name": p.name, "full_name": p.full_name, "pos": p.position,
        "snap": p.snap_pct, "rush": p.rush_share, "tgt_share": p.tgt_share, "opp": p.bf_share,
        "car": p.carries, "tgt": p.targets, "hvt": p.hvt, "gl": p.gl_carries, "yds": p.rush_yds,
        "xfp": None if p.xfp is None else p.xfp / g, "fp": None if p.fp is None else p.fp / g,
        "games": games,
    }


def _team_job(job):
    """One team, one view: the numbers and the take (fast, main process). Cards are rendered
    afterwards in parallel by render_cards().
    Views: wk = this week's targets, l4 = rolling window, rb = this week's backfield."""
    view, season, week, team, out_dir, brand, use_llm, n = job
    extra = {}
    if view == "wk":
        tw = D.build_team_week(season, week, team)
        if tw is None or tw.total_targets == 0:
            return None
        sub, kind, take = "", "targets", write_take(tw, detect_signals(tw))
    elif view == "l4":
        tw = D.build_team_window(season, week, team, n=n)
        if tw is None or tw.n < 2 or tw.total_targets == 0:
            return None
        sub, kind, take = "l4/", "targets", write_take(tw, detect_window_signals(tw))
        extra["movers"] = M.candidates(tw, to_hex(accent(tw.colors)))
    elif view == "rb":  # this week's backfield
        tw = D.build_team_week(season, week, team)
        if tw is None or not tw.rbs():
            return None
        w = D.build_team_window(season, week, team, n=n)
        sub, kind, take = "rb/", "rb", write_take(tw, detect_rb_signals(tw, w), fallback="carries")
        extra["lb"] = [_lb_row(p, tw, team) for p in tw.rbs() if p.carries + p.targets >= 3]
        extra["league"] = league.team_backfield(season, team, [week], tw.players)
    else:  # l4rb: rolling backfield
        tw = D.build_team_window(season, week, team, n=n)
        if tw is None or tw.n < 2 or not tw.rbs():
            return None
        sub, kind, take = "l4rb/", "rb", write_take(tw, detect_rb_signals(tw, tw), fallback="carries")
        extra["lb"] = [_lb_row(p, tw, team, games=p.games) for p in tw.rbs() if p.carries + p.targets >= 4]
        extra["league"] = league.team_backfield(season, team, tw.weeks, tw.players)
        extra["trend"] = {"weeks": tw.weeks, "label": "Rush share",
                          "rows": [{"name": p.name, "shares": p.wk_rush, "total": p.rush_share}
                                   for p in tw.rbs()[:4] if p.carries]}
    if extra.get("league"):
        extra["league"]["color"] = to_hex(accent(tw.colors))
        extra["league"]["colors"] = tw.colors
    if use_llm:
        take = narrate(tw, take)
    img_m = out_dir / "img" / sub / f"{team}-m.webp"
    img = out_dir / "img" / sub / f"{team}.webp"
    entry = {
        "team": team, "team_name": tw.team_name, "color": to_hex(accent(tw.colors)), "logo_url": tw.logo_url,
        "img_path": img, "img_rel": f"img/{sub}{img.name}",
        "img_path_m": img_m, "img_rel_m": f"img/{sub}{img_m.name}", "img_png_m": f"img/{sub}{img_m.name}",
        "take": take.text, "evidence": [s.evidence for s in take.signals],
    }
    take_rec = {"team_name": tw.team_name, "take": take.text, "source": take.source,
                "signals": [{"key": s.key, "evidence": s.evidence} for s in take.signals]}
    rows = D.to_rows(tw)
    if view == "l4":
        entry["trend"] = {"weeks": tw.weeks, "label": "Target share",
                          "rows": [{"name": p.name, "shares": p.wk_share, "total": p.tgt_share}
                                   for p in tw.by_targets()[:5]]}
        take_rec["weeks"] = tw.weeks
        rows = [{**r, "window_weeks": "-".join(map(str, tw.weeks))} for r in rows]
    if view == "l4rb":
        entry["trend"] = extra.get("trend")
    return {"entry": entry, "rows": rows, "take": take_rec, **extra,
            "cards": [(tw, img_m, "portrait", kind), (tw, img, "landscape", kind)]}


def _run_parallel(jobs):
    results = [_team_job(j) for j in jobs]
    cards = [(tw, path, layout, jobs[0][5], kind) for r in results if r for tw, path, layout, kind in r["cards"]]
    render_cards(cards)
    for r in results:
        if r:
            r.pop("cards")
    return results


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
