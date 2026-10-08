#!/usr/bin/env python3
"""
Email the weekly report link to you and your friends.

Sends ONE message from your iCloud address. You're in "To:", everyone else is BCC'd,
so friends never see each other's addresses.

Environment (set as GitHub repo secrets/variables, never in code):
  SMTP_USER       your iCloud address, e.g. you@icloud.com        (variable EMAIL_FROM)
  SMTP_PASSWORD   an iCloud app-specific password                 (secret ICLOUD_APP_PASSWORD)
  EMAIL_TO        friends' addresses, separated by commas/spaces/new lines   (secret EMAIL_TO)
  SMTP_HOST       default smtp.mail.me.com (iCloud)
  SMTP_PORT       default 587

  python send_email.py --season 2026 --week 4 --url https://.../2026/week-04/
  python send_email.py ... --dry-run     # print the email instead of sending
"""

from __future__ import annotations

import argparse
import csv
import html
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def recipients() -> list[str]:
    raw = os.getenv("EMAIL_TO", "")
    found = re.findall(r"[^\s,;<>]+@[^\s,;<>]+\.[A-Za-z]{2,}", raw)
    seen, out = set(), []
    for a in found:
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


def teaser(season: int, week: int, n: int = 3) -> list[str]:
    """Top target shares of the week (min 8 targets), straight from data.csv."""
    f = ROOT / "docs" / str(season) / f"week-{week:02d}" / "data.csv"
    if not f.exists():
        return []
    with open(f, newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if int(r["targets"]) >= 8]
    rows.sort(key=lambda r: -float(r["tgt_share"]))
    return [f"{r['label']} ({r['team']}): {float(r['tgt_share']):.0%} of targets, {r['targets']} looks"
            for r in rows[:n]]


def build(season: int, week: int, url: str, sender: str, bcc: list[str], note: str = "") -> EmailMessage:
    lines = teaser(season, week)
    msg = EmailMessage()
    msg["Subject"] = f"📊 Week {week} · Well Here's A Guy Volumetrics is up"
    msg["From"] = f"Well Here's A Guy Volumetrics <{sender}>"
    msg["To"] = sender
    if bcc:
        msg["Bcc"] = ", ".join(bcc)

    l4 = url.rstrip("/") + "/#tr"
    mv = url.rstrip("/") + "/#mv"
    rb = url.rstrip("/") + "/#rb"
    text = [f"Week {week} target share + snap % for every team is up:", url, "",
            "Trends (rolling 4 games):", l4, "",
            "Risers & fallers (waiver / trade ideas):", mv, "",
            "This week's backfields:", rb, ""]
    if lines:
        text += ["Biggest target shares this week:"] + [f"  - {x}" for x in lines] + [""]
    if note:
        text += [note, ""]
    msg.set_content("\n".join(text))

    items = "".join(f"<li style='margin:4px 0'>{html.escape(x)}</li>" for x in lines)
    msg.add_alternative(f"""\
<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:520px;margin:0 auto;color:#14171d">
  <div style="background:#03050a;background-image:linear-gradient(135deg,#0b3a44 0%,#03050a 45%,#3a0a1e 100%);
       border:1px solid #1d5c66;border-radius:12px;padding:18px 16px;text-align:center">
    <div style="color:#8ff6ff;font-size:12px;letter-spacing:.3em;font-weight:600">WELL HERE&#8217;S A GUY</div>
    <div style="color:#ffffff;font-size:30px;font-weight:800;letter-spacing:.02em;margin-top:4px">VOLUMETRICS</div>
    <div style="color:#ff9fc4;font-size:12px;letter-spacing:.2em;margin-top:6px">WEEK {week}</div></div>
  <p style="font-size:16px;line-height:1.5">Target share and snap % for every team, with a take under each one.</p>
  <p style="text-align:center;margin:20px 0">
    <a href="{html.escape(url)}" style="background:#14171d;color:#fff;text-decoration:none;padding:12px 22px;
       border-radius:8px;font-weight:600;display:inline-block">Open the Week {week} report</a></p>
  <p style="text-align:center;margin:-6px 0 18px;font-size:15px;line-height:1.8">
    <a href="{html.escape(mv)}" style="color:#14171d">Risers &amp; fallers</a> &nbsp;·&nbsp;
    <a href="{html.escape(rb)}" style="color:#14171d">Backfields</a> &nbsp;·&nbsp;
    <a href="{html.escape(l4)}" style="color:#14171d">Trends</a></p>
  {f"<p style='font-size:15px;margin-bottom:4px'><b>Biggest target shares this week</b></p><ul style='font-size:15px;padding-left:18px;margin-top:4px'>{items}</ul>" if items else ""}
  {f"<p style='font-size:14px;color:#555'>{html.escape(note)}</p>" if note else ""}
  <p style="font-size:12px;color:#888">Data: nflverse (play-by-play, PFR snap counts, FTN charting).</p>
</div>""", subtype="html")
    return msg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    sender = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    bcc = [r for r in recipients() if r.lower() != sender.lower()]
    msg = build(a.season, a.week, a.url, sender or "you@example.com", bcc, a.note)

    if a.dry_run:
        print(msg.get_body(("plain",)).get_content())
        print(f"[dry run] would send to {sender or '(no sender set)'} + {len(bcc)} BCC")
        return 0
    if not sender or not password:
        print("SMTP_USER / SMTP_PASSWORD not set; not sending.", file=sys.stderr)
        return 1

    host = os.getenv("SMTP_HOST", "smtp.mail.me.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(sender, password)
        s.send_message(msg)
    # Counts only: the repo is public, so addresses never go in the log
    print(f"Sent Week {a.week} email to you + {len(bcc)} friend(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
