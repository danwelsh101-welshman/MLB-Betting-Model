"""
edgr — NRFI / YRFI model (version 1).

NRFI = "No Runs First Inning" (the 1st inning ends 0-0).
YRFI = "Yes Runs First Inning" (at least one run scores in the 1st).

WHY START HERE?
NRFI is the simplest MLB market to model well, because only a few things
matter: the two starting pitchers and the two offenses. No bullpen, no
late-game chaos.

HOW THIS MODEL WORKS (a transparent, calibrated rate model):
For each half-inning we estimate the chance it is scoreless, starting from
the league baseline (~72% of half-innings are scoreless) and adjusting for:
  - the batting team's runs-per-game (better offense -> more likely to score)
  - the pitcher's ERA            (better pitcher -> more likely scoreless)

    scoring_index = (team_runs_rate / league_rate) * (pitcher_rate / league_rate)
    P(scoreless half) = BASE_SCORELESS ** scoring_index

An index of 1.0 (perfectly average matchup) returns the 72% baseline. A
tougher matchup for the offense pushes the scoreless chance higher; an easier
one pushes it lower.

    NRFI probability = P(top scoreless) * P(bottom scoreless)
    YRFI probability = 1 - NRFI probability

NOTE: This is a legitimate *starter* model, not a trained machine-learning
model yet. It uses real season stats and a calibrated baseline. In a later
step we upgrade to logistic regression / gradient boosting with backtesting.
"""

from dataclasses import dataclass

from config.settings import (
    LEAGUE_RUNS_PER_GAME,
    LEAGUE_AVG_ERA,
    BASE_SCORELESS_HALF_INNING,
    PITCHER_TRUST_INNINGS,
)
from backend.stats import get_pitcher_stats, get_team_runs_per_game


@dataclass
class NrfiResult:
    """The model's output for one game."""
    nrfi_probability: float     # 0.0 - 1.0
    yrfi_probability: float     # 0.0 - 1.0
    data_quality: float         # 0.0 - 1.0 (how complete the inputs were)
    detail: str                 # short human-readable explanation


def predict_nrfi(game: dict, season: int) -> NrfiResult:
    """Estimate NRFI / YRFI probability for one game dictionary.

    `game` needs: home_team_id, away_team_id, home_pitcher_id, away_pitcher_id.
    """
    league_rate = LEAGUE_RUNS_PER_GAME / 9.0   # league runs per inning per team

    # --- Offenses: runs per game -> runs per inning. Fall back to league avg. ---
    home_off = get_team_runs_per_game(game.get("home_team_id"), season)
    away_off = get_team_runs_per_game(game.get("away_team_id"), season)
    home_off_rate = (home_off / 9.0) if home_off else league_rate
    away_off_rate = (away_off / 9.0) if away_off else league_rate

    # --- Pitchers: ERA -> runs per inning, blended toward league for small samples. ---
    home_pit_rate, home_pit_q = _pitcher_rate(game.get("home_pitcher_id"), season)
    away_pit_rate, away_pit_q = _pitcher_rate(game.get("away_pitcher_id"), season)

    # --- Half-inning scoreless probabilities ---
    # Top of the 1st: away offense vs. home pitcher.
    top_scoreless = _scoreless_prob(away_off_rate, home_pit_rate, league_rate)
    # Bottom of the 1st: home offense vs. away pitcher.
    bottom_scoreless = _scoreless_prob(home_off_rate, away_pit_rate, league_rate)

    nrfi = top_scoreless * bottom_scoreless
    yrfi = 1 - nrfi

    # Data quality: high only when we had real offense numbers AND trusted
    # pitcher samples for both sides.
    offense_q = 1.0 if (home_off and away_off) else 0.6
    data_quality = offense_q * (home_pit_q + away_pit_q) / 2

    detail = (
        f"NRFI {nrfi:.0%}: top scoreless {top_scoreless:.0%}, "
        f"bottom scoreless {bottom_scoreless:.0%}."
    )
    return NrfiResult(nrfi, yrfi, round(data_quality, 2), detail)


def _pitcher_rate(pitcher_id, season: int) -> tuple[float, float]:
    """Return (runs-per-inning rate, data_quality 0-1) for a pitcher.

    Blends a pitcher's ERA toward the league average when they have few
    innings, so a tiny sample can't dominate the estimate.
    """
    league_rate = LEAGUE_AVG_ERA / 9.0
    stats = get_pitcher_stats(pitcher_id, season)
    if not stats or stats["innings"] <= 0:
        return league_rate, 0.5   # no data -> league average, low quality

    # weight = how much we trust this pitcher's own ERA (0 to 1).
    weight = min(1.0, stats["innings"] / PITCHER_TRUST_INNINGS)
    blended_era = weight * stats["era"] + (1 - weight) * LEAGUE_AVG_ERA
    return blended_era / 9.0, 0.5 + 0.5 * weight


def _scoreless_prob(offense_rate: float, pitcher_rate: float, league_rate: float) -> float:
    """Probability a single half-inning is scoreless (0.0 - 1.0)."""
    scoring_index = (offense_rate / league_rate) * (pitcher_rate / league_rate)
    prob = BASE_SCORELESS_HALF_INNING ** scoring_index
    return max(0.05, min(0.95, prob))   # keep it sensible, never 0 or 1
