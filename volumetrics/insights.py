"""
insights.py: turn a TeamWeek into "the take" that sits under each chart.

Two steps, both transparent:
  1. detect_signals()  rule-based checks with the thresholds listed below. Every signal
                       carries an `evidence` string showing the numbers that tripped it,
                       and those are printed in the report under "Why this take".
  2. write_take()      stitches the strongest 2-4 signals into a short spoken-style
                       paragraph. If ANTHROPIC_API_KEY is set, narrator.py can polish it
                       in the creator's voice, but it only gets these facts to work with.

Thresholds (tune here):
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .data import PlayerLine, TeamWeek, Window

ALPHA_MONSTER = 0.40  # "when a receiver gets over 40% of targets..."
ALPHA = 0.28  # clear No. 1
CO_ALPHA_MIN, CO_ALPHA_GAP = 0.19, 0.04  # two guys within 4 pts, both >= 19%
TREND_DELTA = 0.10  # +/- 10 pts vs prior average = riser / faller
FALLER_PRIOR_MIN = 0.18
PART_TIME_SNAPS, PART_TIME_SHARE = 0.60, 0.17  # earning looks on limited snaps
FULL_TIME_SNAPS, LOW_SHARE = 0.80, 0.09  # on the field, not getting looks
WR_FULL_TIME = 0.75  # "no receiver over 75% snap share"
SPREAD_TOP_MAX, SPREAD_MIN_PLAYERS = 0.25, 4
RB_SHARE, TE_SHARE = 0.15, 0.20
RZ_MIN = 2
DROPS_MIN = 2
HIGH_VOLUME, LOW_VOLUME = 45, 22


def pct(x: float) -> str:
    return f"{x:.0%}"


@dataclass
class Signal:
    key: str
    priority: int
    player: str | None
    evidence: str
    line: str
    suffix_for: str | None = None  # if set, reads as an add-on about that player
    standalone: str | None = None  # wording to use when that player wasn't mentioned yet


@dataclass
class Take:
    text: str
    signals: list[Signal] = field(default_factory=list)
    source: str = "template"  # or "claude"


def _pick(options: list[str], *seed) -> str:
    """Deterministic variety: same team/week always gets the same phrasing."""
    h = int(hashlib.md5("|".join(map(str, seed)).encode()).hexdigest(), 16)
    return options[h % len(options)]


def poss(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _of_team(n: int, total: int) -> str:
    if n == total:
        return "both of the team's" if n == 2 else f"all {n} of the team's"
    return f"{n} of the team's {total}"


def _statline(p: PlayerLine) -> str:
    td = f", {p.rec_tds} TD" if p.rec_tds == 1 else (f", {p.rec_tds} TDs" if p.rec_tds > 1 else "")
    return f"{p.receptions}-{p.rec_yards}{td}"


# --------------------------------------------------------------------------- #
# 1. Signals
# --------------------------------------------------------------------------- #
def detect_signals(tw: TeamWeek) -> list[Signal]:
    S: list[Signal] = []
    seed = (tw.season, tw.week, tw.team)
    ranked = tw.by_targets()
    if not ranked:
        return S
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    pass_catchers = [p for p in tw.players if p.position in {"WR", "TE", "RB", "FB"}]
    wrs = [p for p in pass_catchers if p.position == "WR"]
    max_wr_snap = max((p.snap_pct for p in wrs), default=0)

    # Alpha
    if top.tgt_share >= ALPHA_MONSTER and top.position in {"WR", "TE"}:
        big_day = top.rec_yards >= 100 or top.rec_tds >= 1
        line = (
            _pick([
                f"{top.name} ate {pct(top.tgt_share)} of the targets, {top.targets} looks, and turned it into {_statline(top)}. "
                f"When a receiver clears 40% of the targets, a monster game is usually coming, and that's exactly what we got.",
                f"{top.targets} targets for {top.name}. That's {pct(top.tgt_share)} of the pie, and it went for {_statline(top)}. "
                f"Any time a guy gets over 40% of the looks, you expect a big day, and he delivered.",
            ], *seed, "a40")
            if big_day else
            _pick([
                f"{top.name} soaked up {pct(top.tgt_share)} of the targets ({top.targets} looks) but only got {_statline(top)} out of it. "
                f"That kind of volume doesn't stay quiet for long.",
                f"{top.targets} targets for {top.name}, {pct(top.tgt_share)} of the team's looks, and only {_statline(top)} to show for it. "
                f"I don't care about the box score here; the volume is elite.",
            ], *seed, "a40q")
        )
        S.append(Signal("alpha_40", 10, top.name,
                        f"{top.name}: {top.targets}/{tw.total_targets} = {top.tgt_share:.1%} target share (>= {pct(ALPHA_MONSTER)})", line))
    elif top.tgt_share >= ALPHA and not (second and abs(top.tgt_share - second.tgt_share) <= CO_ALPHA_GAP):
        S.append(Signal("alpha", 8, top.name,
                        f"{top.name}: {top.tgt_share:.1%} target share (>= {pct(ALPHA)})",
                        _pick([
                            f"This passing game runs through {top.name}: {top.targets} targets, {pct(top.tgt_share)} of the share.",
                            f"{top.name} is the clear No. 1 here with {pct(top.tgt_share)} of the targets ({top.targets}).",
                        ], *seed, "alpha")))

    # Co-alphas
    if second and top.tgt_share >= CO_ALPHA_MIN and second.tgt_share >= CO_ALPHA_MIN \
            and top.tgt_share - second.tgt_share <= CO_ALPHA_GAP:
        extra = ""
        if second.snap_pct > top.snap_pct + 0.02:
            extra = f" {second.name} actually played more snaps ({pct(second.snap_pct)} to {pct(top.snap_pct)})."
        elif second.rz_targets > top.rz_targets:
            extra = f" And {second.name} had the bigger red-zone role ({second.rz_targets} RZ to {top.rz_targets})."
        S.append(Signal("co_alpha", 7, f"{top.name}+{second.name}",
                        f"{top.name} {top.tgt_share:.1%} vs {second.name} {second.tgt_share:.1%} (gap <= {pct(CO_ALPHA_GAP)})",
                        _pick([
                            f"{top.name} ({pct(top.tgt_share)}) and {second.name} ({pct(second.tgt_share)}) are a lot closer than most people think.{extra}",
                            f"Look at how tight {top.name} and {second.name} are: {top.targets} targets to {second.targets}.{extra}",
                        ], *seed, "co")))

    # Regular who didn't play -> who benefited (bigger target share or bigger snap share)
    if tw.absent:
        a = tw.absent[0]
        # If the top guy was already the top guy before, he's not "the beneficiary" story
        skip = top.name if top.tgt_share >= ALPHA and (top.prior_tgt_share or 0) >= 0.20 else None
        group = {"RB", "FB"} if a.position in {"RB", "FB"} else {"WR", "TE"}
        cands = [p for p in pass_catchers
                 if p.prior_games >= 1 and p.position in group and p.name not in (a.name, skip)]

        def d_share(p):
            return p.tgt_share - (p.prior_tgt_share or 0)

        def d_snap(p):
            return p.snap_pct - (p.prior_snap_pct or 0)

        # Prefer the clearest target-share jump; otherwise whoever inherited the snaps
        ben = max(cands, key=d_share, default=None)
        if ben is not None and d_share(ben) < 0.08:
            ben = max(cands, key=d_snap)
        if ben is not None:
            d_share = ben.tgt_share - (ben.prior_tgt_share or 0)
            d_snap = ben.snap_pct - (ben.prior_snap_pct or 0)
            ev = (f"{a.name} averaged {pct(a.prior_tgt_share)} share before, 0 offensive snaps this week; "
                  f"{ben.name} share {pct(ben.prior_tgt_share or 0)} -> {pct(ben.tgt_share)}, "
                  f"snaps {pct(ben.prior_snap_pct or 0)} -> {pct(ben.snap_pct)}")
            if d_share >= 0.05:
                S.append(Signal("absent", 9, ben.name, ev, _pick([
                    f"With {a.name} not taking an offensive snap, {ben.name} jumped to {pct(ben.tgt_share)} of the targets "
                    f"after averaging {pct(ben.prior_tgt_share or 0)}. If {a.name} is out another week, {ben.name} is a sneaky pickup.",
                    f"{a.name} didn't play a snap, and {ben.name} is the guy who soaked it up: {pct(ben.tgt_share)} of the targets, "
                    f"up from {pct(ben.prior_tgt_share or 0)}. Keep him in mind if {a.name} misses more time.",
                ], *seed, "abs")))
            elif d_snap >= 0.15:
                S.append(Signal("absent", 9, ben.name, ev,
                    f"With {a.name} not taking an offensive snap, notice {ben.name} was out there for {pct(ben.snap_pct)} "
                    f"of the snaps, up from {pct(ben.prior_snap_pct or 0)}. The targets haven't caught up yet, but if {a.name} "
                    f"is out another week, he's a sneaky pickup."))
    # Risers / fallers (need at least 2 prior games so one weird week doesn't drive it)
    for p in ranked:
        if p.prior_tgt_share is None or p.prior_games < 2:
            continue
        d = p.tgt_share - p.prior_tgt_share
        if d >= TREND_DELTA and p.tgt_share >= 0.18 and p.name != top.name:
            S.append(Signal("riser", 7, p.name,
                            f"{p.name}: {pct(p.prior_tgt_share)} prior avg -> {pct(p.tgt_share)} (+{d:.0%})",
                            _pick([
                                f"Notice {p.name} is trending up: {pct(p.tgt_share)} of the targets this week vs {pct(p.prior_tgt_share)} coming in.",
                                f"{poss(p.name)} role is growing: {pct(p.tgt_share)} of the looks after averaging {pct(p.prior_tgt_share)}.",
                            ], *seed, "rise", p.name)))
    for p in pass_catchers:
        if p.prior_tgt_share is None or p.prior_games < 2 or p.prior_tgt_share < FALLER_PRIOR_MIN or p.snaps == 0:
            continue
        d = p.prior_tgt_share - p.tgt_share
        if d >= TREND_DELTA:
            snap_drop = (p.prior_snap_pct or 0) - p.snap_pct
            if snap_drop >= 0.20 and p.snap_pct < 0.40:
                line = (f"{p.name} fell to {pct(p.tgt_share)} of the targets and only played {pct(p.snap_pct)} of the snaps "
                        f"after averaging {pct(p.prior_snap_pct)}, so something kept him off the field. Check the injury "
                        f"report before reading anything into it.")
            elif snap_drop >= 0.20:
                line = (f"{p.name} fell to {pct(p.tgt_share)} of the targets after averaging {pct(p.prior_tgt_share)}, "
                        f"and his snaps dropped to {pct(p.snap_pct)} from {pct(p.prior_snap_pct)}. That looks like a role "
                        f"change, not noise, so I'd wait a week before buying.")
            else:
                line = _pick([
                    f"{p.name} only saw {pct(p.tgt_share)} of the targets after averaging {pct(p.prior_tgt_share)}, "
                    f"even on {pct(p.snap_pct)} of the snaps. The role is still there. This is a buy-low window.",
                    f"Don't panic on {p.name}: {pct(p.tgt_share)} of the looks this week, but he was at {pct(p.prior_tgt_share)} "
                    f"coming in and still played {pct(p.snap_pct)} of the snaps. I'd buy low.",
                ], *seed, "fall", p.name)
            S.append(Signal("faller", 7, p.name,
                            f"{p.name}: {pct(p.prior_tgt_share)} prior avg -> {pct(p.tgt_share)}; snaps {pct(p.prior_snap_pct or 0)} -> {pct(p.snap_pct)}",
                            line))

    # Snap vs target mismatches
    for p in ranked:
        if p.snap_pct <= PART_TIME_SNAPS and p.tgt_share >= PART_TIME_SHARE and p.targets >= 4:
            S.append(Signal("part_time", 6, p.name,
                            f"{p.name}: {pct(p.tgt_share)} target share on {pct(p.snap_pct)} snaps",
                            _pick([
                                f"{p.name} pulled {pct(p.tgt_share)} of the targets on just {pct(p.snap_pct)} of the snaps. If that snap share climbs, he's a sneaky add.",
                                f"Notice {p.name} earned {p.targets} targets while only playing {pct(p.snap_pct)} of the snaps. That's a guy getting open when he's out there.",
                            ], *seed, "pt", p.name)))
    for p in sorted(pass_catchers, key=lambda p: -p.snap_pct):
        if p.position in {"WR", "TE"} and p.snap_pct >= FULL_TIME_SNAPS and p.tgt_share <= LOW_SHARE:
            S.append(Signal("snaps_no_looks", 5, p.name,
                            f"{p.name}: {pct(p.snap_pct)} snaps but {p.targets} targets ({pct(p.tgt_share)})",
                            _pick([
                                (f"Notice {p.name} actually played {pct(p.snap_pct)} of the snaps and didn't get a single target."
                                 if p.targets == 0 else
                                 f"Notice {p.name} actually played {pct(p.snap_pct)} of the snaps but only got {p.targets} target{'s' if p.targets != 1 else ''}."),
                                f"{p.name} was on the field for {pct(p.snap_pct)} of the snaps and saw {'zero' if p.targets == 0 else 'just ' + str(p.targets)} look{'s' if p.targets != 1 else ''}. The routes are there; the targets aren't.",
                            ], *seed, "snl", p.name)))
            break

    # Red zone
    rz_lead = max(ranked, key=lambda p: (p.rz_targets, p.tgt_share))
    if rz_lead.rz_targets >= RZ_MIN and tw.total_rz_targets and rz_lead.rz_targets / tw.total_rz_targets >= 0.4:
        S.append(Signal("red_zone", 6, rz_lead.name,
                        f"{rz_lead.name}: {rz_lead.rz_targets} of {tw.total_rz_targets} team red-zone targets",
                        f"{rz_lead.name} also got {_of_team(rz_lead.rz_targets, tw.total_rz_targets)} red-zone targets, and that's where touchdowns come from.",
                        suffix_for=rz_lead.name,
                        standalone=f"{rz_lead.name} got {_of_team(rz_lead.rz_targets, tw.total_rz_targets)} red-zone targets, and that's where touchdowns come from."))

    # Spread / rotation
    double_digit = [p for p in ranked if p.tgt_share >= 0.10]
    if top.tgt_share < SPREAD_TOP_MAX and len(double_digit) >= SPREAD_MIN_PLAYERS:
        if wrs and max_wr_snap < WR_FULL_TIME:
            S.append(Signal("mess", 7, None,
                            f"top share {pct(top.tgt_share)} (< {pct(SPREAD_TOP_MAX)}), {len(double_digit)} players >= 10%, max WR snaps {pct(max_wr_snap)}",
                            f"This passing offense is a mess: no receiver cleared {pct(WR_FULL_TIME)} of the snaps and nobody got a real share of the targets "
                            f"(top guy was {pct(top.tgt_share)}). Hard to trust anyone here until something changes."))
        else:
            S.append(Signal("spread", 6, None,
                            f"top share {pct(top.tgt_share)} (< {pct(SPREAD_TOP_MAX)}), {len(double_digit)} players >= 10%",
                            _pick([
                                f"A lot of targets spread around this week: {len(double_digit)} guys hit double-digit share and nobody topped {pct(top.tgt_share)}.",
                                f"No one dominated here. {len(double_digit)} different players got 10%+ of the looks, which is fine for the offense and tough for fantasy.",
                            ], *seed, "spread")))
    elif wrs and max_wr_snap < WR_FULL_TIME:
        S.append(Signal("rotation", 5, None, f"max WR snap share {pct(max_wr_snap)} (< {pct(WR_FULL_TIME)})",
                        f"No wide receiver played more than {pct(max_wr_snap)} of the snaps, so a rotation is capping everybody's ceiling."))

    # Position-specific usage
    for p in ranked:
        if p.position == "RB" and p.tgt_share >= RB_SHARE:
            S.append(Signal("rb_targets", 5, p.name, f"{p.name} (RB): {pct(p.tgt_share)} target share",
                            f"{p.name} had {p.targets} targets out of the backfield ({pct(p.tgt_share)}). That's real PPR value."))
            break
    for p in ranked:
        if p.position == "TE" and p.tgt_share >= TE_SHARE:
            S.append(Signal("te_role", 5, p.name, f"{p.name} (TE): {pct(p.tgt_share)} target share",
                            f"{p.name} commanded {pct(p.tgt_share)} of the targets at tight end, and that's a weekly-starter role at the position."))
            break

    if tw.drops_available:
        for p in ranked:
            if p.drops >= DROPS_MIN:
                S.append(Signal("drops", 4, p.name, f"{p.name}: {p.drops} drops (FTN)",
                                f"{p.name} did drop {p.drops} balls, which is the kind of thing that costs you targets if it keeps up.",
                                suffix_for=p.name))
                break

    if tw.total_targets >= HIGH_VOLUME:
        S.append(Signal("volume_high", 3, None, f"{tw.total_targets} team targets (>= {HIGH_VOLUME})",
                        f"{tw.total_targets} targets total, so this team threw a ton. Don't expect every number here to repeat."))
    elif tw.total_targets <= LOW_VOLUME:
        S.append(Signal("volume_low", 3, None, f"{tw.total_targets} team targets (<= {LOW_VOLUME})",
                        f"Only {tw.total_targets} targets to go around, so even a big share doesn't buy much."))

    return sorted(S, key=lambda s: -s.priority)


# --------------------------------------------------------------------------- #
# 2. Template narration
# --------------------------------------------------------------------------- #
def write_take(tw: TeamWeek, signals: list[Signal], max_main: int = 3) -> Take:
    """Pick the strongest signals: one per player, one per signal type, max 3 + 1 add-on."""
    used_players: set[str] = set()
    used_keys: set[str] = set()
    chosen: list[Signal] = []
    n_main = n_suffix = 0
    for s in signals:
        names = set(s.player.split("+")) if s.player else set()
        if s.key in used_keys:
            continue
        if s.suffix_for and s.suffix_for in used_players:
            if n_suffix == 0:  # short add-on about someone already mentioned
                chosen.append(s)
                used_keys.add(s.key)
                n_suffix += 1
            continue
        if n_main >= max_main or (names & used_players):
            continue
        if s.standalone:  # first mention of this player: drop the "also"
            s = Signal(s.key, s.priority, s.player, s.evidence, s.standalone)
        chosen.append(s)
        used_keys.add(s.key)
        used_players |= names
        n_main += 1

    r = tw.by_targets()
    if n_main < 2 and len(r) >= 2 and r[0].name not in used_players:  # thin week: anchor on the leader
        chosen.insert(0, Signal("leaders", 1, r[0].name, "top two by targets",
                                f"{r[0].name} led the way with {r[0].targets} targets ({pct(r[0].tgt_share)}){tw.span}, "
                                f"with {r[1].name} next at {r[1].targets} ({pct(r[1].tgt_share)})."))
    return Take(text=" ".join(s.line for s in chosen), signals=chosen)


# --------------------------------------------------------------------------- #
# Rolling window ("Last 4 games" tab): trends instead of one-week blips
# --------------------------------------------------------------------------- #
W_LOCKED, W_LOCKED_FLOOR = 0.27, 0.20  # owns it: high share AND never below 20% in the window
W_ALPHA = 0.25
W_TREND = 0.08  # last-2-games avg vs first-2-games avg
W_SNAP_TREND = 0.15
W_CONDENSED = 0.55  # top two combined
W_RZ_MIN, W_RZ_SHARE = 4, 0.35


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _halves(vals: list, fill_zero: bool = True):
    """(avg of first two games, avg of last two games). Missed games count as 0 share."""
    v = [(0.0 if x is None else x) if fill_zero else x for x in vals]
    if len(v) < 3:
        return None, None
    k = len(v) // 2
    return _avg(v[:k]), _avg(v[-k:])


def detect_window_signals(w: Window) -> list[Signal]:
    S: list[Signal] = []
    seed = (w.season, w.week, w.team, "w")
    ranked = w.by_targets()
    if not ranked or w.n < 2:
        return S
    n = w.n
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    catchers = [p for p in w.players if p.position in {"WR", "TE", "RB", "FB"}]
    played = [x for x in top.wk_share if x is not None]

    # Who owns this offense
    if top.tgt_share >= W_LOCKED and len(played) == n and min(played) >= W_LOCKED_FLOOR:
        S.append(Signal("locked", 10, top.name,
                        f"{top.name}: {top.tgt_share:.1%} share over {n} games, never below {pct(min(played))}",
                        _pick([
                            f"{top.name} owns this offense: {pct(top.tgt_share)} of the targets over the last {n} games, "
                            f"and he hasn't dipped below {pct(min(played))} in any of them. That's as safe as it gets.",
                            f"{top.targets} targets for {top.name} over the last {n}, {pct(top.tgt_share)} of the pie, "
                            f"and at least {pct(min(played))} every single week. I'm riding this.",
                        ], *seed, "locked")))
    elif top.tgt_share >= W_ALPHA:
        lo, hi = (min(played), max(played)) if played else (0, 0)
        if hi - lo >= 0.15:
            S.append(Signal("alpha_swingy", 8, top.name,
                            f"{top.name}: {top.tgt_share:.1%} share over {n}; weekly range {pct(lo)}-{pct(hi)}",
                            f"{top.name} leads this team at {pct(top.tgt_share)} of the targets over the last {n}, "
                            f"but it's swung anywhere from {pct(lo)} to {pct(hi)} week to week. Expect some boom and some bust."))
        else:
            S.append(Signal("alpha", 8, top.name, f"{top.name}: {top.tgt_share:.1%} share over {n} games",
                            f"{top.name} is the clear No. 1 over the last {n} games: {top.targets} targets, {pct(top.tgt_share)} of the share."))

    if second and top.tgt_share >= 0.20 and second.tgt_share >= 0.20 and top.tgt_share - second.tgt_share <= 0.04:
        S.append(Signal("co_alpha", 7, f"{top.name}+{second.name}",
                        f"{top.name} {top.tgt_share:.1%} vs {second.name} {second.tgt_share:.1%} over {n}",
                        f"{top.name} ({pct(top.tgt_share)}) and {second.name} ({pct(second.tgt_share)}) are basically "
                        f"splitting the top role over the last {n} games."))

    # Trends inside the window
    for p in sorted(catchers, key=lambda p: -p.targets):
        a, b = _halves(p.wk_share)
        if a is None:
            continue
        sa, sb = _halves(p.wk_snap)
        if b - a >= W_TREND and b >= 0.15:
            extra = f" His snaps went from {pct(sa)} to {pct(sb)} too." if sa is not None and sb - sa >= 0.10 else ""
            S.append(Signal("trend_up", 8, p.name,
                            f"{p.name}: {pct(a)} share in the first games of the window -> {pct(b)} in the latest",
                            _pick([
                                f"{p.name} is trending the right way: {pct(a)} of the targets early in this stretch, "
                                f"{pct(b)} in the last two games.{extra} Get him before everyone notices.",
                                f"Notice {poss(p.name)} share climbing: {pct(a)} to {pct(b)} over the last {n} games.{extra} "
                                f"That's a role that's growing.",
                            ], *seed, "up", p.name)))
        elif a - b >= W_TREND and a >= 0.18:
            k = len(p.wk_snap) // 2
            missed = [w.weeks[i] for i in range(len(p.wk_snap) - k, len(p.wk_snap)) if p.wk_snap[i] is None]
            if missed:  # a missed game isn't a role change; say what the data actually shows
                wk = " and ".join(f"Week {x}" for x in missed)
                line = (f"{p.name} didn't play in {wk} after drawing {pct(a)} of the targets early in this stretch. "
                        f"If he's back, he should slide right back into that role, so watch his status.")
            elif sa is not None and sa - sb >= 0.15:
                line = (f"{p.name} is heading the wrong way: {pct(a)} of the targets early in this stretch, {pct(b)} lately, "
                        f"and his snaps fell from {pct(sa)} to {pct(sb)}. That's a real role change.")
            else:
                line = (f"{poss(p.name)} share has slipped from {pct(a)} to {pct(b)}, but he's still playing "
                        f"{pct(sb if sb is not None else p.snap_pct)} of the snaps. The role is there. This is a buy-low window.")
            S.append(Signal("trend_down", 7, p.name,
                            f"{p.name}: share {pct(a)} -> {pct(b)}; snaps {pct(sa or 0)} -> {pct(sb or 0)}", line))

    for p in sorted(catchers, key=lambda p: -p.snaps):
        sa, sb = _halves(p.wk_snap)
        if sa is not None and sb - sa >= W_SNAP_TREND and sb >= 0.60:
            S.append(Signal("snap_climb", 6, p.name, f"{p.name}: snaps {pct(sa)} -> {pct(sb)}",
                            f"Notice {poss(p.name)} snaps went from {pct(sa)} to {pct(sb)} over this stretch. "
                            f"The targets usually follow the snaps."))
            break

    for p in sorted(catchers, key=lambda p: -p.snap_pct):
        if p.position in {"WR", "TE"} and p.snap_pct >= 0.85 and p.tgt_share <= 0.12:
            S.append(Signal("snaps_no_looks", 5, p.name,
                            f"{p.name}: {pct(p.snap_pct)} snaps, {pct(p.tgt_share)} share over {n}",
                            f"{p.name} has been on the field for {pct(p.snap_pct)} of the snaps over the last {n} games "
                            f"but is only drawing {pct(p.tgt_share)} of the targets."))
            break

    rz = max(ranked, key=lambda p: (p.rz_targets, p.tgt_share))
    if rz.rz_targets >= W_RZ_MIN and w.total_rz_targets and rz.rz_targets / w.total_rz_targets >= W_RZ_SHARE:
        S.append(Signal("red_zone", 6, rz.name, f"{rz.name}: {rz.rz_targets} of {w.total_rz_targets} team RZ targets over {n}",
                        f"{rz.name} also has {_of_team(rz.rz_targets, w.total_rz_targets)} red-zone targets over the "
                        f"last {n}. That's the touchdown role.", suffix_for=rz.name,
                        standalone=f"{rz.name} has {_of_team(rz.rz_targets, w.total_rz_targets)} red-zone targets over "
                                   f"the last {n}. That's the touchdown role."))

    if second and top.tgt_share + second.tgt_share >= W_CONDENSED:
        S.append(Signal("condensed", 5, None,
                        f"{top.name} + {second.name} = {top.tgt_share + second.tgt_share:.1%} of targets over {n}",
                        f"Over the last {n} games, {top.name} and {second.name} have soaked up "
                        f"{pct(top.tgt_share + second.tgt_share)} of the targets. Nobody else here matters much for fantasy."))
    elif top.tgt_share < 0.22 and len([p for p in ranked if p.tgt_share >= 0.10]) >= 4:
        S.append(Signal("spread", 5, None, f"top share over {n} games {pct(top.tgt_share)}",
                        f"Nobody has more than {pct(top.tgt_share)} of the targets over the last {n} games. "
                        f"This target tree is flat, so it's hard to trust anyone week to week."))

    for p in ranked:
        if p.position == "RB" and p.tgt_share >= 0.13:
            S.append(Signal("rb_targets", 4, p.name, f"{p.name} (RB): {pct(p.tgt_share)} share over {n}",
                            f"{p.name} has {p.targets} targets out of the backfield over the last {n}. Steady PPR value."))
            break
    for p in ranked:
        if p.position == "TE" and p.tgt_share >= 0.18 and p.name != top.name:
            S.append(Signal("te_role", 4, p.name, f"{p.name} (TE): {pct(p.tgt_share)} share over {n}",
                            f"{p.name} is getting {pct(p.tgt_share)} of the looks at tight end over the last {n}, "
                            f"and that's a weekly starter."))
            break

    per_game = w.total_targets / n
    if per_game >= 40:
        S.append(Signal("volume_high", 3, None, f"{per_game:.1f} team targets per game over {n}",
                        f"This team is throwing {per_game:.0f} times a game over the last {n}, so there's plenty of volume to go around."))
    elif per_game <= 26:
        S.append(Signal("volume_low", 3, None, f"{per_game:.1f} team targets per game over {n}",
                        f"Only about {per_game:.0f} targets a game over the last {n}, which caps everyone's ceiling."))

    return sorted(S, key=lambda s: -s.priority)
