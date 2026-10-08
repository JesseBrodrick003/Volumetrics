"""
espn.py: read your ESPN fantasy league so the report knows who's available.

ESPN has no official public API, but the fantasy site itself loads league data from a JSON
endpoint. Private leagues need two cookies from a logged-in browser session:

  ESPN_LEAGUE_ID   the number after leagueId= in your league's URL
  ESPN_S2          cookie "espn_s2"   (long string)
  ESPN_SWID        cookie "SWID"      (looks like {ABCD1234-...}; it also tells us which team is yours)

Store all three as GitHub repo SECRETS. They're never written to the site or the logs.
If anything fails (expired cookie, ESPN changes the endpoint), the report still builds,
just without the league layer, and the log says why.

Player IDs: ESPN uses its own IDs; nflverse's player table carries espn_id, so we map
ESPN roster entries onto the same players the rest of the report uses.
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

ENDPOINTS = (  # ESPN moved league reads to lm-api-reads in 2024; keep the old host as a fallback
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{lid}",
    "https://fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{lid}",
)


def _norm_swid(s: str | None) -> str:
    s = (s or "").strip().upper()
    if s and not s.startswith("{"):
        s = "{" + s + "}"
    return s


def fetch(season: int) -> dict | None:
    lid = (os.getenv("ESPN_LEAGUE_ID") or "").strip()
    if not lid:
        return None
    s2, swid = (os.getenv("ESPN_S2") or "").strip(), _norm_swid(os.getenv("ESPN_SWID"))
    cookies = {"espn_s2": s2, "SWID": swid} if s2 and swid else None
    params = [("view", "mRoster"), ("view", "mTeam"), ("view", "mSettings")]
    headers = {"User-Agent": "Mozilla/5.0 (volumetrics)", "Accept": "application/json"}
    for url in ENDPOINTS:
        try:
            r = requests.get(url.format(season=season, lid=lid), params=params, cookies=cookies,
                             headers=headers, timeout=25)
            if r.status_code in (401, 403):
                log.warning("ESPN said %s: the league is private and the espn_s2/SWID cookies are missing or expired",
                            r.status_code)
                return None
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):  # some views come back wrapped in a list
                data = data[0] if data else {}
            if data.get("teams"):
                return parse(data, swid)
        except Exception as exc:  # try the next host; the report must not fail because of ESPN
            log.warning("ESPN league read failed at %s (%s)", url.split("/apis")[0], exc)
    return None


def parse(data: dict, swid: str = "") -> dict:
    """-> {name, my_team, teams: {id: name}, players: {espn_id(str): {"team": name, "mine": bool}}}"""
    teams, players, mine_id = {}, {}, None
    swid = _norm_swid(swid)
    for t in data.get("teams", []):
        name = t.get("name") or " ".join(x for x in (t.get("location"), t.get("nickname")) if x) or t.get("abbrev") \
            or f"Team {t.get('id')}"
        teams[t.get("id")] = name.strip()
        owners = [_norm_swid(o if isinstance(o, str) else (o or {}).get("id")) for o in (t.get("owners") or [])]
        if swid and swid in owners:
            mine_id = t.get("id")
    for t in data.get("teams", []):
        for e in ((t.get("roster") or {}).get("entries") or []):
            pid = e.get("playerId") or (((e.get("playerPoolEntry") or {}).get("player") or {}).get("id"))
            if pid is not None:
                players[str(int(pid))] = {"team": teams.get(t.get("id"), ""), "mine": t.get("id") == mine_id}
    settings = data.get("settings") or {}
    return {"name": settings.get("name") or "Your league", "my_team": teams.get(mine_id),
            "teams": teams, "players": players}


def status(league: dict | None, espn_id) -> str | None:
    """'available' | 'mine' | 'rostered' | None (no league loaded or unknown player)."""
    if not league or espn_id is None or str(espn_id) in ("", "None", "nan"):
        return None
    try:
        key = str(int(float(espn_id)))
    except (TypeError, ValueError):
        return None
    p = league["players"].get(key)
    if p is None:
        return "available"
    return "mine" if p["mine"] else "rostered"
