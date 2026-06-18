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

from backend.value import american_to_decimal


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
