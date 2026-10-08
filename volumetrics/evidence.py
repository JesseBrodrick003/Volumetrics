"""
evidence.py: the "why" behind every riser and faller.

A usage change alone isn't enough to act on. For each mover we compare the first half of his
team's window with the second half (games he played) on the stats analysts use to confirm a
role change, then grade how much of it backs the call.

WR / TE
  Snap share            on the field more?                                   PFR snap counts
  Air yards share       trusted with deeper looks? (his air yards / team's)  nflverse pbp
  WOPR                  1.5 x target share + 0.7 x air yards share (shown, not counted: it moves
                        with target share, so it can't independently confirm a target-share change)
  End-zone targets      throws into the end zone (air yards reach the goal line)
  Targets / route (est) earning looks when he's out there                    see note
  Yards / route (est)   producing when he's out there (2.0+ is excellent)    see note
RB
  Snap share            trusted on more downs
  Goal-line share       his share of the team's carries inside the 5
  Red-zone carry share  his share of carries inside the 20
  Targets per game      passing-down role
  Yards after contact   per carry, what he creates himself                   PFR
  Broken tackles        on runs                                               PFR
  xFP per game          expected PPR points from the workload                 nflverse

Note: route participation isn't public for 2026 (play-level participation data stops in 2025),
so routes are ESTIMATED as snap share x team dropbacks in each game. That's accurate for most
receivers (they run a route on nearly every pass play they're in for) and generous for tight
ends who stay in to block. Every number built on it is labeled "est.".
"""

from __future__ import annotations

from functools import lru_cache

import polars as pl

from .data import RED_ZONE_MAX_YARDLINE, _player_lookup, load_season


@lru_cache(maxsize=2)
def _tables(season: int) -> dict:
    f = load_season(season)
    pbp = f["pbp"]
    _, pfr_to_gsis = _player_lookup(f["players"])

    tg = pbp.filter((pl.col("play_type") == "pass") & pl.col("receiver_player_id").is_not_null()
                    & (pl.col("two_point_attempt").fill_null(0) == 0)).with_columns(
        (pl.col("air_yards").is_not_null() & (pl.col("air_yards") >= pl.col("yardline_100"))).alias("ez"))
    p_tg = tg.group_by(["week", "posteam", "receiver_player_id"]).agg(
        pl.len().alias("targets"), pl.col("air_yards").fill_null(0).sum().alias("air"),
        pl.col("ez").sum().alias("ez"), pl.col("receiving_yards").fill_null(0).sum().alias("rec_yds"))
    t_tg = tg.group_by(["week", "posteam"]).agg(pl.len().alias("team_targets"),
                                                pl.col("air_yards").fill_null(0).sum().alias("team_air"))
    db = pbp.filter(pl.col("qb_dropback").fill_null(0) == 1).group_by(["week", "posteam"]).agg(pl.len().alias("dropbacks"))

    runs = pbp.filter((pl.col("play_type") == "run") & pl.col("rusher_player_id").is_not_null()
                      & (pl.col("qb_scramble").fill_null(0) == 0) & (pl.col("two_point_attempt").fill_null(0) == 0))
    p_ru = runs.group_by(["week", "posteam", "rusher_player_id"]).agg(
        pl.len().alias("carries"), (pl.col("yardline_100") <= RED_ZONE_MAX_YARDLINE).sum().alias("rz"),
        (pl.col("yardline_100") <= 5).sum().alias("gl"))
    t_ru = runs.group_by(["week", "posteam"]).agg(
        pl.len().alias("team_carries"), (pl.col("yardline_100") <= RED_ZONE_MAX_YARDLINE).sum().alias("team_rz"),
        (pl.col("yardline_100") <= 5).sum().alias("team_gl"))

    sn = f["snaps"].with_columns(
        pl.col("pfr_player_id").map_elements(lambda x: pfr_to_gsis.get(x), return_dtype=pl.Utf8).alias("gsis"))

    def idx(df, keys):
        return {tuple(r[k] for k in keys): r for r in df.to_dicts()}

    out = {
        "p_tg": idx(p_tg, ["week", "posteam", "receiver_player_id"]),
        "t_tg": idx(t_tg, ["week", "posteam"]),
        "db": idx(db, ["week", "posteam"]),
        "p_ru": idx(p_ru, ["week", "posteam", "rusher_player_id"]),
        "t_ru": idx(t_ru, ["week", "posteam"]),
        "snap": {(r["week"], r["team"], r["gsis"]): r["offense_pct"] for r in sn.to_dicts() if r["gsis"]},
        "adv": {}, "xfp": {},
    }
    adv = f.get("pfr_rush")
    if adv is not None:
        for r in adv.to_dicts():
            g = pfr_to_gsis.get(r["pfr_player_id"])
            if g:
                out["adv"][(r["week"], r["team"], g)] = r
    ffo = f.get("ffo")
    if ffo is not None:
        for r in ffo.select("week", "posteam", "player_id", "total_fantasy_points_exp").to_dicts():
            out["xfp"][(int(r["week"]), r["posteam"], r["player_id"])] = r["total_fantasy_points_exp"] or 0.0
    return out


