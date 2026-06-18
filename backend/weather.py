"""
edgr — ballpark weather (Open-Meteo, free, no API key).

Weather has a real, modest effect on run scoring:
  - Warm air is thinner, so the ball carries -> more runs / home runs.
  - Wind blowing OUT toward center boosts scoring; blowing IN suppresses it.
  - Domes / closed roofs are neutral (no weather effect).

We turn the forecast at game time into a single `factor` (a multiplier near
1.0) that the run model applies to both teams' expected runs. The effect is
kept conservative and clamped so a single windy reading can't dominate.

HONEST NOTE: park orientations (home plate -> center field bearing) are
approximate v1 values and the effect sizes are sensible defaults, not yet
calibrated by backtesting. Temperature is the most reliable signal here.
"""

from dataclasses import dataclass
import math
import requests

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 15

# venue name -> (latitude, longitude, is_dome, cf_bearing_degrees or None)
# cf_bearing = compass direction from home plate toward center field.
PARKS = {
    "Angel Stadium": (33.8003, -117.8827, False, 75),
    "Chase Field": (33.4455, -112.0667, True, None),
    "Truist Park": (33.8907, -84.4677, False, 60),
    "Oriole Park at Camden Yards": (39.2840, -76.6217, False, 60),
    "Fenway Park": (42.3467, -71.0972, False, 45),
    "Wrigley Field": (41.9484, -87.6553, False, 40),
    "Rate Field": (41.8299, -87.6338, False, 130),
    "Guaranteed Rate Field": (41.8299, -87.6338, False, 130),
    "Great American Ball Park": (39.0975, -84.5069, False, 100),
    "Progressive Field": (41.4962, -81.6852, False, 70),
    "Coors Field": (39.7559, -104.9942, False, 0),
    "Comerica Park": (42.3390, -83.0485, False, 150),
    "Daikin Park": (29.7570, -95.3555, True, None),
    "Minute Maid Park": (29.7570, -95.3555, True, None),
    "Kauffman Stadium": (39.0517, -94.4803, False, 60),
    "Dodger Stadium": (34.0739, -118.2400, False, 25),
    "loanDepot park": (25.7780, -80.2197, True, None),
    "American Family Field": (43.0280, -87.9712, True, None),
    "Target Field": (44.9817, -93.2776, False, 100),
    "Citi Field": (40.7571, -73.8458, False, 25),
    "Yankee Stadium": (40.8296, -73.9262, False, 75),
    "Sutter Health Park": (38.5803, -121.5135, False, 30),
    "Citizens Bank Park": (39.9061, -75.1665, False, 0),
    "PNC Park": (40.4469, -80.0057, False, 120),
    "Petco Park": (32.7073, -117.1566, False, 0),
    "Oracle Park": (37.7786, -122.3893, False, 90),
    "T-Mobile Park": (47.5914, -122.3325, True, None),
    "Busch Stadium": (38.6226, -90.1928, False, 70),
    "Tropicana Field": (27.7683, -82.6534, True, None),
    "George M. Steinbrenner Field": (27.9797, -82.5076, False, 30),
    "Globe Life Field": (32.7473, -97.0817, True, None),
    "Rogers Centre": (43.6414, -79.3894, True, None),
    "Nationals Park": (38.8730, -77.0074, False, 30),
}

# Cache: {(venue, hour_key): Weather}
_cache: dict = {}


@dataclass
class Weather:
    ok: bool                 # True if we have a usable reading
    is_dome: bool
    temp_f: float | None
    wind_mph: float | None
    wind_effect: str | None  # "out", "in", "cross", or None
    factor: float            # run-environment multiplier (~0.88 - 1.14)
    summary: str             # short human-readable string


def _neutral(summary: str = "Conditions unavailable") -> Weather:
    return Weather(False, False, None, None, None, 1.0, summary)


def _find_park(venue: str):
    """Match a venue to a park, tolerating sponsor names (e.g. 'X Field at Y')."""
    if not venue:
        return None
    if venue in PARKS:
        return PARKS[venue]
    for name, data in PARKS.items():
        if name in venue or venue in name:
            return data
    return None


def get_game_weather(game: dict) -> Weather:
    """Return the weather factor + summary for a game (cached per venue/hour)."""
    venue = game.get("venue")
    game_time = game.get("game_time")
    park = _find_park(venue)

    if not park:
        return _neutral()
    lat, lon, is_dome, cf_bearing = park
    if is_dome:
        return Weather(True, True, None, None, None, 1.0, "Roof — neutral conditions")
    if not game_time:
        return _neutral()

    hour_key = game_time[:13]   # "2026-06-17T17"
    cache_key = (venue, hour_key)
    if cache_key in _cache:
        return _cache[cache_key]

    weather = _fetch(lat, lon, game_time, cf_bearing)
    _cache[cache_key] = weather
    return weather


def _fetch(lat, lon, game_time, cf_bearing) -> Weather:
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "timezone": "UTC", "forecast_days": 16, "past_days": 2,
    }
    try:
        data = requests.get(OPEN_METEO, params=params, timeout=TIMEOUT).json()
        hours = data["hourly"]["time"]
        target = game_time[:13]   # match to the nearest whole hour (UTC)
        idx = next((i for i, t in enumerate(hours) if t[:13] == target), None)
        if idx is None:
            return _neutral()
        temp = float(data["hourly"]["temperature_2m"][idx])
        wind = float(data["hourly"]["wind_speed_10m"][idx])
        wdir = float(data["hourly"]["wind_direction_10m"][idx])
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return _neutral()

    return _build(temp, wind, wdir, cf_bearing)


def _build(temp, wind, wdir, cf_bearing) -> Weather:
    # Temperature: ball carries in warm air. ~1.5% per 10°F off a 70°F baseline.
    temp_factor = 1 + (temp - 70) * 0.0015

    effect, wind_factor = None, 1.0
    if cf_bearing is not None:
        wind_to = (wdir + 180) % 360            # direction the wind blows toward
        diff = abs((wind_to - cf_bearing + 180) % 360 - 180)
        if diff <= 55:                          # blowing out toward center
            effect, sign = "out", 1
        elif diff >= 125:                       # blowing in from center
            effect, sign = "in", -1
        else:
            effect, sign = "cross", 0
        wind_factor = 1 + sign * min(wind, 25) * 0.004   # 15 mph out -> +6%

    factor = max(0.88, min(1.14, temp_factor * wind_factor))

    if effect in ("out", "in"):
        summary = f"{temp:.0f}°F, wind {wind:.0f} mph {effect} to center"
    elif effect == "cross":
        summary = f"{temp:.0f}°F, {wind:.0f} mph crosswind"
    else:
        summary = f"{temp:.0f}°F"

    return Weather(True, False, temp, wind, effect, round(factor, 3), summary)
