"""
edgr — grade picks against final scores (the start of backtesting).

Given a finished game's final score, decide whether each stored pick won or
lost, then roll the day up into a record, units won/lost, and ROI. This is
what eventually fills the dashboard's Model Performance section with REAL
numbers — never estimated ones.

Only graded markets (moneyline, run line, game total) are handled here; they
need just the final score. Inning-level markets (F5, NRFI) would need the
linescore and are added later.
"""

import re
from datetime import date

from backend.value import american_to_decimal
from backend.database import get_connection, upsert_row, get_games_for_date
from backend.mlb_api import fetch_schedule


def grade_pick(pick: dict, home_team: str, away_team: str,
               home_score: int, away_score: int) -> str | None:
    """Return 'win', 'loss', 'push', or None (can't grade) for one pick."""
    market = pick["market"]
    selection = pick["selection"]
    recommended = pick["recommended_pick"]

    if market == "moneyline":
        team_home = selection == home_team
        team, opp = (home_score, away_score) if team_home else (away_score, home_score)
        return "win" if team > opp else "loss"

    if market == "run_line":
        line = _number(recommended)
        if line is None:
            return None
        sign = -1 if " -" in recommended else 1   # "-1.5" vs "+1.5"
        team_home = selection == home_team
        margin = (home_score - away_score) if team_home else (away_score - home_score)
        covered = margin > -sign * line            # -1.5: margin>1.5 ; +1.5: margin>-1.5
        return "win" if covered else "loss"

    if market == "game_total":
        line = _number(recommended)
        if line is None:
            return None
        total = home_score + away_score
        if total == line:
            return "push"
        is_over = recommended.lower().startswith("over")
        hit = (total > line) if is_over else (total < line)
        return "win" if hit else "loss"

    return None   # markets we can't grade from the final score alone


def grade_date(iso_date: str) -> list[dict]:
    """Fetch final scores for a date and grade every stored pick for it.

    Saves each pick's result back to the database (so the record persists), and
    returns the graded pick dicts. Only games marked Final are graded; games
    still in progress are left ungraded (result stays None).
    """
    for game in fetch_schedule(date.fromisoformat(iso_date)):
        upsert_row("games", game)

    games = {g["game_id"]: g for g in get_games_for_date(iso_date)}
    conn = get_connection()
    try:
        picks = [dict(r) for r in conn.execute(
            "SELECT * FROM picks WHERE date = ?", (iso_date,)).fetchall()]
        for p in picks:
            g = games.get(p["game_id"])
            is_final = g and g.get("game_status") == "Final"
            if not is_final or g.get("home_score") is None or g.get("away_score") is None:
                p["result"] = None
            else:
                p["result"] = grade_pick(p, g["home_team"], g["away_team"],
                                         g["home_score"], g["away_score"])
            conn.execute("UPDATE picks SET result = ? WHERE id = ?",
                         (p["result"], p["id"]))
        conn.commit()
        return picks
    finally:
        conn.close()


def grade_all_pending(before_date: str) -> int:
    """Grade every past date that still has ungraded picks. Returns # of dates."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT date FROM picks WHERE date < ? AND result IS NULL "
            "ORDER BY date", (before_date,)).fetchall()
    finally:
        conn.close()
    dates = [r["date"] for r in rows]
    for d in dates:
        grade_date(d)
    return len(dates)


def _number(text: str) -> float | None:
    """Pull the numeric line out of a pick label like 'Over 8.5' or 'Team -1.5'."""
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def summarize(graded: list[dict]) -> dict:
    """Roll a list of graded picks into record / units / ROI.

    Each item needs: result, odds_american, suggested_units.
    """
    wins = sum(1 for g in graded if g["result"] == "win")
    losses = sum(1 for g in graded if g["result"] == "loss")
    pushes = sum(1 for g in graded if g["result"] == "push")

    units_staked = 0.0
    units_won = 0.0
    for g in graded:
        if g["result"] == "push" or g["result"] is None:
            continue
        stake = g["suggested_units"]
        units_staked += stake
        if g["result"] == "win":
            units_won += stake * (american_to_decimal(g["odds_american"]) - 1)
        else:
            units_won -= stake

    decided = wins + losses
    return {
        "wins": wins, "losses": losses, "pushes": pushes,
        "win_pct": (wins / decided * 100) if decided else 0.0,
        "units_staked": round(units_staked, 2),
        "units_won": round(units_won, 2),
        "roi": (units_won / units_staked * 100) if units_staked else 0.0,
    }
