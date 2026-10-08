"""
data.py: pull one NFL week from nflverse and build a tidy per-team usage table.

Every number in the charts and summaries comes from this file, so the
definitions are spelled out here.

Sources (all via nflreadpy / nflverse, free and public):
  play-by-play    -> targets, red-zone targets, catches, yards, TDs
  snap counts     -> offensive snap %, team snap total   (from Pro Football Reference)
  FTN charting    -> drops (optional; CC-BY-SA 4.0, attribute "FTN Data via nflverse")
  players         -> short names, headshot URLs, PFR <-> GSIS id crosswalk
  teams           -> colors and logos
  schedules       -> opponent, home/away, final score

Definitions
  Target         a pass play (play_type == "pass") with a named receiver, excluding
                 two-point tries. Plays wiped out by penalty are play_type "no_play"
                 so they don't count. This matches nflverse's official `targets`
                 column exactly (checked against Week 4, 2026: all 32 teams equal).
  Red-zone tgt   a target thrown with the line of scrimmage inside the opponent's 20.
  Target share   player targets / team targets for that game.
  Snap %         offensive snaps / team offensive snaps (PFR).
  Prior share    the player's average weekly target share in earlier weeks this season
                 where he took at least one offensive snap for this team.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

import nflreadpy as nfl
import polars as pl

log = logging.getLogger(__name__)

SKILL_POSITIONS = {"WR", "TE", "RB", "FB"}
# Red zone = snap inside the opponent's 20 (19 or closer). A throw from exactly the 20
# is not counted, which matches the reference graphics (e.g. CeeDee Lamb, Wk 4 2026: 2 RZ).
RED_ZONE_MAX_YARDLINE = 19
# A player counts as a "regular who sat out" if he averaged this much target share before
REGULAR_SHARE = 0.15


# --------------------------------------------------------------------------- #
# Data containers
# --------------------------------------------------------------------------- #
@dataclass
class PlayerLine:
    gsis_id: str | None
    name: str  # chart label, e.g. "T McMillan"
    full_name: str
    position: str
    headshot: str | None
    headshot_alt: str | None = None  # ESPN headshot, used if the NFL one fails
    targets: int = 0
    tgt_share: float = 0.0
    rz_targets: int = 0
    drops: int = 0
    receptions: int = 0
    rec_yards: int = 0
    rec_tds: int = 0
    snaps: int = 0
    snap_pct: float = 0.0
    prior_tgt_share: float | None = None
    prior_snap_pct: float | None = None
    prior_games: int = 0


@dataclass
class TeamWeek:
    season: int
    week: int
    team: str
    team_name: str  # "Carolina Panthers"
    nick: str  # "Panthers"
    colors: list[str]
    logo_url: str | None
    opponent: str
    home: bool
    team_score: int
    opp_score: int
    total_targets: int
    total_rz_targets: int
    team_snaps: int
    drops_available: bool
    players: list[PlayerLine] = field(default_factory=list)
    absent: list[PlayerLine] = field(default_factory=list)

    @property
    def result(self) -> str:
        if self.team_score > self.opp_score:
            return "W"
        if self.team_score < self.opp_score:
            return "L"
        return "T"

    @property
    def matchup(self) -> str:
        return f"{'vs' if self.home else '@'} {self.opponent}"

    def by_targets(self) -> list[PlayerLine]:
        return sorted(
            [p for p in self.players if p.targets > 0],
            key=lambda p: (-p.targets, -p.snap_pct, p.name),
        )

    def by_snaps(self, positions=SKILL_POSITIONS) -> list[PlayerLine]:
        return sorted(
            [p for p in self.players if p.snaps > 0 and p.position in positions],
            key=lambda p: (-p.snap_pct, -p.targets, p.name),
        )


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=4)
def load_season(season: int) -> dict[str, pl.DataFrame]:
    """Download everything needed for a season once; nflreadpy caches on disk too."""
    log.info("Loading nflverse data for %s ...", season)
    frames = {
        "pbp": nfl.load_pbp(season),
        "snaps": nfl.load_snap_counts(season),
        "players": nfl.load_players(),
        "teams": nfl.load_teams(),
        "sched": nfl.load_schedules(season),
    }
    try:
        frames["ftn"] = nfl.load_ftn_charting(season)
    except Exception as exc:  # FTN sometimes lags a few days; drops are optional
        log.warning("FTN charting unavailable (%s); drops will be omitted", exc)
        frames["ftn"] = None
    return frames


def latest_completed_week(season: int) -> int | None:
    """Most recent regular/post-season week where every scheduled game has a final score."""
    sched = load_season(season)["sched"]
    weeks = (
        sched.group_by("week")
        .agg(pl.col("result").is_not_null().all().alias("done"), pl.len().alias("games"))
        .filter(pl.col("done"))
        .sort("week")
    )
    return int(weeks["week"].max()) if weeks.height else None


def teams_that_played(season: int, week: int) -> list[str]:
    sched = load_season(season)["sched"].filter(
        (pl.col("week") == week) & pl.col("result").is_not_null()
    )
    return sorted(set(sched["home_team"].to_list()) | set(sched["away_team"].to_list()))


def teams_with_snaps(season: int, week: int) -> set[str]:
    snaps = load_season(season)["snaps"]
    return set(snaps.filter(pl.col("week") == week)["team"].unique().to_list())


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _short_name(short: str | None, display: str | None) -> str:
    """'T.McMillan' -> 'T McMillan'; 'A.St. Brown' -> 'A St. Brown'."""
    if short and re.match(r"^[A-Za-z]{1,3}\.", short):
        return re.sub(r"^([A-Za-z]{1,3})\.\s*", r"\1 ", short)
    if display:
        parts = display.split(" ", 1)
        return f"{parts[0][0]} {parts[1]}" if len(parts) == 2 else display
    return short or "Unknown"


def _espn_headshot(espn_id) -> str | None:
    if espn_id is None or str(espn_id) in ("", "None", "nan"):
        return None
    return f"https://a.espncdn.com/i/headshots/nfl/players/full/{int(float(espn_id))}.png"


def _player_lookup(players: pl.DataFrame) -> tuple[dict, dict]:
    """Two dicts: gsis_id -> info, pfr_id -> gsis_id."""
    cols = ["gsis_id", "pfr_id", "espn_id", "display_name", "short_name", "headshot", "position"]
    rows = players.select(cols).to_dicts()
    by_gsis = {r["gsis_id"]: r for r in rows if r["gsis_id"]}
    pfr_to_gsis = {r["pfr_id"]: r["gsis_id"] for r in rows if r["pfr_id"] and r["gsis_id"]}
    return by_gsis, pfr_to_gsis


def _targets(pbp: pl.DataFrame, ftn: pl.DataFrame | None) -> pl.DataFrame:
    """Per game/team/receiver target table from play-by-play (+ drops if FTN present)."""
    t = pbp.filter(
        (pl.col("play_type") == "pass")
        & pl.col("receiver_player_id").is_not_null()
        & (pl.col("two_point_attempt").fill_null(0) == 0)
    ).with_columns(pl.col("play_id").cast(pl.Int64))

    if ftn is not None:
        drops = ftn.select(
            pl.col("nflverse_game_id").alias("game_id"),
            pl.col("nflverse_play_id").cast(pl.Int64).alias("play_id"),
            pl.col("is_drop").fill_null(False),
        )
        t = t.join(drops, on=["game_id", "play_id"], how="left")
    else:
        t = t.with_columns(pl.lit(False).alias("is_drop"))

    return t.group_by(["week", "game_id", "posteam", "receiver_player_id"]).agg(
        pl.len().alias("targets"),
        (pl.col("yardline_100") <= RED_ZONE_MAX_YARDLINE).sum().alias("rz_targets"),
        pl.col("complete_pass").fill_null(0).sum().alias("receptions"),
        pl.col("receiving_yards").fill_null(0).sum().alias("rec_yards"),
        pl.col("pass_touchdown").fill_null(0).sum().alias("rec_tds"),
        pl.col("is_drop").fill_null(False).sum().alias("drops"),
    )


# --------------------------------------------------------------------------- #
# Main builder
# --------------------------------------------------------------------------- #
def build_team_week(season: int, week: int, team: str) -> TeamWeek | None:
    f = load_season(season)
    by_gsis, pfr_to_gsis = _player_lookup(f["players"])

    # ---- game context ----
    g = f["sched"].filter(
        (pl.col("week") == week)
        & ((pl.col("home_team") == team) | (pl.col("away_team") == team))
        & pl.col("result").is_not_null()
    )
    if g.height == 0:
        return None
    g = g.row(0, named=True)
    home = g["home_team"] == team
    opp = g["away_team"] if home else g["home_team"]
    team_score = g["home_score"] if home else g["away_score"]
    opp_score = g["away_score"] if home else g["home_score"]

    trow = f["teams"].filter(pl.col("team_abbr") == team).row(0, named=True)
    colors = [c for c in (trow.get(f"team_color{s}") for s in ("", "2", "3", "4")) if c]

    # ---- targets (all weeks for this team, so we can compute prior shares) ----
    tg = _targets(f["pbp"].filter(pl.col("posteam") == team), f["ftn"])
    tg_week = tg.filter(pl.col("week") == week)
    total_targets = int(tg_week["targets"].sum())
    total_rz = int(tg_week["rz_targets"].sum())
    if total_targets == 0:
        log.warning("%s week %s: no targets found in pbp", team, week)

    # ---- snaps ----
    sn = f["snaps"].filter(pl.col("team") == team).with_columns(
        pl.col("pfr_player_id")
        .map_elements(lambda x: pfr_to_gsis.get(x), return_dtype=pl.Utf8)
        .alias("gsis_id")
    )
    sn_week = sn.filter(pl.col("week") == week)
    if sn_week.height == 0:
        log.warning("%s week %s: snap counts not posted yet", team, week)
        return None
    # Team snaps: back out from players' snaps / pct (QB/OL rows are ~100% so this is tight)
    est = sn_week.filter(pl.col("offense_pct") >= 0.5).select(
        (pl.col("offense_snaps") / pl.col("offense_pct")).median()
    ).item()
    team_snaps = int(round(est)) if est else int(sn_week["offense_snaps"].max())

    # ---- assemble player lines ----
    lines: dict[str, PlayerLine] = {}

    def get_line(gsis: str | None, fallback_name: str, fallback_pos: str) -> PlayerLine:
        key = gsis or f"name:{fallback_name}"
        if key not in lines:
            info = by_gsis.get(gsis, {}) if gsis else {}
            full = info.get("display_name") or fallback_name
            lines[key] = PlayerLine(
                gsis_id=gsis,
                name=_short_name(info.get("short_name"), full),
                full_name=full,
                position=fallback_pos or info.get("position") or "",
                headshot=info.get("headshot"),
                headshot_alt=_espn_headshot(info.get("espn_id")),
            )
        return lines[key]

    for r in sn_week.filter(pl.col("offense_snaps") > 0).to_dicts():
        pl_ = get_line(r["gsis_id"], r["player"], r["position"])
        pl_.snaps = int(r["offense_snaps"])
        pl_.snap_pct = float(r["offense_pct"])

    for r in tg_week.to_dicts():
        info = by_gsis.get(r["receiver_player_id"], {})
        pl_ = get_line(r["receiver_player_id"], info.get("display_name", "Unknown"), info.get("position", ""))
        pl_.targets = int(r["targets"])
        pl_.tgt_share = r["targets"] / total_targets if total_targets else 0.0
        pl_.rz_targets = int(r["rz_targets"])
        pl_.receptions = int(r["receptions"])
        pl_.rec_yards = int(r["rec_yards"])
        pl_.rec_tds = int(r["rec_tds"])
        pl_.drops = int(r["drops"])

    # ---- prior-week context (season to date, before this week) ----
    prior = _prior_context(tg.filter(pl.col("week") < week), sn.filter(pl.col("week") < week))
    for key, pl_ in lines.items():
        if pl_.gsis_id and pl_.gsis_id in prior:
            p = prior[pl_.gsis_id]
            pl_.prior_tgt_share, pl_.prior_snap_pct, pl_.prior_games = p["share"], p["snap"], p["games"]

    # ---- regulars who didn't play this week ----
    played = {p.gsis_id for p in lines.values() if p.gsis_id}
    absent = []
    for gsis, p in prior.items():
        if gsis not in played and p["share"] >= REGULAR_SHARE and p["position"] in SKILL_POSITIONS:
            info = by_gsis.get(gsis, {})
            full = info.get("display_name") or p["name"]
            absent.append(
                PlayerLine(
                    gsis_id=gsis,
                    name=_short_name(info.get("short_name"), full),
                    full_name=full,
                    position=p["position"],
                    headshot=info.get("headshot"),
                    headshot_alt=_espn_headshot(info.get("espn_id")),
                    prior_tgt_share=p["share"],
                    prior_snap_pct=p["snap"],
                    prior_games=p["games"],
                )
            )

    return TeamWeek(
        season=season,
        week=week,
        team=team,
        team_name=trow["team_name"],
        nick=trow["team_nick"],
        colors=colors,
        logo_url=trow.get("team_logo_espn"),
        opponent=opp,
        home=home,
        team_score=int(team_score),
        opp_score=int(opp_score),
        total_targets=total_targets,
        total_rz_targets=total_rz,
        team_snaps=team_snaps,
        drops_available=f["ftn"] is not None
        and f["ftn"].filter(pl.col("week") == week).height > 0,
        players=list(lines.values()),
        absent=sorted(absent, key=lambda p: -(p.prior_tgt_share or 0)),
    )


def _prior_context(tg_prior: pl.DataFrame, sn_prior: pl.DataFrame) -> dict[str, dict]:
    """Average weekly target share and snap % for each player in earlier weeks."""
    if sn_prior.height == 0:
        return {}
    team_tgts = tg_prior.group_by("week").agg(pl.col("targets").sum().alias("team_targets"))
    shares = tg_prior.join(team_tgts, on="week").select(
        "week",
        pl.col("receiver_player_id").alias("gsis_id"),
        (pl.col("targets") / pl.col("team_targets")).alias("share"),
    )
    snaps = sn_prior.filter((pl.col("offense_snaps") > 0) & pl.col("gsis_id").is_not_null()).select(
        "week", "gsis_id", "player", "position", pl.col("offense_pct").alias("snap")
    )
    # Games = weeks with an offensive snap; weeks with snaps but no targets count as 0% share
    merged = snaps.join(shares, on=["week", "gsis_id"], how="left").with_columns(
        pl.col("share").fill_null(0.0)
    )
    agg = merged.group_by("gsis_id").agg(
        pl.col("share").mean(),
        pl.col("snap").mean(),
        pl.len().alias("games"),
        pl.col("player").last().alias("name"),
        pl.col("position").last(),
    )
    return {r["gsis_id"]: r for r in agg.to_dicts()}


def to_rows(tw: TeamWeek) -> list[dict]:
    """Flat rows for the audit CSV that ships with every weekly report."""
    out = []
    for p in sorted(tw.players, key=lambda p: (-p.targets, -p.snap_pct)):
        if p.position not in SKILL_POSITIONS and p.targets == 0:
            continue
        out.append(
            {
                "season": tw.season,
                "week": tw.week,
                "team": tw.team,
                "player": p.full_name,
                "label": p.name,
                "pos": p.position,
                "targets": p.targets,
                "team_targets": tw.total_targets,
                "tgt_share": round(p.tgt_share, 4),
                "rz_targets": p.rz_targets,
                "drops": p.drops if tw.drops_available else None,
                "rec": p.receptions,
                "rec_yds": p.rec_yards,
                "rec_td": p.rec_tds,
                "snaps": p.snaps,
                "team_snaps": tw.team_snaps,
                "snap_pct": round(p.snap_pct, 4),
                "prior_tgt_share": None if p.prior_tgt_share is None else round(p.prior_tgt_share, 4),
                "prior_snap_pct": None if p.prior_snap_pct is None else round(p.prior_snap_pct, 4),
                "prior_games": p.prior_games,
            }
        )
    return out
