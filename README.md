# edgr ⚾📈

**edgr** is an AI-powered MLB betting *analytics* tool. Open it each day and instantly
see the highest-confidence picks across many MLB markets — ranked by confidence,
expected value, and model edge.

> ⚠️ **edgr is an analytics tool, not guaranteed betting advice.** No pick is a "lock"
> or "guaranteed." A confidence score reflects *model confidence*, not certainty.
> Bet only what you can afford to lose. If gambling stops being fun, get help:
> call/text **1-800-GAMBLER**.

---

## What it does

Every day, edgr:
1. Pulls MLB data (schedules, pitchers, stats, weather).
2. Pulls current sportsbook odds.
3. Runs models to project outcomes.
4. Compares projections vs. odds to find **edges** and **expected value (EV)**.
5. Keeps only picks that clear strict rules (70%+ confidence, positive EV, good data).
6. Shows the best picks on a clean dashboard.

### Markets covered (the goal)
Moneyline · Run line · Game totals · Team totals · First-5 moneyline · First-5 totals ·
NRFI/YRFI · Pitcher strikeouts / hits / earned runs · Batter hits / total bases /
home runs / RBI / runs · Stolen bases (if data allows).

---

## Getting started (quick version)

```bash
# 1. Create an isolated environment (one time)
python3.14 -m venv .venv

# 2. Turn it on (do this every time you work on edgr)
source .venv/bin/activate

# 3. Install the packages (one time)
pip install -r requirements.txt

# 4. Add your secret keys
cp .env.example .env      # then edit .env and paste your Odds API key
```

We'll add the "run the app" commands in later steps as they're built.

---

## Project layout
See [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) for a full tour of every folder.

| Folder | Purpose |
|---|---|
| `backend/` | Data pulling + database |
| `app/` | Streamlit dashboard |
| `data/` | Saved data + SQLite database |
| `models/` | Machine-learning models |
| `scripts/` | One-command tasks |
| `config/` | Settings (thresholds, units) |
| `tests/` | Automated checks |
| `docs/` | Documentation |

---

## Data sources
- **MLB Stats API** — schedules, teams, players, probable pitchers, box scores, results (free, no key)
- **PyBaseball** — historical batting/pitching/Statcast data (free)
- **The Odds API** — sportsbook odds (free tier, needs a key)
- **Open-Meteo** — weather & wind for outdoor parks (free, no key)

## Tech
Python 3.14 · pandas · scikit-learn · Streamlit · SQLite (upgradeable to PostgreSQL)

