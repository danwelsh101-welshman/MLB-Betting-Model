"""
edgr — pull the MLB schedule into the database.

This is edgr's first real data pull. It asks the MLB Stats API for a day's
games and saves them into the `games` table.

HOW TO RUN (venv on, from the project's main folder):

    python -m scripts.pull_schedule              # today's games
    python -m scripts.pull_schedule 2026-06-17   # a specific date (YYYY-MM-DD)
"""

import sys
from datetime import date, datetime

from backend.database import init_db, upsert_row, count_rows
from backend.mlb_api import fetch_schedule


def _read_date_argument() -> date:
    """Use a date typed on the command line, or default to today."""
    if len(sys.argv) > 1:
        try:
            return datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            print(f"⚠️  '{sys.argv[1]}' isn't a valid date. Use YYYY-MM-DD.")
            sys.exit(1)
    return date.today()


def main() -> None:
    game_date = _read_date_argument()
    print(f"Pulling MLB schedule for {game_date}...")

    init_db()  # make sure the tables exist before we write to them

    games = fetch_schedule(game_date)

    if not games:
        print("No games found for that date (off-day, or schedule not posted yet).")
        return

    for game in games:
        upsert_row("games", game)

    print(f"\n✅ Saved {len(games)} games to the database.\n")
    print(f"{'AWAY':<24}{'@':^3}{'HOME':<24}{'STATUS'}")
    print("-" * 70)
    for g in games:
        matchup_status = g["game_status"] or ""
        print(f"{g['away_team']:<24}{'@':^3}{g['home_team']:<24}{matchup_status}")

    # Show probable pitchers separately (cleaner than cramming into one line).
    print("\nProbable pitchers:")
    for g in games:
        away_p = g["away_pitcher"] or "TBD"
        home_p = g["home_pitcher"] or "TBD"
        print(f"   {g['away_team']} ({away_p})  @  {g['home_team']} ({home_p})")

    print(f"\nTotal games now stored in the database: {count_rows('games')}")


if __name__ == "__main__":
    main()
