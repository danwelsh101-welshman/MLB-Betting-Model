"""
edgr — MLB Stats API client (the part that fetches real baseball data).

The MLB Stats API is FREE and needs no key. We use it for the schedule,
teams, probable pitchers, venues, and final scores.

Base URL: https://statsapi.mlb.com/api/v1

For a beginner:
- An "API" is a website meant for programs (not people) to read.
- We send a web request and get back data as JSON (nested lists/dictionaries).
- `requests` is the library that sends the request; `.json()` turns the
  reply into Python dictionaries we can pick values out of.
"""

from datetime import date
import requests

# The schedule endpoint. "hydrate" asks MLB to also include extra details
# (the probable pitcher and venue) in the same reply, so we don't have to
# make additional requests.
SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"

# A short timeout so the program never hangs forever waiting on the network.
TIMEOUT_SECONDS = 20


def fetch_schedule(game_date: date | None = None) -> list[dict]:
    """Get the MLB schedule for one day as a clean list of game dictionaries.

    `game_date` defaults to today. Each item in the returned list has the
    handful of fields edgr cares about, already pulled out of MLB's deeply
    nested response.
    """
    if game_date is None:
        game_date = date.today()

    params = {
        "sportId": 1,                       # 1 = Major League Baseball
        "date": game_date.isoformat(),      # "2026-06-17"
        "hydrate": "probablePitcher,team",  # include pitchers + team info
    }

    response = requests.get(SCHEDULE_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()             # raise an error on a bad reply
    payload = response.json()

    return _parse_schedule(payload, game_date)


def _parse_schedule(payload: dict, game_date: date) -> list[dict]:
    """Turn MLB's nested response into a simple list of game dictionaries.

    The leading underscore is a Python convention meaning "internal helper —
    not really meant to be called from outside this file."
    """
    games: list[dict] = []

    # MLB groups games under "dates" (usually just one date for our request).
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            home = game["teams"]["home"]
            away = game["teams"]["away"]

            games.append({
                "game_id": game["gamePk"],
                "date": game_date.isoformat(),
                "game_time": game.get("gameDate"),   # UTC ISO, e.g. 2026-06-17T23:05:00Z
                "season": int(game.get("season", game_date.year)),
                "home_team": home["team"].get("name", "Unknown"),
                "away_team": away["team"].get("name", "Unknown"),
                # Team + pitcher IDs let us look up each side's stats later.
                "home_team_id": home["team"].get("id"),
                "away_team_id": away["team"].get("id"),
                "home_pitcher": _probable_pitcher_name(home),
                "away_pitcher": _probable_pitcher_name(away),
                "home_pitcher_id": _probable_pitcher_id(home),
                "away_pitcher_id": _probable_pitcher_id(away),
                "venue": game.get("venue", {}).get("name"),
                "game_status": game.get("status", {}).get("detailedState"),
                # Scores exist only after the game starts/finishes; default None.
                "home_score": home.get("score"),
                "away_score": away.get("score"),
            })

    return games


def _probable_pitcher_name(team_side: dict) -> str | None:
    """Safely dig out the probable pitcher's name (may not be announced yet)."""
    pitcher = team_side.get("probablePitcher")
    if pitcher:
        return pitcher.get("fullName")
    return None


def _probable_pitcher_id(team_side: dict) -> int | None:
    """Safely dig out the probable pitcher's MLB id (may not be announced yet)."""
    pitcher = team_side.get("probablePitcher")
    if pitcher:
        return pitcher.get("id")
    return None
