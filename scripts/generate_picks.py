"""
edgr — generate today's picks.

This produces edgr's first picks table. It reads the games already stored for
a date, runs the NRFI/YRFI model + value math, keeps only the strong picks,
saves them to the `picks` table, and prints them.

HOW TO RUN (venv on, from the project's main folder):

    python -m scripts.pull_schedule      # 1) make sure games are stored first
    python -m scripts.generate_picks     # 2) then generate today's picks

    python -m scripts.generate_picks 2026-06-17   # a specific date
"""

import sys
from datetime import date, datetime

from backend.database import (
    init_db,
    get_games_for_date,
    delete_picks_for_date,
    insert_row,
)
from models.picks_engine import build_all_picks


def _read_date_argument() -> date:
    if len(sys.argv) > 1:
        try:
            return datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            print(f"⚠️  '{sys.argv[1]}' isn't a valid date. Use YYYY-MM-DD.")
            sys.exit(1)
    return date.today()


def _print_picks_table(picks: list[dict]) -> None:
    header = (
        f"{'PICK':<22}{'GAME':<26}{'ODDS':>6}{'MODEL':>7}"
        f"{'EDGE':>7}{'EV':>7}{'CONF':>6}{'RISK':>8}"
    )
    print(header)
    print("-" * len(header))
    for p in picks:
        print(
            f"{p['recommended_pick'][:21]:<22}"
            f"{p['game_label'][:25]:<26}"
            f"{int(p['odds_american']):>+6}"
            f"{p['model_probability']*100:>6.1f}%"
            f"{p['edge_pct']:>6.1f}%"
            f"{p['expected_value']:>7.3f}"
            f"{p['confidence_score']:>6.0f}"
            f"{p['risk_rating']:>8}"
        )


def main() -> None:
    game_date = _read_date_argument()
    iso = game_date.isoformat()
    season = game_date.year

    init_db()
    games = get_games_for_date(iso)
    if not games:
        print(f"No games stored for {iso}. Run:  python -m scripts.pull_schedule {iso}")
        return

    print(f"Analyzing {len(games)} games for {iso} across all markets...\n")
    picks = build_all_picks(games, season)
    using_sample = any(p["sportsbook"] == "sample" for p in picks)

    # Replace any earlier picks for this date, then save the fresh ones.
    delete_picks_for_date(iso)
    for pick in picks:
        insert_row("picks", pick)

    if not picks:
        print("No picks cleared edgr's strict rules today. That's normal —")
        print("edgr only surfaces picks that meet every confidence/EV requirement.")
        return

    if using_sample:
        print("🟡 SAMPLE-ODDS MODE: no live odds connected, so the EDGE/EV/CONF")
        print("   numbers below are ILLUSTRATIVE ONLY (real edges are ~1-8%).")
        print("   Add a free Odds API key to .env for real picks.\n")

    print(f"⭐ TODAY'S HIGHEST-CONFIDENCE PICKS — {len(picks)} across all markets\n")
    _print_picks_table(picks)
    print(
        "\nColumns: MODEL = model win %, EDGE = model minus implied,"
        "\nEV = expected profit per 1 unit, CONF = confidence (0-100)."
    )
    print("\n⚠️  Analytics only, not betting advice. Confidence = model confidence,"
          " not certainty.")


if __name__ == "__main__":
    main()
