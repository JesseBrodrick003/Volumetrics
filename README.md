# Volumetrics

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

## The "Last 4" tab

Each team's **four most recent games played** (bye weeks skipped), added together, so every week the
oldest game drops off and the newest comes in. Shares are totals over those games (a player's targets ÷
the team's targets across all four), so a game he missed counts as zero. Under each card, a small table
shows the top five receivers' target share game by game, shaded by size, so you can see who's rising
or fading. The takes there look for trends: who's owned the role every week, whose share is climbing or
slipping between the first and last two games, snap shares growing, and who's getting the red-zone looks.
Change the window with `--window` (e.g. `--window 3`).

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
