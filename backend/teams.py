"""
edgr — MLB team branding helpers (abbreviations + logos).

Used by the dashboard to show compact, recognizable team chips with logos
instead of long text names. Logos come from MLB's public static CDN, keyed by
the same team id we already store on each game.
"""

# Full team name -> standard abbreviation.
TEAM_ABBR = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET",
    "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK",
    "Athletics": "ATH", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD",
    "San Francisco Giants": "SF", "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


def abbr(team_name: str) -> str:
    """Return a team's abbreviation, or a sensible 3-letter fallback."""
    if team_name in TEAM_ABBR:
        return TEAM_ABBR[team_name]
    # Fallback: first letters of the last word, uppercased.
    return (team_name or "").split()[-1][:3].upper()


def logo_url(team_id) -> str:
    """Return the MLB CDN logo URL for a team id (SVG)."""
    return f"https://www.mlbstatic.com/team-logos/{team_id}.svg"
