"""
narrator.py: optional voice pass with Claude.

If ANTHROPIC_API_KEY is set, each team's template take is rewritten to sound like a
fantasy analyst talking to camera. The model only receives the numbers and the
triggered signals for that team, and is told not to add anything else (no injury
reasons, no player history, no projections it can't back with the data). If the call
fails for any reason, the template take is kept, so the weekly job never breaks
because of this step.

Env vars
  ANTHROPIC_API_KEY     turns this on
  VOLUMETRICS_MODEL     model id (default below)
"""

from __future__ import annotations

import json
import logging
import os

from .data import TeamWeek
from .insights import Take

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5"

STYLE_GUIDE = """You write the 15-20 second spoken take that plays under one NFL team's weekly
target-share and snap-share chart, in the voice of an energetic fantasy football creator
talking straight to camera.

Voice:
- First person, casual, quick. Short sentences. Sounds spoken, not written.
- Leads with the most interesting usage story, not a recap of the score.
- Uses "Notice..." to point at something on the chart (e.g. snaps vs targets mismatch).
- Turns numbers into a fantasy call: buy-low window, sneaky pickup, riding him, can be
  ignored for now, closer than people think, wait a week.
- Willing to be blunt ("this passing offense is a mess") when the data supports it.
- Refers to players the way they appear on the chart (e.g. "T McMillan") or by last name.

Hard rules:
- Use ONLY the facts provided. Do not mention injuries, trades, coaching, contracts,
  player history, or anything not in the data. If a player had 0 snaps, say he didn't
  play; do not guess why.
- Every number you state must appear in the data. Round percentages to whole numbers.
- 45-85 words, one paragraph, no hashtags, no emojis, no headings, no bullet points.
- Output the take text only."""


def _facts(tw: TeamWeek, take: Take) -> dict:
    players = []
    for p in sorted(tw.players, key=lambda p: (-p.targets, -p.snap_pct)):
        if p.targets == 0 and p.snap_pct < 0.3:
            continue
        if p.position not in {"WR", "TE", "RB", "FB"} and p.targets == 0:
            continue
        players.append({
            "name": p.name, "pos": p.position, "targets": p.targets,
            "target_share": round(p.tgt_share * 100), "red_zone_targets": p.rz_targets,
            "drops": p.drops if tw.drops_available else None,
            "catches_yards_tds": [p.receptions, p.rec_yards, p.rec_tds],
            "snap_pct": round(p.snap_pct * 100),
            "prior_avg_target_share": None if p.prior_tgt_share is None else round(p.prior_tgt_share * 100),
            "prior_avg_snap_pct": None if p.prior_snap_pct is None else round(p.prior_snap_pct * 100),
            "prior_games": p.prior_games,
        })
    return {
        "team": tw.team_name, "week": tw.week, "season": tw.season,
        "game": f"{tw.matchup}, {tw.result} {tw.team_score}-{tw.opp_score}",
        "team_targets": tw.total_targets, "team_red_zone_targets": tw.total_rz_targets,
        "team_offensive_snaps": tw.team_snaps,
        "players": players,
        "did_not_play_regulars": [
            {"name": a.name, "pos": a.position, "prior_avg_target_share": round((a.prior_tgt_share or 0) * 100)}
            for a in tw.absent
        ],
        "signals_to_build_the_take_around": [s.evidence for s in take.signals],
        "draft_take": take.text,
    }


def narrate(tw: TeamWeek, take: Take) -> Take:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return take
    try:
        import anthropic

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=os.getenv("VOLUMETRICS_MODEL", DEFAULT_MODEL),
            max_tokens=400,
            system=STYLE_GUIDE,
            messages=[{
                "role": "user",
                "content": "Data for this team (JSON):\n" + json.dumps(_facts(tw, take), indent=1)
                           + "\n\nWrite the take. Keep the strongest 2-3 points from the signals.",
            }],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        if 20 <= len(text.split()) <= 140:
            return Take(text=text, signals=take.signals, source="claude")
        log.warning("%s: narrator returned %d words; keeping template", tw.team, len(text.split()))
    except Exception as exc:
        log.warning("%s: narrator failed (%s); keeping template", tw.team, exc)
    return take