def half(season: int, team: str, gsis: str, weeks: list[int]) -> dict:
    """Totals over the games in `weeks` that he played (took a snap or touched the ball)."""
    T = _tables(season)
    agg = {k: 0.0 for k in ("games", "snap", "targets", "team_targets", "air", "team_air", "ez", "rec_yds",
                            "routes", "carries", "rz", "gl", "team_rz", "team_gl", "yac", "bt", "adv_car", "xfp")}
    for w in weeks:
        snap = T["snap"].get((w, team, gsis), 0.0) or 0.0
        pt = T["p_tg"].get((w, team, gsis), {})
        pr = T["p_ru"].get((w, team, gsis), {})
        if snap <= 0 and not pt and not pr:
            continue
        tt, tr, db = T["t_tg"].get((w, team), {}), T["t_ru"].get((w, team), {}), T["db"].get((w, team), {})
        agg["games"] += 1
        agg["snap"] += snap
        agg["targets"] += pt.get("targets", 0)
        agg["air"] += pt.get("air", 0)
        agg["ez"] += pt.get("ez", 0)
        agg["rec_yds"] += pt.get("rec_yds", 0)
        agg["team_targets"] += tt.get("team_targets", 0)
        agg["team_air"] += tt.get("team_air", 0)
        agg["routes"] += snap * db.get("dropbacks", 0)  # estimate, see module note
        agg["carries"] += pr.get("carries", 0)
        agg["rz"] += pr.get("rz", 0)
        agg["gl"] += pr.get("gl", 0)
        agg["team_rz"] += tr.get("team_rz", 0)
        agg["team_gl"] += tr.get("team_gl", 0)
        ad = T["adv"].get((w, team, gsis))
        if ad:
            agg["yac"] += ad.get("rushing_yards_after_contact") or 0
            agg["bt"] += ad.get("rushing_broken_tackles") or 0
            agg["adv_car"] += ad.get("carries") or 0
        agg["xfp"] += T["xfp"].get((w, team, gsis), 0.0)
    g = agg["games"] or 1
    a = agg
    return {
        **a,
        "snap": a["snap"] / g,
        "tgt_share": a["targets"] / a["team_targets"] if a["team_targets"] else 0.0,
        "air_share": a["air"] / a["team_air"] if a["team_air"] > 0 else 0.0,
        "tprr": a["targets"] / a["routes"] if a["routes"] >= 8 else None,
        "yprr": a["rec_yds"] / a["routes"] if a["routes"] >= 8 else None,
        "gl_share": a["gl"] / a["team_gl"] if a["team_gl"] else None,
        "rz_share": a["rz"] / a["team_rz"] if a["team_rz"] else None,
        "tpg": a["targets"] / g,
        "yco": a["yac"] / a["adv_car"] if a["adv_car"] >= 8 else None,
        "xfp_pg": a["xfp"] / g,
    }


def _wopr(h):
    return 1.5 * h["tgt_share"] + 0.7 * h["air_share"]


def _p(x):
    return f"{x:.0%}"


