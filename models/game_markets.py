"""
edgr — game-level markets model.

From two inputs we already know how to get (each team's offense and each
starter's ERA), we estimate how many runs each team should score. From those
two numbers we can derive EVERY game-level market:

  - Moneyline      : who wins?            -> P(home outscores away)
  - Run line (1.5) : win/lose by 2+?      -> P(margin >= 2)
  - Game total      : over/under runs?    -> P(total runs over the line)
  - First 5 (F5)    : same, but innings 1-5 only (starter-driven)

THE MATH (standard, well-understood):
  - Runs scored by a team  ~ Poisson(expected runs)
  - Final margin (home - away) ~ Skellam(home expected, away expected)
  - Total runs ~ Poisson(home expected + away expected)
Poisson/Skellam are the textbook distributions for "count" events like runs.

Like the NRFI model, this is a transparent rate-based model (v1). It uses real
season stats; the trained-ML upgrade comes later.
"""

from dataclasses import dataclass

from scipy.stats import poisson, skellam

from config.settings import (
    LEAGUE_RUNS_PER_GAME,
    LEAGUE_AVG_ERA,
    STARTER_WEIGHT_FULLGAME,
    HOME_FIELD_EDGE,
    PITCHER_TRUST_INNINGS,
)
from backend.stats import get_pitcher_stats, get_team_runs_per_game


@dataclass
class GameProjection:
    """Expected runs for one game, full-game and first-5-innings."""
    home_runs_full: float
    away_runs_full: float
    home_runs_f5: float
    away_runs_f5: float
    data_quality: float


def project_game(game: dict, season: int) -> GameProjection:
    """Estimate expected runs for both teams (full game and first 5 innings)."""
    league_rate = LEAGUE_RUNS_PER_GAME / 9.0

    # Offenses (runs per inning), falling back to league average if unknown.
    home_off = get_team_runs_per_game(game.get("home_team_id"), season)
    away_off = get_team_runs_per_game(game.get("away_team_id"), season)
    home_off_rate = (home_off / 9.0) if home_off else league_rate
    away_off_rate = (away_off / 9.0) if away_off else league_rate

    # Starting pitchers (runs allowed per inning), blended for small samples.
    home_start_rate, home_q = _pitcher_rate(game.get("home_pitcher_id"), season)
    away_start_rate, away_q = _pitcher_rate(game.get("away_pitcher_id"), season)

    # Full game: starter handles ~65% of innings, bullpen (~league) the rest.
    league_pitch_rate = LEAGUE_AVG_ERA / 9.0
    home_pitch_full = (STARTER_WEIGHT_FULLGAME * home_start_rate
                       + (1 - STARTER_WEIGHT_FULLGAME) * league_pitch_rate)
    away_pitch_full = (STARTER_WEIGHT_FULLGAME * away_start_rate
                       + (1 - STARTER_WEIGHT_FULLGAME) * league_pitch_rate)

    # Expected runs = (offense * opponent pitching / league) scaled to innings.
    # "/ league_rate" keeps the result centered on league-average scoring.
    home_full = _expected_runs(home_off_rate, away_pitch_full, league_rate, innings=9)
    away_full = _expected_runs(away_off_rate, home_pitch_full, league_rate, innings=9)

    # First 5 innings: entirely the starters, over 5 innings.
    home_f5 = _expected_runs(home_off_rate, away_start_rate, league_rate, innings=5)
    away_f5 = _expected_runs(away_off_rate, home_start_rate, league_rate, innings=5)

    offense_q = 1.0 if (home_off and away_off) else 0.6
    data_quality = round(offense_q * (home_q + away_q) / 2, 2)

    return GameProjection(home_full, away_full, home_f5, away_f5, data_quality)


def _expected_runs(offense_rate, pitch_rate, league_rate, innings) -> float:
    """Expected runs for one team over N innings (kept to a sensible range)."""
    per_inning = (offense_rate * pitch_rate / league_rate)
    return max(0.2, per_inning * innings)


def _pitcher_rate(pitcher_id, season: int) -> tuple[float, float]:
    """Runs-per-inning rate for a pitcher, blended toward league for small samples."""
    league_rate = LEAGUE_AVG_ERA / 9.0
    stats = get_pitcher_stats(pitcher_id, season)
    if not stats or stats["innings"] <= 0:
        return league_rate, 0.5
    weight = min(1.0, stats["innings"] / PITCHER_TRUST_INNINGS)
    blended_era = weight * stats["era"] + (1 - weight) * LEAGUE_AVG_ERA
    return blended_era / 9.0, 0.5 + 0.5 * weight


# ---------------------------------------------------------------------------
# Market probability functions (each returns a probability 0.0 - 1.0)
# ---------------------------------------------------------------------------
def moneyline_prob(home_runs: float, away_runs: float, home_field: bool = True) -> tuple[float, float]:
    """Return (home win prob, away win prob).

    Margin (home - away) follows a Skellam distribution. Ties (extra innings)
    are split 50/50. A small home-field edge nudges the home team up.
    """
    p_home_more = 1 - skellam.cdf(0, home_runs, away_runs)      # margin >= 1
    p_tie = skellam.pmf(0, home_runs, away_runs)                # margin == 0
    home_win = p_home_more + 0.5 * p_tie
    if home_field:
        home_win = min(0.97, home_win + HOME_FIELD_EDGE)
    return home_win, 1 - home_win


def run_line_prob(home_runs: float, away_runs: float) -> dict:
    """Return win probabilities for the four common -1.5 / +1.5 run-line sides."""
    # home -1.5 wins if home margin >= 2  ->  1 - P(margin <= 1)
    home_minus = 1 - skellam.cdf(1, home_runs, away_runs)
    # home +1.5 wins if home margin >= -1 ->  1 - P(margin <= -2)
    home_plus = 1 - skellam.cdf(-2, home_runs, away_runs)
    return {
        "home_-1.5": home_minus,
        "home_+1.5": home_plus,
        "away_+1.5": 1 - home_minus,   # opposite of home -1.5
        "away_-1.5": 1 - home_plus,    # opposite of home +1.5
    }


def total_prob(home_runs: float, away_runs: float, line: float) -> tuple[float, float]:
    """Return (over prob, under prob) for a total-runs line (e.g. 8.5)."""
    lam = home_runs + away_runs
    # For a .5 line, "over" means total >= line rounded up.
    threshold = int(line)              # 8.5 -> 8; over means total >= 9
    under = poisson.cdf(threshold, lam)
    over = 1 - under
    return over, under
