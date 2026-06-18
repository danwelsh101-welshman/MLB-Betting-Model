"""
edgr — season-stat lookups from the MLB Stats API.

We use this to feed the models: a starting pitcher's ERA (runs allowed per 9
innings) and a team's runs scored per game. Both come from the free MLB Stats
API, which is fast and reliable.

Two beginner-friendly touches:
- A simple in-memory cache (a dictionary) so we don't ask MLB for the same
  pitcher twice in one run.
- Safe fallbacks: if a stat is missing (e.g. a rookie with no record yet),
  we return None and let the model fall back to a league-average assumption.
"""

import requests

BASE = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 20

# Caches: {(id, season): value}.  Cleared every time the program restarts.
_pitcher_cache: dict = {}
_team_cache: dict = {}
_hand_cache: dict = {}


def get_pitcher_hand(pitcher_id) -> str:
    """Return a pitcher's throwing hand as 'L' or 'R' (or '' if unknown)."""
    if pitcher_id is None:
        return ""
    if pitcher_id in _hand_cache:
        return _hand_cache[pitcher_id]
    try:
        data = requests.get(f"{BASE}/people/{pitcher_id}", timeout=TIMEOUT).json()
        hand = data["people"][0].get("pitchHand", {}).get("code", "")
    except (requests.RequestException, KeyError, IndexError, ValueError):
        hand = ""
    _hand_cache[pitcher_id] = hand
    return hand


def get_pitcher_stats(pitcher_id: int, season: int) -> dict | None:
    """Return {'era': float, 'innings': float} for a pitcher, or None.

    `era` = earned runs allowed per 9 innings (lower is better).
    `innings` = innings pitched this season (used to judge sample size).
    """
    if pitcher_id is None:
        return None
    key = (pitcher_id, season)
    if key in _pitcher_cache:
        return _pitcher_cache[key]

    url = f"{BASE}/people/{pitcher_id}/stats"
    params = {"stats": "season", "group": "pitching", "season": season}
    try:
        data = requests.get(url, params=params, timeout=TIMEOUT).json()
        splits = data["stats"][0]["splits"]
        if not splits:
            _pitcher_cache[key] = None
            return None
        stat = splits[0]["stat"]
        innings = _innings_to_float(stat.get("inningsPitched", "0"))
        games_started = float(stat.get("gamesStarted", 0) or 0)
        strikeouts = float(stat.get("strikeOuts", 0) or 0)
        result = {
            "era": float(stat.get("era", 0) or 0),
            "innings": innings,
            "games_started": games_started,
            "strikeouts": strikeouts,
            # Strikeouts per 9 innings (the standard "K/9" stat).
            "k_per_9": (strikeouts / innings * 9) if innings > 0 else 0.0,
            # Average innings the pitcher throws per start.
            "ip_per_start": (innings / games_started) if games_started > 0 else 0.0,
        }
    except (requests.RequestException, KeyError, IndexError, ValueError):
        result = None

    _pitcher_cache[key] = result
    return result


def get_team_runs_per_game(team_id: int, season: int) -> float | None:
    """Return a team's runs scored per game this season, or None."""
    if team_id is None:
        return None
    key = (team_id, season)
    if key in _team_cache:
        return _team_cache[key]

    url = f"{BASE}/teams/{team_id}/stats"
    params = {"stats": "season", "group": "hitting", "season": season}
    try:
        data = requests.get(url, params=params, timeout=TIMEOUT).json()
        stat = data["stats"][0]["splits"][0]["stat"]
        runs = float(stat.get("runs", 0) or 0)
        games = float(stat.get("gamesPlayed", 0) or 0)
        result = runs / games if games > 0 else None
    except (requests.RequestException, KeyError, IndexError, ValueError, ZeroDivisionError):
        result = None

    _team_cache[key] = result
    return result


def _innings_to_float(innings_pitched: str) -> float:
    """MLB writes innings like '195.1' meaning 195 and 1/3 innings.

    The decimal part is in THIRDS of an inning (.1 = 1/3, .2 = 2/3), not a
    normal decimal, so we convert it properly.
    """
    try:
        whole, _, frac = str(innings_pitched).partition(".")
        result = float(whole)
        if frac == "1":
            result += 1 / 3
        elif frac == "2":
            result += 2 / 3
        return result
    except ValueError:
        return 0.0
