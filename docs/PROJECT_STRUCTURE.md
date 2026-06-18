# edgr — Project Structure

edgr is an AI-powered sports betting **analytics** tool. Each day it pulls MLB data,
compares model projections against sportsbook odds, and surfaces the highest-confidence
picks that clear strict confidence and expected-value rules.

> ⚠️ This is an analytics tool, **not** guaranteed betting advice. "Confidence" means
> *model confidence*, not certainty. Please gamble responsibly.

## Folder map

| Folder        | What lives here | Plain-English purpose |
|---------------|-----------------|-----------------------|
| `backend/`    | Data pulling + database code | The "engine room." Talks to APIs (MLB, odds, weather), saves data into the database, and reads it back out. |
| `app/`        | The Streamlit dashboard | What *you* see. The "Today's Highest Confidence Picks" screen, filters, charts, team/player pages. |
| `data/`       | Saved data files | `raw/` = untouched downloads. `processed/` = cleaned data + the SQLite database file. |
| `models/`     | Machine-learning models | The "brains." Code that learns from history and predicts game/player outcomes. Trained model files are saved here too. |
| `scripts/`    | One-command tasks | Things you *run*, e.g. "pull today's data," "generate today's picks," "run a backtest." |
| `config/`     | Settings | Knobs and dials: confidence threshold, unit size, which markets are on, API settings. No secrets here. |
| `tests/`      | Automated checks | Small programs that confirm the code still works after changes. |
| `docs/`       | Documentation | Notes, guides, and this file. |

## Files that will live in the project root (added in later steps)

- `requirements.txt` — the list of Python packages edgr needs.
- `.env.example` — a template showing which secret keys (like your Odds API key) to set.
- `.env` — your *actual* secret keys (never shared, never committed).
- `README.md` — the front-door guide to running edgr.
- `.gitignore` — tells git which files to ignore (secrets, data dumps, etc.).

## How the pieces talk to each other (the daily flow)

```
  scripts/  ──run──▶  backend/  ──fetch──▶  MLB API · Odds API · Weather
     │                   │
     │                   ▼
     │              data/ (SQLite)
     │                   │
     ▼                   ▼
  models/  ──predict──▶  picks  ──show──▶  app/ (Streamlit dashboard)
```

1. You run a script in `scripts/`.
2. `backend/` fetches fresh data and stores it in `data/`.
3. `models/` reads that data and makes predictions.
4. edgr compares predictions vs. sportsbook odds, scores each pick, keeps only the strong ones.
5. `app/` displays them on the dashboard.
