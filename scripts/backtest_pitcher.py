"""
edgr — season backtest of the REAL pitcher-based model (walk-forward, leak-free).

Unlike scripts/backtest.py (a team-level proxy), this replicates edgr's live
run model: each starter's ERA *as of that game date* (blended toward league
for small samples) plus each team's offense to date. No future data is used.

It makes one game-log request per starting pitcher (free MLB API), so it is
slower than the proxy backtest but faithful to what edgr actually predicts.

RUN:  python -m scripts.backtest_pitcher
      python -m scripts.backtest_pitcher 2026-03-01 2026-06-17
"""

import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests
from scipy.stats import skellam

from config.settings import (
    LEAGUE_RUNS_PER_GAME, LEAGUE_AVG_ERA, STARTER_WEIGHT_FULLGAME,
    HOME_FIELD_EDGE, PITCHER_TRUST_INNINGS,
)
from backend.stats import _innings_to_float
from scripts.backtest import _report

BASE = "https://statsapi.mlb.com/api/v1"
MIN_GAMES = 10

_logs: dict = {}   # pitcher_id -> sorted list of (date_str, earned_runs, innings)


def fetch_games(start: date, end: date) -> list[dict]:
    """Final games in range, with each team's probable starting pitcher id."""
    games, cur = [], start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=27), end)
        params = {"sportId": 1, "startDate": cur.isoformat(),
                  "endDate": chunk_end.isoformat(), "hydrate": "probablePitcher,team"}
        data = requests.get(f"{BASE}/schedule", params=params, timeout=30).json()
        for day in data.get("dates", []):
            for g in day.get("games", []):
                if g.get("status", {}).get("detailedState") != "Final":
                    continue
                home, away = g["teams"]["home"], g["teams"]["away"]
                if home.get("score") is None or away.get("score") is None:
                    continue
                games.append({
                    "date": day["date"],
                    "home": home["team"]["name"], "away": away["team"]["name"],
                    "hs": home["score"], "as": away["score"],
                    "home_pid": home.get("probablePitcher", {}).get("id"),
                    "away_pid": away.get("probablePitcher", {}).get("id"),
                })
        cur = chunk_end + timedelta(days=1)
    games.sort(key=lambda x: x["date"])
    return games


def _load_log(pid: int) -> list:
    if pid in _logs:
        return _logs[pid]
    out = []
    try:
        data = requests.get(f"{BASE}/people/{pid}/stats",
                            params={"stats": "gameLog", "group": "pitching",
                                    "season": 2026}, timeout=30).json()
        for sp in data["stats"][0]["splits"]:
            st = sp["stat"]
            out.append((sp["date"], float(st.get("earnedRuns", 0) or 0),
                        _innings_to_float(st.get("inningsPitched", "0"))))
    except (requests.RequestException, KeyError, IndexError, ValueError):
        out = []
    out.sort()
    _logs[pid] = out
    return out


def _pitcher_rate(pid, game_date: str) -> float:
    """Runs-per-inning rate from a pitcher's ERA strictly BEFORE game_date."""
    league_pitch = LEAGUE_AVG_ERA / 9.0
    if not pid:
        return league_pitch
    er = ip = 0.0
    for d, e, i in _load_log(pid):
        if d < game_date:
            er += e; ip += i
    if ip <= 0:
        return league_pitch
    era = er / ip * 9
    weight = min(1.0, ip / PITCHER_TRUST_INNINGS)
    blended = weight * era + (1 - weight) * LEAGUE_AVG_ERA
    return blended / 9.0


def collect_predictions(games: list[dict]) -> tuple[list[dict], float]:
    """Walk forward through the season, returning one prediction per game.

    Each record: {p_home, home_won, proj_total, actual_total}. No leakage —
    every prediction uses only games (and pitcher logs) from before that date.
    """
    pids = {g["home_pid"] for g in games} | {g["away_pid"] for g in games}
    pids.discard(None)
    print(f"Loading game logs for {len(pids)} starting pitchers...")
    for n, pid in enumerate(pids, 1):
        _load_log(pid)
        if n % 75 == 0:
            print(f"   {n}/{len(pids)}")

    total_runs = sum(g["hs"] + g["as"] for g in games)
    league_pg = total_runs / (2 * len(games)) if games else 4.4
    league_rate = LEAGUE_RUNS_PER_GAME / 9.0
    league_pitch = LEAGUE_AVG_ERA / 9.0

    rs, gp = defaultdict(float), defaultdict(int)
    preds: list[dict] = []

    for g in games:
        h, a, hs, as_, gd = g["home"], g["away"], g["hs"], g["as"], g["date"]
        if gp[h] >= MIN_GAMES and gp[a] >= MIN_GAMES:
            home_off = (rs[h] / gp[h]) / 9.0
            away_off = (rs[a] / gp[a]) / 9.0
            home_pitch = STARTER_WEIGHT_FULLGAME * _pitcher_rate(g["home_pid"], gd) + (1 - STARTER_WEIGHT_FULLGAME) * league_pitch
            away_pitch = STARTER_WEIGHT_FULLGAME * _pitcher_rate(g["away_pid"], gd) + (1 - STARTER_WEIGHT_FULLGAME) * league_pitch
            exp_h = max(0.2, home_off * away_pitch / league_rate * 9)
            exp_a = max(0.2, away_off * home_pitch / league_rate * 9)
            p_home = min(0.97, 1 - skellam.cdf(0, exp_h, exp_a)
                         + 0.5 * skellam.pmf(0, exp_h, exp_a) + HOME_FIELD_EDGE)
            # Run-line probabilities (home covers -1.5 / +1.5) for calibration.
            q_minus = float(1 - skellam.cdf(1, exp_h, exp_a))   # margin >= 2
            q_plus = float(1 - skellam.cdf(-2, exp_h, exp_a))   # margin >= -1
            preds.append({"p_home": p_home, "home_won": hs > as_,
                          "proj_total": exp_h + exp_a, "actual_total": hs + as_,
                          "q_minus": q_minus, "q_plus": q_plus,
                          "home_margin": hs - as_})
        rs[h] += hs; gp[h] += 1
        rs[a] += as_; gp[a] += 1

    return preds, league_pg


def run_backtest(games: list[dict]) -> None:
    preds, league_pg = collect_predictions(games)

    ml_buckets = defaultdict(lambda: [0, 0])
    proj_tot, act_tot = [], []
    pick_w = pick_l = 0
    for p in preds:
        b = round(p["p_home"] * 10) / 10
        ml_buckets[b][0] += int(p["home_won"])
        ml_buckets[b][1] += 1
        if max(p["p_home"], 1 - p["p_home"]) >= 0.55:
            if (p["p_home"] >= 0.5) == p["home_won"]:
                pick_w += 1
            else:
                pick_l += 1
        proj_tot.append(p["proj_total"])
        act_tot.append(p["actual_total"])

    print("\n*** REAL pitcher-based model ***")
    _report(games, len(preds), league_pg, ml_buckets, proj_tot, act_tot, pick_w, pick_l)


def main() -> None:
    if len(sys.argv) > 2:
        start = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        end = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
    else:
        start = date(date.today().year, 3, 1)
        end = date.today() - timedelta(days=1)

    print(f"Fetching games {start} → {end}...")
    games = fetch_games(start, end)
    if not games:
        print("No completed games found.")
        return
    run_backtest(games)


if __name__ == "__main__":
    main()
