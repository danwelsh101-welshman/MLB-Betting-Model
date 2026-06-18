"""
edgr — central settings (the "knobs and dials").

Everything that controls *how* edgr behaves lives here so you can tweak the
app without hunting through code. Import these values elsewhere like:

    from config.settings import MIN_CONFIDENCE

NOTE: Real secrets (like API keys) do NOT go here — they go in the .env file.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Load the secret keys from the .env file (if it exists) into the environment.
load_dotenv()

# ---------------------------------------------------------------------------
# 1. FOLDER PATHS
#    Built automatically from this file's location so they work on any machine.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
MODELS_DIR = PROJECT_ROOT / "models"

# Where the SQLite database file lives.
DATABASE_PATH = PROCESSED_DATA_DIR / "edgr.db"

# ---------------------------------------------------------------------------
# 2. SECRET KEYS (read from .env; safe defaults if missing)
# ---------------------------------------------------------------------------
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

# Which sportsbook edgr prices against. Set by the owner (not end users) so
# odds reflect one consistent book. Change in .env if you bet elsewhere.
PREFERRED_SPORTSBOOK = os.getenv("ODDS_PREFERRED_BOOK", "FanDuel")

# The Odds API *widget* URL (display-only embed). Optional. When set, the
# dashboard shows a live sportsbook-odds panel. This is separate from the REST
# API key above, which is what lets edgr READ odds to compute edges.
ODDS_WIDGET_URL = os.getenv("ODDS_WIDGET_URL", "")

# ---------------------------------------------------------------------------
# 3. PICK-QUALITY RULES
#    A pick is only shown if it clears ALL of these thresholds.
# ---------------------------------------------------------------------------
MIN_CONFIDENCE = 70.0       # 0-100 scale; must be at least this confident
MIN_EXPECTED_VALUE = 0.0    # EV must be positive (greater than 0)
MIN_EDGE_PCT = 2.0          # model must beat the market by at least this %

# "Reasonable odds range" in American odds. Avoids huge favorites/longshots.
MIN_AMERICAN_ODDS = -250
MAX_AMERICAN_ODDS = 250

# ---------------------------------------------------------------------------
# 4. BANKROLL / UNIT SIZING
#    A "unit" is your standard bet size. Suggested units scale with confidence.
# ---------------------------------------------------------------------------
MAX_UNITS_PER_PICK = 3.0    # never suggest more than this on a single pick

# ---------------------------------------------------------------------------
# 5. MARKETS edgr will analyze.  Flip a value to False to turn a market off.
# ---------------------------------------------------------------------------
MARKETS = {
    "moneyline": True,
    "run_line": True,
    "game_total": True,
    "team_total": True,
    "f5_moneyline": True,       # first five innings moneyline
    "f5_total": True,           # first five innings total
    "nrfi_yrfi": True,          # no/ yes runs first inning
    "pitcher_strikeouts": True,
    "pitcher_hits_allowed": True,
    "pitcher_earned_runs": True,
    "batter_hits": True,
    "batter_total_bases": True,
    "batter_home_runs": True,
    "batter_rbi": True,
    "batter_runs": True,
    "stolen_bases": True,       # only if data is available
}

# ---------------------------------------------------------------------------
# 5b. LEAGUE BASELINES (used by the models)
#     These are slow-moving MLB-wide averages. Update them once a season.
# ---------------------------------------------------------------------------
LEAGUE_RUNS_PER_GAME = 4.4          # league average runs scored per team per game
LEAGUE_AVG_ERA = 4.4                # league average ERA (runs allowed per 9 IP)
# Share of half-innings that are scoreless league-wide (~72%). NRFI baseline.
BASE_SCORELESS_HALF_INNING = 0.72
# A starter needs roughly this many innings before we fully trust their ERA.
PITCHER_TRUST_INNINGS = 40.0

# Full-game run prevention is mostly the starter, partly the bullpen (~league).
STARTER_WEIGHT_FULLGAME = 0.65      # 65% starter, 35% league-average bullpen
HOME_FIELD_EDGE = 0.03             # small bump to the home team's win probability

# Typical "main" lines used when a real sportsbook line isn't available yet.
DEFAULT_GAME_TOTAL_LINE = 8.5
DEFAULT_F5_TOTAL_LINE = 4.5
DEFAULT_RUN_LINE = 1.5

# ---------------------------------------------------------------------------
# 6. RISK RATING BANDS (based on confidence score)
# ---------------------------------------------------------------------------
RISK_BANDS = {
    "Low": 85,      # confidence >= 85  -> Low risk
    "Medium": 75,   # confidence >= 75  -> Medium risk
    # anything below the Medium cutoff -> High risk
}
