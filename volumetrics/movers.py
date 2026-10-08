"""
movers.py: league-wide risers and fallers over each team's rolling window.

For every WR/TE/RB we compare the first half of the window with the second half
(with 4 games: games 1-2 vs games 3-4), using only games he actually played:

  WR / TE  target share            (his targets / team targets, per game)
  RB       backfield share         ((carries + targets) / all RB carries + targets, per game)

and pair it with snap share and expected PPR points per game.

Rules (tune here):
  - must have played the latest game (a player who just got hurt is not a "faller")
  - must have played at least one game in each half
  - volume floor so 2% -> 6% noise doesn't make the list
Tags are suggestions from usage alone; we don't know who's rostered in your league:
  Riser that was barely used early  -> "Waiver add"
  Riser that already had a role     -> "Buy"
  Faller whose snaps held           -> "Buy low"   (role intact, looks will come back)
  Faller whose snaps dropped 15+    -> "Sell"      (role is shrinking)
  anything else                     -> "Watch"
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .data import PlayerLine, Window

MIN_DELTA = {"WR": 0.06, "TE": 0.06, "RB": 0.12}
FLOOR = {"WR": 0.12, "TE": 0.12, "RB": 0.25}
LOW_START = {"WR": 0.12, "TE": 0.12, "RB": 0.30}
TOP_N = 12  # shown under "All"
TOP_POS = 8  # shown per position filter
SCALE = {"WR": 0.10, "TE": 0.10, "RB": 0.25}  # a 10-pt target-share jump ~ a 25-pt backfield-share jump


@dataclass
class Mover:
    player: PlayerLine
    team: str
    team_name: str
    color: str
    position: str
    metric: str
    before: float
    after: float
    snap_before: float | None
    snap_after: float | None
    xfp_before: float | None
    xfp_after: float | None
    series: list = field(default_factory=list)
    weeks: list = field(default_factory=list)
    tag: str = ""

    @property
    def delta(self) -> float:
        return self.after - self.before

    @property
    def score(self) -> float:
        """Size of the move, normalized by position so RBs and WRs rank fairly together."""
        ds = (self.snap_after or 0) - (self.snap_before or 0)
        return self.delta / SCALE[self.position] + ds / 0.30

    @property
    def key(self) -> str:
        return (self.player.gsis_id or self.player.full_name).replace(" ", "_")


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _split(vals: list, k: int):
    return vals[:k], vals[-k:]


def candidates(w: Window, color: str) -> list[Mover]:
    out = []
    if w.n < 2:
        return out
    k = w.n // 2
    for p in w.players:
        pos = "RB" if p.position in {"RB", "FB"} else p.position
        if pos not in MIN_DELTA:
            continue
        series = p.wk_bf if pos == "RB" else p.wk_share
        if not series or series[-1] is None:  # didn't play the latest game
            continue
        first, last = _split(series, k)
        a, b = _avg(first), _avg(last)
        if a is None or b is None or max(a, b) < FLOOR[pos] or abs(b - a) < MIN_DELTA[pos]:
            continue
        sf, sl = _split(p.wk_snap, k)
        xf, xl = _split(p.wk_xfp, k)
        m = Mover(player=p, team=w.team, team_name=w.team_name, color=color, position=pos,
                  metric="Backfield share" if pos == "RB" else "Target share",
                  before=a, after=b, snap_before=_avg(sf), snap_after=_avg(sl),
                  xfp_before=_avg(xf), xfp_after=_avg(xl), series=series, weeks=w.weeks)
        ds = (m.snap_after or 0) - (m.snap_before or 0)
        meaningful = b >= (0.40 if pos == "RB" else 0.15) or (m.xfp_after or 0) >= 8
        if m.delta > 0:
            m.tag = ("Waiver add" if a < LOW_START[pos] else "Buy") if meaningful else "Watch"
        else:
            m.tag = "Buy low" if ds >= -0.10 else ("Sell" if ds <= -0.15 else "Watch")
        out.append(m)
    return out


def rank(all_movers: list[Mover]) -> tuple[list[dict], list[dict]]:
    """Each list holds the overall top TOP_N plus the top TOP_POS at each position, with the
    flags the page uses for its position filter."""
    def build(ms):
        out, seen = [], set()
        overall = ms[:TOP_N]
        per_pos = {}
        for m in ms:
            per_pos.setdefault(m.position, []).append(m)
        for i, m in enumerate(ms):
            pr = per_pos[m.position].index(m) + 1
            in_all = m in overall
            if in_all or pr <= TOP_POS:
                if id(m) not in seen:
                    out.append({"m": m, "all": in_all, "pos_rank": pr})
                    seen.add(id(m))
        return out

    risers = sorted((m for m in all_movers if m.delta > 0), key=lambda m: -m.score)
    fallers = sorted((m for m in all_movers if m.delta < 0), key=lambda m: m.score)
    return build(risers), build(fallers)
