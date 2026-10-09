# Well Here's A Guy Volumetrics

Weekly NFL usage cards: a **target-share donut** and a **snap % bar chart** for every team,
with a short spoken-style **take** underneath each one. Runs itself every Tuesday on GitHub
Actions and publishes to GitHub Pages.

![example card](docs/2026/week-04/img/CAR-m.png)

## How it runs

Every **Tuesday 15:00 UTC** (8am Pacific in season), after Monday Night Football, GitHub Actions:

1. pulls the latest completed week from nflverse and builds every team's card (headshots included),
2. commits the report to `docs/` and publishes it to GitHub Pages,
3. emails the link to you and your friends from your iCloud address (friends are BCC'd).
   If email isn't set up yet, it opens an issue that @mentions you instead, which GitHub emails to you.

A **Wednesday** run fills in any team whose snap counts posted late, and does nothing if Tuesday
already got everything. Run it any time from **Actions → Weekly Volumetrics → Run workflow**
(leave the boxes blank for the latest week, or fill in a season/week to backfill).

Optional settings (**Settings → Secrets and variables → Actions**):
- Secret `ANTHROPIC_API_KEY`: turns on the Claude voice pass for the takes.
- Variable `VOLUMETRICS_BRAND`: the text in the top-right corner of every chart (default `VOLUMETRICS`).

**Email list** (same settings page):
- Variable `EMAIL_FROM`: your iCloud address (the sender, and you always get a copy).
- Secret `ICLOUD_APP_PASSWORD`: make one at account.apple.com → Sign-In and Security → App-Specific Passwords.
- Secret `EMAIL_TO`: friends' addresses separated by commas. Edit this secret any time to add or remove people.
  It's a secret (not a variable) because the repo is public; the log only ever shows a head count.

## Run it locally

```bash
pip install -r requirements.txt
python run_weekly.py                         # latest completed week
python run_weekly.py --season 2026 --week 4  # a specific week
python run_weekly.py --teams CAR DAL --embed # a few teams + one self-contained HTML file
```

## What's in each weekly folder (`docs/<season>/week-NN/`)

| File | What it is |
|---|---|
| `index.html` | top target shares, then every team: chart, the take, and "Why this take" with the numbers |
| `img/<TEAM>-m.webp`, `img/<TEAM>.webp` | phone card (1080×1920) and wide card (1920×1080); tap a card to open it full size |
| `img/l4/...` | the same two cards for the "Last 4" tab |
| `data_l4.csv` | every number in the Last 4 tab, one row per player |
| `report-standalone.html` | same page with images inlined, one file you can text or email |
| `data.csv` | every number used, one row per player |
| `takes.json` | each take plus the signals and evidence that produced it |
| `manifest.json` | which teams were built, which were missing, when it ran |

## The four tabs

1. **Week N Targets**: target-share donut + snap % bars for every team, with the take underneath.
2. **Week N Backfield**: the top 8 rushers of the week, four league-wide charts, then every team's backfield
   (carry-share donut + snap / rush / target bars per back) with an RB take.
3. **Trends (rolling 4)**: each team's last 4 games played, byes skipped, so the oldest game drops off weekly.
   A switch flips between **Targets** (rolling donut + bars + target share by week) and **Backfield** (top 8
   rushers over the span, the same four league charts, each team's rolling backfield + rush share by week).
   **O-line injury notes** sit at the bottom: starting linemen who missed time, the injury from the official
   report, and how they're practicing for the next game.
4. **Risers & Fallers (buy / sell)**: biggest usage moves over the window, tagged Waiver add / Buy / Buy low /
   Sell / Watch, filterable by RB / WR / TE.

### League-wide backfield charts (Week N Backfield and Trends → Backfield)

| Chart | X | Y | What it shows |
|---|---|---|---|
| Efficiency vs. volume | RB carries per game | EPA per rush | efficient workhorses vs. teams forcing the run |
| Rushing vs. receiving | rush success rate | RB share of team targets | which backfields help in both phases |
| Blocked vs. created | yards before contact / carry | + yards after contact / carry | the line's work vs. the back's (PFR) |
| Who owns the backfield | each back's share of RB carries + targets | | workhorse vs. committee, plus RB1's carries inside the 5 |

Team logos are the dots; quadrant lines sit at the league median.

## Risers & Fallers: evidence, not just usage (`volumetrics/evidence.py`)

Every move is checked against the stats that confirm a real role change, comparing the first and
second half of each team's window, and graded **Strong / Solid / Thin**. Only Strong or Solid moves
get Waiver add / Buy / Sell; thin or mixed ones are tagged Watch. Each card lists the stats behind it.

- **WR / TE:** snap share, air yards share (deeper looks, counted only when it outpaces target share),
  end-zone targets, targets per route and yards per route (est.). WOPR is shown but not counted, since
  it moves with target share.
- **RB:** snap share, goal-line and red-zone carry share, targets per game, yards after contact and
  broken tackles (PFR), expected points per game.
- **Routes are estimated** (snap share x team dropbacks): route participation isn't public for 2026.

## Send a week to someone new (without re-sending to everyone)

1. Settings → Secrets and variables → Actions → New repository secret `EMAIL_NEW` with just the new
   people's addresses (commas between them).
2. Actions → Weekly Volumetrics → Run workflow: Week = the week to send, Send the email = on,
   Who gets the email = "only the people in EMAIL_NEW". Each new person gets their own copy and you get
   one too; nobody else gets it again. ("just me" sends it only to you, handy for checking.)
3. Add them to `EMAIL_TO` so they're on the list every Tuesday, and clear `EMAIL_NEW`.

## Your ESPN league

Add three repo secrets: `ESPN_LEAGUE_ID` (the number after `leagueId=` in your league's URL), and for a
private league the `espn_s2` and `SWID` cookies from a logged-in desktop browser (DevTools → Application →
Cookies → espn.com). Risers & Fallers then marks every player Available / Your team / Rostered, adds
Available and My team filters, and makes the tags actionable: a backed riser is a Waiver add only if he's
available, a Trade target if he's on someone else's roster, a Hold if he's yours. The cookies expire about
once a year; if the league layer disappears, copy fresh ones. Only availability shows on the site; other
teams' names and rosters are never published.

## Add it to your home screen

The site ships a web-app manifest and icons, so "Add to Home Screen" on iPhone (Share menu) or
Android opens it full-screen like an app.

## How the numbers are defined (`volumetrics/data.py`)

- **Target**: pass play with a named receiver, no two-point tries, no plays wiped out by penalty.
  Matches nflverse's official `targets` for all 32 teams in Week 4, 2026.
- **Red-zone target**: thrown from inside the opponent's 20.
- **Drop**: FTN charting via nflverse (CC-BY-SA 4.0). Shown only when FTN has posted the week.
- **Snap %**: offensive snaps / team offensive snaps, from Pro Football Reference via nflverse.
- **Prior share**: average weekly target share in earlier weeks this season, for weeks he played.

## How the takes are written (`volumetrics/insights.py`)

Rules first, then wording. Each rule has its threshold at the top of `insights.py`:

| Signal | Fires when |
|---|---|
| Alpha 40 | top WR/TE gets ≥ 40% of targets ("monster game" check uses his yards/TDs) |
| Alpha | top guy ≥ 28% and nobody close |
| Closer than you think | top two both ≥ 19% and within 4 points |
| Didn't play → beneficiary | a regular (≥ 15% prior share) took 0 offensive snaps; finds who gained the most targets, or the most snaps |
| Riser / faller | ± 10 points vs prior average (2+ prior games); faller on steady snaps = buy-low |
| Part-timer earning looks | ≤ 60% snaps but ≥ 17% share |
| Snaps, no looks | WR/TE ≥ 80% snaps but ≤ 9% share |
| Red-zone role | ≥ 2 RZ targets and ≥ 40% of the team's |
| Spread / mess / rotation | top share < 25% with 4+ players ≥ 10%; no WR ≥ 75% snaps |
| RB / TE role, drops, volume | RB ≥ 15%, TE ≥ 20%, 2+ drops, ≥ 45 or ≤ 22 team targets |

The strongest three (one per player, one per type) become the take. With `ANTHROPIC_API_KEY` set,
`volumetrics/narrator.py` asks Claude to rewrite that take in the creator's spoken style using
**only** that team's numbers; if the call fails, the rule-based take is kept.
Model: `claude-sonnet-5-5` (override with `VOLUMETRICS_MODEL`).

## Tweaking the look (`volumetrics/charts.py`)

Colors come from each team's official palette (lifted so dark navies and browns read on the
dark card), and every player keeps one color across both plots. Players under 5% or with a
single target are pooled into "Other (n)". Wedge labels shrink, then turn to run along the
radius, until they fit inside their slice. Font: Jost (SIL OFL, `assets/fonts`).

Data: nflverse (play-by-play, PFR snap counts, FTN charting, rosters, schedules).
