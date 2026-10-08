"""
league.py: team-level backfield numbers for the league-wide RB charts, plus O-line notes.

All per team, over a set of that team's games (one week, or its last 4 games played):

  RB carries / game      designed runs by RBs (no QB runs, scrambles, kneels)
  EPA per rush           average expected points added on those carries (nflverse pbp)
  Rush success rate      share of those carries with positive EPA
  RB target share        share of the team's targets that went to RBs
  YBC / att              yards before contact per RB carry  (blocking: O-line + scheme)   PFR
  YAC / att              yards after contact per RB carry   (what the back creates)       PFR
  Broken tackles         rushing broken tackles by RBs                                    PFR
  Backfield split        each back's share of RB carries + targets, and who gets the
                         carries inside the 5
"""

from __future__ import annotations

import polars as pl

from .data import OL_POSITIONS, POSITION_ALIASES, _player_lookup, _short_name, load_season, team_games


def _rb_ids(f) -> set[str]:
    by_gsis, _ = _player_lookup(f["players"])
    return {g for g, r in by_gsis.items() if POSITION_ALIASES.get(r.get("position"), r.get("position")) in {"RB", "FB"}}


def team_backfield(season: int, team: str, weeks: list[int], backs: list | None = None) -> dict | None:
    """backs: the team's PlayerLine list for the same span (from build_team_week / window)."""
    f = load_season(season)
    if not weeks:
        return None
    rb_ids = _rb_ids(f)
    pbp = f["pbp"].filter((pl.col("posteam") == team) & pl.col("week").is_in(weeks))
    runs = pbp.filter(
        (pl.col("play_type") == "run") & pl.col("rusher_player_id").is_in(list(rb_ids))
        & (pl.col("qb_scramble").fill_null(0) == 0) & (pl.col("two_point_attempt").fill_null(0) == 0)
    )
    tg = pbp.filter((pl.col("play_type") == "pass") & pl.col("receiver_player_id").is_not_null()
                    & (pl.col("two_point_attempt").fill_null(0) == 0))
    n_runs = runs.height
    if n_runs == 0:
        return None
    games = len(weeks)
    row = {
        "team": team, "games": games, "weeks": weeks,
        "rb_carries_pg": n_runs / games,
        "epa_per_rush": float(runs["epa"].mean()),
        "success": float((runs["epa"] > 0).mean()),
        "rb_tgt_share": (tg.filter(pl.col("receiver_player_id").is_in(list(rb_ids))).height / tg.height) if tg.height else 0.0,
        "ypc": float(runs["rushing_yards"].fill_null(0).mean()),
    }
    adv = f.get("pfr_rush")
    if adv is not None:
        _, pfr_to_gsis = _player_lookup(f["players"])
        a = adv.filter((pl.col("team") == team) & pl.col("week").is_in(weeks)).with_columns(
            pl.col("pfr_player_id").map_elements(lambda x: pfr_to_gsis.get(x), return_dtype=pl.Utf8).alias("gsis"))
        a = a.filter(pl.col("gsis").is_in(list(rb_ids)))
        car = a["carries"].sum()
        if car:
            row["ybc_att"] = float(a["rushing_yards_before_contact"].fill_null(0).sum() / car)
            row["yac_att"] = float(a["rushing_yards_after_contact"].fill_null(0).sum() / car)
            row["broken_tackles"] = int(a["rushing_broken_tackles"].fill_null(0).sum())
    if backs:
        rbs = sorted([p for p in backs if p.position in {"RB", "FB"} and (p.carries + p.targets) > 0],
                     key=lambda p: -(p.carries + p.targets))
        tot = sum(p.carries + p.targets for p in rbs) or 1
        gl_tot = sum(p.gl_carries for p in rbs)
        row["split"] = [{"name": p.name, "share": (p.carries + p.targets) / tot, "gl": p.gl_carries} for p in rbs]
        row["gl_total"] = gl_tot
    return row


