"""
edgr — automated checks for the betting value math.

Run all tests (venv on, from the project's main folder):

    pytest

These confirm the money math behaves correctly. `pytest.approx` lets us
compare floating-point numbers without worrying about tiny rounding.
"""

import pytest

from backend.value import (
    american_to_decimal,
    american_to_implied,
    expected_value,
    edge_percent,
    confidence_score,
    risk_rating,
    suggested_units,
)


def test_decimal_odds():
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(-110) == pytest.approx(1.9090909, rel=1e-4)
    assert american_to_decimal(150) == pytest.approx(2.5)


def test_implied_probability():
    # +100 is an even-money bet -> 50% implied.
    assert american_to_implied(100) == pytest.approx(0.5)
    # -200 favorite -> 66.7% implied.
    assert american_to_implied(-200) == pytest.approx(0.6667, rel=1e-3)


def test_expected_value_sign():
    # If we win 60% of the time at +100, that's clearly profitable.
    assert expected_value(0.60, 100) > 0
    # If we only win 40% at +100, that's a losing bet.
    assert expected_value(0.40, 100) < 0
    # Fair coin at fair odds -> roughly break-even.
    assert expected_value(0.50, 100) == pytest.approx(0.0)


def test_edge_percent():
    # Model 60% vs a 50% implied price -> a 10-point edge.
    assert edge_percent(0.60, 100) == pytest.approx(10.0)


def test_confidence_blends_probability_and_edge():
    # Same win probability, but more edge -> higher confidence.
    less_edge = confidence_score(0.65, edge_pct=2, data_quality=1.0)
    more_edge = confidence_score(0.65, edge_pct=10, data_quality=1.0)
    assert more_edge > less_edge


def test_confidence_scales_with_data_quality():
    # Full data quality keeps the score; poor quality pulls it toward 50.
    high = confidence_score(0.80, edge_pct=8, data_quality=1.0)
    low = confidence_score(0.80, edge_pct=8, data_quality=0.5)
    assert 50 < low < high


def test_risk_rating_bands():
    assert risk_rating(90) == "Low"
    assert risk_rating(78) == "Medium"
    assert risk_rating(60) == "High"


def test_units_capped_and_zero_when_weak():
    # A weak pick (low confidence) suggests no stake.
    assert suggested_units(confidence=68, edge_pct=1) == 0.0
    # A strong pick is positive but never exceeds the cap (3.0 units).
    big = suggested_units(confidence=95, edge_pct=40)
    assert 0 < big <= 3.0
