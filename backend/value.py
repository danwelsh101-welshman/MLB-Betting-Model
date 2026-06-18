"""
edgr — betting value math (odds, edge, expected value, confidence).

These are small, pure functions: give them numbers, they return numbers,
with no database or internet involved. That makes them easy to trust and
easy to test (see tests/test_value.py).

Quick glossary:
- "American odds": -120 means risk $120 to win $100; +150 means risk $100
  to win $150.
- "Implied probability": the win chance the odds price suggests.
- "Edge": how much MORE likely our model thinks the bet wins vs. the price.
- "Expected value (EV)": average profit per 1 unit staked, in the long run.
"""

from config.settings import (
    MAX_UNITS_PER_PICK,
    RISK_BANDS,
)


def american_to_decimal(american: int) -> float:
    """Convert American odds to decimal odds (total return per 1 staked)."""
    if american > 0:
        return 1 + american / 100
    return 1 + 100 / abs(american)


def american_to_implied(american: int) -> float:
    """Convert American odds to the implied win probability (0.0 - 1.0).

    Note: a sportsbook's implied probabilities add up to MORE than 100%
    across both sides — that gap is the book's built-in margin ("the vig").
    """
    if american > 0:
        return 100 / (american + 100)
    return abs(american) / (abs(american) + 100)


def expected_value(model_prob: float, american: int) -> float:
    """Expected profit per 1 unit staked, given our model's win probability.

    EV = (chance we win) * (profit if we win) - (chance we lose) * (1 unit).
    Positive EV means a profitable bet in the long run *if the model is right*.
    """
    decimal = american_to_decimal(american)
    profit_if_win = decimal - 1
    return model_prob * profit_if_win - (1 - model_prob) * 1


def edge_percent(model_prob: float, american: int) -> float:
    """How many percentage points our model beats the market price by."""
    return (model_prob - american_to_implied(american)) * 100


def confidence_score(model_prob: float, edge_pct: float, data_quality: float) -> float:
    """A 0-100 'model confidence' score that BLENDS two things:

      1. How likely the pick is to hit       (model_prob)
      2. How strong the betting value is      (edge_pct)

    A high score means the model thinks the pick is BOTH reasonably likely AND
    good value. We then shrink the score toward a neutral 50 when the
    underlying data is thin (low data_quality). This is MODEL confidence,
    NOT a guarantee.
    """
    data_quality = max(0.0, min(1.0, data_quality))

    # Component 1: win probability on a 0-100 scale.
    prob_component = model_prob * 100

    # Component 2: edge strength. 0% edge -> 50; ~12.5% edge -> 100.
    edge_component = max(0.0, min(100.0, 50 + edge_pct * 4))

    # Equal blend of the two.
    blended = 0.5 * prob_component + 0.5 * edge_component

    # Pull toward a neutral 50 when data quality is low.
    return 50 + (blended - 50) * data_quality


def risk_rating(confidence: float) -> str:
    """Turn a confidence score into Low / Medium / High risk."""
    if confidence >= RISK_BANDS["Low"]:
        return "Low"
    if confidence >= RISK_BANDS["Medium"]:
        return "Medium"
    return "High"


def suggested_units(confidence: float, edge_pct: float) -> float:
    """A modest, conservative stake suggestion (in 'units').

    Bigger when BOTH confidence and edge are higher, but always capped by
    MAX_UNITS_PER_PICK so no single pick is oversized. Responsible by design.
    """
    if confidence < 70 or edge_pct <= 0:
        return 0.0
    # Scale: every 1 unit needs ~5 points of edge and confidence above 70.
    confidence_factor = (confidence - 70) / 15      # 0 at 70, ~1 at 85
    edge_factor = edge_pct / 5                       # 1 unit per 5% edge
    units = 0.5 + confidence_factor + edge_factor    # start at half a unit
    units = min(units, MAX_UNITS_PER_PICK)
    return round(units * 2) / 2                      # round to nearest 0.5