def oline_notes(season: int, week: int, teams: list[str], n: int = 4) -> list[dict]:
    """Starting linemen (80%+ of snaps in the games they played over the window) who missed
    time after they'd been playing, with the injury from the official report, plus how they're
    practicing for the next game if that report is already out."""
    f = load_season(season)
    _, pfr_to_gsis = _player_lookup(f["players"])
    sn = f["snaps"]
    inj = f.get("injuries")
    out = []
    for team in teams:
        weeks = team_games(season, week, team, n)
        if not weeks:
            continue
        s = sn.filter((pl.col("team") == team) & pl.col("week").is_in(weeks) & pl.col("position").is_in(list(OL_POSITIONS)))
        notes = []
        for (pid,), g in s.group_by(["pfr_player_id"]):
            played = g.filter(pl.col("offense_snaps") > 0)
            if played.height == 0 or played["offense_pct"].mean() < 0.80:
                continue
            got = {r["week"]: r["offense_pct"] for r in g.to_dicts()}
            first = min(w for w in weeks if got.get(w, 0) >= 0.25) if any(got.get(w, 0) >= 0.25 for w in weeks) else None
            # only games after he'd started playing count as "missed" (a backup who stepped in didn't miss anything)
            missed = [w for w in weeks if first is not None and w > first and got.get(w, 0) < 0.25]
            gsis = pfr_to_gsis.get(pid)
            name, pos = g["player"][0], g["position"][0]
            injury, nxt = "", None
            if inj is not None and gsis:
                rep = inj.filter((pl.col("team") == team) & (pl.col("gsis_id") == gsis))
                past = rep.filter(pl.col("week").is_in(weeks)).sort("week")
                if past.height and past.row(-1, named=True)["report_primary_injury"]:
                    injury = past.row(-1, named=True)["report_primary_injury"].lower()
                up = rep.filter(pl.col("week") == week + 1)
                if up.height:
                    r = up.row(0, named=True)
                    reason = (r["practice_primary_injury"] or r["report_primary_injury"] or "").lower()
                    if "not injury related" not in reason:  # rest days aren't injury news
                        ps = r["practice_status"] or ""
                        nxt = r["report_status"] or ("DNP" if ps.startswith("Did Not") else "Limited" if ps.startswith("Limited") else None)
                        injury = injury or reason
            if (missed and missed[-1] == weeks[-1]) or len(missed) >= 2 or nxt in ("Out", "Doubtful", "DNP"):
                notes.append({"name": name, "pos": "OL" if pos == "OL" else pos, "missed": missed, "injury": injury,
                              "next": nxt, "missed_latest": bool(missed) and missed[-1] == weeks[-1]})
        if notes:
            notes.sort(key=lambda x: (not x["missed_latest"], -len(x["missed"])))
            out.append({"team": team, "weeks": weeks, "notes": notes,
                        "starters_out": sum(x["missed_latest"] for x in notes)})
    out.sort(key=lambda t: (-t["starters_out"], -len(t["notes"]), t["team"]))
    return out


def note_text(n: dict, week: int) -> str:
    """'G Sam Cosmi (knee): missed Weeks 3-4; DNP in practice for Week 5'"""
    bits = []
    if n["missed"]:
        ws = n["missed"]
        bits.append(f"missed Week {ws[0]}" if len(ws) == 1 else f"missed Weeks {', '.join(map(str, ws))}")
    if n["next"]:
        bits.append({"DNP": f"didn't practice ahead of Week {week + 1}", "Limited": f"limited in practice ahead of Week {week + 1}",
                     "Out": f"ruled out for Week {week + 1}", "Doubtful": f"doubtful for Week {week + 1}",
                     "Questionable": f"questionable for Week {week + 1}"}.get(n["next"], n["next"]))
    inj = f" ({n['injury']})" if n["injury"] else ""
    return f"{n['pos']} {n['name']}{inj}: {'; '.join(bits)}"
