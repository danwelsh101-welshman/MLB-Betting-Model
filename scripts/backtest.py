"""
edgr — season backtest (walk-forward, leak-free, free data only).

WHAT THIS DOES
For every completed game this season, it predicts the result using ONLY the
games that happened before it (no peeking at the future), then checks the
prediction against what actually happened. It reports:

  - Moneyline calibration: when the model says "65% to win", do those teams
    really win ~65% of the time?
  - Pick win rate: if you backed the model's favored side, how often right?
  - Totals bias: does the model's projected run total run high or low vs.
    what actually scored? (This is what reveals the "30% Unders" problem.)

HONEST SCOPE
- Free + leak-free: team run rates are built from final scores only.
- It tests a TEAM-LEVEL proxy of edgr's run model (it does not use each
  starting pitcher's point-in-time ERA — that needs many more calls and is a
  heavier follow-up).
- No sportsbook ROI here: real ROI needs paid historical odds. This measures
  whether the MODEL is accurate, which is the foundation.

RUN:  python -m scripts.backtest
      python -m scripts.backtest 2026-03-01 2026-06-17
"""

import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests
from scipy.stats import skellam

from config.settings import HOME_FIELD_EDGE

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MIN_GAMES = 10           # warm-up: need this many prior games before predicting
CONF_THRESHOLD = 0.55    # only count "confident" model sides in the pick record


def fetch_final_games(start: date, end: date) -> list[dict]:
    """Fetch every FINAL game in a date range (chunked to be gentle)."""
    games, cur = [], start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=27), end)
        params = {"sportId": 1, "startDate": cur.isoformat(),
                  "endDate": chunk_end.isoformat(), "hydrate": "team"}
        data = requests.get(SCHEDULE_URL, params=params, timeout=30).json()
        for day in data.get("dates", []):
            for g in day.get("games", []):
                if g.get("status", {}).get("detailedState") != "Final":
                    continue
                home, away = g["teams"]["home"], g["teams"]["away"]
                hs, as_ = home.get("score"), away.get("score")
                if hs is None or as_ is None:
                    continue
                games.append({"date": day["date"], "home": home["team"]["name"],
                              "away": away["team"]["name"], "hs": hs, "as": as_})
        cur = chunk_end + timedelta(days=1)
    games.sort(key=lambda x: x["date"])
    return games


def run_backtest(games: list[dict]) -> None:
    # League average runs per game per team (a constant, computed from the season).
    total_runs = sum(g["hs"] + g["as"] for g in games)
    league_pg = total_runs / (2 * len(games)) if games else 4.4

    rs, ra, gp = defaultdict(float), defaultdict(float), defaultdict(int)
    ml_buckets = defaultdict(lambda: [0, 0])   # bucket -> [home wins, games]
    proj_tot, act_tot = [], []
    pick_w = pick_l = 0
    predicted = 0

    for g in games:
        h, a, hs, as_ = g["home"], g["away"], g["hs"], g["as"]

        if gp[h] >= MIN_GAMES and gp[a] >= MIN_GAMES:
            predicted += 1
            h_off, h_def = rs[h] / gp[h], ra[h] / gp[h]
            a_off, a_def = rs[a] / gp[a], ra[a] / gp[a]
            # Expected runs = offense * opponent defense / league average.
            exp_h = h_off * a_def / league_pg
            exp_a = a_off * h_def / league_pg

            # Moneyline win probability (Skellam) + small home-field edge.
            p_home = (1 - skellam.cdf(0, exp_h, exp_a)
                      + 0.5 * skellam.pmf(0, exp_h, exp_a))
            p_home = min(0.97, p_home + HOME_FIELD_EDGE)
            home_won = hs > as_

            bucket = round(p_home * 10) / 10
            ml_buckets[bucket][0] += int(home_won)
            ml_buckets[bucket][1] += 1

            # Model's favored side, counted only when reasonably confident.
            conf = max(p_home, 1 - p_home)
            if conf >= CONF_THRESHOLD:
                fav_home = p_home >= 0.5
                if fav_home == home_won:
                    pick_w += 1
                else:
                    pick_l += 1

            proj_tot.append(exp_h + exp_a)
            act_tot.append(hs + as_)

        # Update running totals AFTER predicting (walk-forward, no leakage).
        rs[h] += hs; ra[h] += as_; gp[h] += 1
        rs[a] += as_; ra[a] += hs; gp[a] += 1

    _report(games, predicted, league_pg, ml_buckets, proj_tot, act_tot, pick_w, pick_l)


def _report(games, predicted, league_pg, ml_buckets, proj_tot, act_tot, pick_w, pick_l):
    print(f"\n📊 edgr season backtest — {len(games)} final games "
          f"({predicted} predicted after warm-up)\n")
    print(f"League avg runs/game/team: {league_pg:.2f}\n")

    # --- Moneyline pick record ---
    decided = pick_w + pick_l
    if decided:
        print("MONEYLINE — backing the model's favored side (>= 55% conf):")
        print(f"   Record: {pick_w}-{pick_l}  |  Win rate: {pick_w/decided*100:.1f}%")
        print("   (Break-even vs a -110 line is ~52.4%.)\n")

    # --- Calibration table ---
    print("CALIBRATION — does the model's % match reality? (home-win buckets)")
    print(f"   {'Predicted':<12}{'Games':<8}{'Actual home win%'}")
    for b in sorted(ml_buckets):
        wins, n = ml_buckets[b]
        if n >= 20:
            print(f"   {b*100:>4.0f}%       {n:<8}{wins/n*100:>6.1f}%")
    print()

    # --- Totals bias ---
    if proj_tot:
        mp = sum(proj_tot) / len(proj_tot)
        ma = sum(act_tot) / len(act_tot)
        over_actual = sum(1 for p, a in zip(proj_tot, act_tot) if a > p)
        print("TOTALS — is the run projection biased?")
        print(f"   Avg projected total: {mp:.2f} runs")
        print(f"   Avg actual total:    {ma:.2f} runs")
        print(f"   Model {'UNDER-shoots' if mp < ma else 'OVER-shoots'} reality "
              f"by {abs(mp-ma):.2f} runs/game")
        print(f"   Actual went OVER the projection {over_actual/len(proj_tot)*100:.1f}% "
              f"of the time (50% = unbiased)\n")


def main() -> None:
    if len(sys.argv) > 2:
        start = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        end = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
    else:
        start = date(date.today().year, 3, 1)
        end = date.today() - timedelta(days=1)

    print(f"Fetching final games {start} → {end} (free MLB data)...")
    games = fetch_final_games(start, end)
    if not games:
        print("No completed games found in that range.")
        return
    run_backtest(games)


if __name__ == "__main__":
    main()
