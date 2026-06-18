"""
edgr — pitcher strikeout projection (the first player-prop model).

This projects how many strikeouts a starting pitcher is likely to record.

THE MATH:
    expected strikeouts = (K/9) * (innings the pitcher usually throws / 9)

A pitcher who averages 10 K/9 and throws 6 innings projects to
10 * 6/9 = 6.7 strikeouts. Strikeout counts follow a Poisson distribution, so
once we connect real prop odds we can also compute over/under probabilities
for any line (e.g. "Over 6.5 Ks").

HONEST NOTE:
We can project the NUMBER now from free data. To turn this into a *bet* with
edge/EV, edgr needs the sportsbook's strikeout line and price — those come
from a paid odds tier and get wired in later. Until then, edgr shows the
projection only (no bet recommendation), so nothing is fabricated.
"""

from dataclasses import dataclass

from scipy.stats import poisson

from config.settings import PITCHER_TRUST_INNINGS
from backend.stats import get_pitcher_stats


@dataclass
class StrikeoutProjection:
    pitcher_name: str
    expected_strikeouts: float
    k_per_9: float
    ip_per_start: float
    data_quality: float


def project_strikeouts(pitcher_id: int, pitcher_name: str, season: int) -> StrikeoutProjection | None:
    """Project a starter's strikeouts for their next start, or None if no data."""
    stats = get_pitcher_stats(pitcher_id, season)
    if not stats or stats["innings"] <= 0 or stats["ip_per_start"] <= 0:
        return None

    # Season innings can include relief work, which inflates innings-per-start
    # for swing pitchers. Cap to a realistic starter range (3 to 7 innings).
    ip_per_start = max(3.0, min(7.0, stats["ip_per_start"]))
    expected_k = stats["k_per_9"] * ip_per_start / 9.0

    # Trust grows with sample size (innings pitched this season).
    data_quality = round(min(1.0, stats["innings"] / PITCHER_TRUST_INNINGS), 2)

    return StrikeoutProjection(
        pitcher_name=pitcher_name,
        expected_strikeouts=round(expected_k, 2),
        k_per_9=round(stats["k_per_9"], 2),
        ip_per_start=round(ip_per_start, 2),
        data_quality=data_quality,
    )


def over_under_probability(expected_k: float, line: float) -> tuple[float, float]:
    """Return (P over line, P under line) for a strikeout prop line.

    Used once real prop odds are connected. Strikeouts ~ Poisson(expected).
    """
    threshold = int(line)              # 6.5 -> 6; over means K >= 7
    under = poisson.cdf(threshold, expected_k)
    return 1 - under, under