def build(season: int, team: str, gsis: str, pos: str, weeks: list[int], rising: bool) -> dict:
    """Returns {grade, support: [chip], counter: [chip], A, B}. A chip is (label, detail)."""
    k = max(len(weeks) // 2, 1)
    A, B = half(season, team, gsis, weeks[:k]), half(season, team, gsis, weeks[-k:])
    sup, con = [], []
    ds = B["snap"] - A["snap"]

    if pos in ("WR", "TE"):
        da = B["air_share"] - A["air_share"]
        if rising:
            if ds >= 0.08: sup.append(("Snaps", f"{_p(A['snap'])} \u2192 {_p(B['snap'])}"))
            # deeper looks, not just more of them: his air-yards share grew AND outpaces his target share
            if da >= 0.05 and B["air_share"] >= max(0.10, B["tgt_share"]):
                sup.append(("Air yards share", f"{_p(A['air_share'])} \u2192 {_p(B['air_share'])}"))
            if B["tprr"] is not None and B["tprr"] >= 0.22: sup.append(("Targets/route", f"{_p(B['tprr'])} (est.)"))
            if B["yprr"] is not None and B["yprr"] >= 1.8: sup.append(("Yards/route", f"{B['yprr']:.2f} (est.)"))
            if B["ez"] >= 1: sup.append(("End-zone targets", f"{int(B['ez'])} lately"))
            if ds <= -0.08: con.append(("Snaps fell", f"{_p(A['snap'])} \u2192 {_p(B['snap'])}"))
            if B["yprr"] is not None and B["targets"] >= 4 and B["yprr"] < 1.0: con.append(("Yards/route", f"only {B['yprr']:.2f} (est.)"))
            if B["tprr"] is not None and B["tprr"] < 0.14: con.append(("Targets/route", f"only {_p(B['tprr'])} (est.)"))
        else:
            if ds <= -0.08: sup.append(("Snaps", f"{_p(A['snap'])} \u2192 {_p(B['snap'])}"))
            if B["tprr"] is not None and B["tprr"] < 0.15: sup.append(("Targets/route", f"{_p(B['tprr'])} (est.)"))
            if B["yprr"] is not None and B["yprr"] < 1.2: sup.append(("Yards/route", f"{B['yprr']:.2f} (est.)"))
            if ds >= -0.03: con.append(("Snaps held", f"{_p(A['snap'])} \u2192 {_p(B['snap'])}"))
            if B["tprr"] is not None and B["tprr"] >= 0.20: con.append(("Still earning", f"{_p(B['tprr'])} targets/route (est.)"))
            if B["air_share"] >= 0.20: con.append(("Air yards share", f"still {_p(B['air_share'])}"))
            if B["ez"] >= 1: con.append(("End-zone targets", f"{int(B['ez'])} lately"))
    else:  # RB
        dt, dx = B["tpg"] - A["tpg"], B["xfp_pg"] - A["xfp_pg"]
        glA, glB = A["gl_share"], B["gl_share"]
        if rising:
            if ds >= 0.10: sup.append(("Snaps", f"{_p(A['snap'])} \u2192 {_p(B['snap'])}"))
            if glB is not None and B["team_gl"] >= 2 and glB >= 0.5 and (glA is None or glB > glA):
                sup.append(("Goal-line carries", f"{int(B['gl'])} of {int(B['team_gl'])}"))
            if B["rz_share"] is not None and B["rz_share"] >= 0.40 and (A["rz_share"] or 0) + 0.15 <= B["rz_share"]:
                sup.append(("Red-zone carry share", f"{_p(A['rz_share'] or 0)} \u2192 {_p(B['rz_share'])}"))
            if dt >= 1.5: sup.append(("Targets/game", f"{A['tpg']:.1f} \u2192 {B['tpg']:.1f}"))
            if B["yco"] is not None and B["yco"] >= 3.0: sup.append(("After contact", f"{B['yco']:.1f} yds/carry"))
            if B["bt"] >= 3: sup.append(("Broken tackles", f"{int(B['bt'])} lately"))
            if dx >= 3: sup.append(("xFP/game", f"{A['xfp_pg']:.1f} \u2192 {B['xfp_pg']:.1f}"))
            if ds <= -0.08: con.append(("Snaps fell", f"{_p(A['snap'])} \u2192 {_p(B['snap'])}"))
            if B["yco"] is not None and B["yco"] < 2.0: con.append(("After contact", f"only {B['yco']:.1f} yds/carry"))
        else:
            if ds <= -0.10: sup.append(("Snaps", f"{_p(A['snap'])} \u2192 {_p(B['snap'])}"))
            if glA is not None and A["team_gl"] >= 2 and (glB or 0) <= glA - 0.3:
                sup.append(("Goal-line share", f"{_p(glA)} \u2192 {_p(glB or 0)}"))
            if dx <= -3: sup.append(("xFP/game", f"{A['xfp_pg']:.1f} \u2192 {B['xfp_pg']:.1f}"))
            if dt <= -1.5: sup.append(("Targets/game", f"{A['tpg']:.1f} \u2192 {B['tpg']:.1f}"))
            if glB is not None and B["team_gl"] >= 2 and glB >= 0.5: con.append(("Still the goal-line back", f"{int(B['gl'])} of {int(B['team_gl'])}"))
            if B["yco"] is not None and B["yco"] >= 3.0: con.append(("After contact", f"{B['yco']:.1f} yds/carry"))
            if ds >= -0.03: con.append(("Snaps held", f"{_p(A['snap'])} \u2192 {_p(B['snap'])}"))

    s, c = len(sup), len(con)
    grade = "Strong" if s >= 3 and c == 0 else ("Solid" if s >= 2 and c <= 1 else "Thin")
    info = {"wopr": (_wopr(A), _wopr(B))} if pos in ("WR", "TE") else {"xfp": (A["xfp_pg"], B["xfp_pg"])}
    return {"grade": grade, "support": sup, "counter": con, "A": A, "B": B, "info": info}
