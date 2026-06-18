"""
edgr — odds provider (The Odds API client, with safe fallbacks).

WHAT'S REAL vs SAMPLE:
- With a free The Odds API key in your .env, edgr fetches LIVE moneyline,
  run line (spreads), and game totals and matches them to each game.
- First-5-innings, NRFI/YRFI, and player props are not on the common free
  feeds, so those stay as clearly-labeled SAMPLE prices for now.
- With NO key at all, every market uses SAMPLE prices so the app still runs.

Every game's odds carry an `is_placeholder` flag per market so the dashboard
can badge each pick honestly as LIVE or SAMPLE.

When you upgrade your odds plan later, you mostly extend this one file.
"""

import requests

from config.settings import (
    ODDS_API_KEY,
    DEFAULT_GAME_TOTAL_LINE,
    DEFAULT_F5_TOTAL_LINE,
    DEFAULT_RUN_LINE,
)

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "baseball_mlb"
TIMEOUT = 20

# Cache the live fetch so we only call the paid-credit API once per run.
_live_events_cache: list | None = None
_live_fetch_failed = False

# Which sportsbook's odds to prefer (The Odds API bookmaker key). The dashboard
# can change this so picks reflect the book the user actually bets at.
_preferred_book = "fanduel"

# Display name -> The Odds API bookmaker key.
BOOKMAKER_KEYS = {
    "FanDuel": "fanduel", "DraftKings": "draftkings", "BetMGM": "betmgm",
    "Caesars": "williamhill_us", "BetOnline": "betonlineag",
}


def set_preferred_book(display_name: str) -> None:
    """Set the preferred sportsbook by display name (e.g. 'DraftKings')."""
    global _preferred_book
    _preferred_book = BOOKMAKER_KEYS.get(display_name, "fanduel")


def _select_book(books: list) -> dict | None:
    """Pick the preferred bookmaker from an event, else the first available."""
    for b in books:
        if b.get("key") == _preferred_book:
            return b
    return books[0] if books else None


# ---------------------------------------------------------------------------
# Sample (placeholder) prices — realistic, but NOT real market lines.
# ---------------------------------------------------------------------------
def _sample_odds() -> dict:
    return {
        "sportsbook": "sample",
        "moneyline": {"home_odds": -110, "away_odds": -110, "is_placeholder": True},
        "run_line": {
            "line": DEFAULT_RUN_LINE,
            "home_-1.5": 130, "home_+1.5": -150,
            "away_-1.5": 130, "away_+1.5": -150,
            "is_placeholder": True,
        },
        "game_total": {
            "line": DEFAULT_GAME_TOTAL_LINE,
            "over": -110, "under": -110, "is_placeholder": True,
        },
        "f5_moneyline": {"home_odds": -110, "away_odds": -110, "is_placeholder": True},
        "f5_total": {
            "line": DEFAULT_F5_TOTAL_LINE,
            "over": -110, "under": -110, "is_placeholder": True,
        },
        "nrfi_yrfi": {"nrfi": -115, "yrfi": -105, "is_placeholder": True},
    }


# ---------------------------------------------------------------------------
# Live fetch from The Odds API
# ---------------------------------------------------------------------------
def _fetch_live_events() -> list:
    """Fetch current MLB odds once and cache the result (list of events)."""
    global _live_events_cache, _live_fetch_failed
    if _live_events_cache is not None or _live_fetch_failed:
        return _live_events_cache or []
    if not ODDS_API_KEY:
        _live_fetch_failed = True
        return []

    url = f"{ODDS_API_BASE}/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",   # moneyline, run line, totals (free tier)
        "oddsFormat": "american",
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        _live_events_cache = resp.json()
    except (requests.RequestException, ValueError):
        _live_fetch_failed = True
        _live_events_cache = []
    return _live_events_cache


def _normalize(name: str) -> str:
    return (name or "").lower().strip()


def _teams_match(a: str, b: str) -> bool:
    """Loose team-name match between MLB API and Odds API naming."""
    a, b = _normalize(a), _normalize(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    # Fall back to comparing the nickname (last word): "Yankees" == "Yankees".
    return a.split()[-1] == b.split()[-1]


def _find_event(game: dict, events: list) -> dict | None:
    """Find the live odds event matching this game by home + away team."""
    for event in events:
        if (_teams_match(game["home_team"], event.get("home_team", ""))
                and _teams_match(game["away_team"], event.get("away_team", ""))):
            return event
    return None


def _extract_from_event(game: dict, event: dict) -> dict:
    """Pull moneyline / run line / totals out of the first bookmaker we find."""
    odds = _sample_odds()   # start from samples, overwrite what we can fill live
    book = _select_book(event.get("bookmakers", []))
    if not book:
        return odds

    odds["sportsbook"] = book.get("title", "live")
    home_name = event.get("home_team", "")

    for market in book.get("markets", []):
        key = market.get("key")
        outcomes = market.get("outcomes", [])

        if key == "h2h":   # moneyline
            for o in outcomes:
                price = o.get("price")
                if _teams_match(o.get("name", ""), home_name):
                    odds["moneyline"]["home_odds"] = price
                else:
                    odds["moneyline"]["away_odds"] = price
            odds["moneyline"]["is_placeholder"] = False

        elif key == "totals":   # game total over/under
            for o in outcomes:
                if o.get("point") is not None:
                    odds["game_total"]["line"] = float(o["point"])
                if _normalize(o.get("name")) == "over":
                    odds["game_total"]["over"] = o.get("price")
                elif _normalize(o.get("name")) == "under":
                    odds["game_total"]["under"] = o.get("price")
            odds["game_total"]["is_placeholder"] = False

        elif key == "spreads":   # run line (usually +/-1.5)
            # Clear the sample sides first; only keep the sides the feed gives
            # us (the others become None and are skipped downstream).
            odds["run_line"].update({
                "home_-1.5": None, "home_+1.5": None,
                "away_-1.5": None, "away_+1.5": None,
            })
            for o in outcomes:
                point = o.get("point")
                price = o.get("price")
                is_home = _teams_match(o.get("name", ""), home_name)
                if point is None:
                    continue
                side = "home" if is_home else "away"
                sign = "-1.5" if point < 0 else "+1.5"
                odds["run_line"][f"{side}_{sign}"] = price
                odds["run_line"]["line"] = abs(float(point))
            odds["run_line"]["is_placeholder"] = False

    return odds


# ---------------------------------------------------------------------------
# The single function the rest of edgr calls
# ---------------------------------------------------------------------------
def get_game_odds(game: dict) -> dict:
    """Return all market odds for one game (live where possible, else sample)."""
    events = _fetch_live_events()
    if events:
        event = _find_event(game, events)
        if event:
            return _extract_from_event(game, event)
    return _sample_odds()


def is_live_mode() -> bool:
    """True when a REST key is set AND the live odds fetch returned events.

    Used to decide whether to hide sample-priced picks (so we never show a
    fabricated edge once real odds are available).
    """
    return bool(ODDS_API_KEY) and bool(_fetch_live_events())
