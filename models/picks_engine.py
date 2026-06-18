"""
edgr — the picks engine (multi-market).

For each game we:
  1. Project expected runs (full game + first 5 innings).
  2. Run the NRFI model.
  3. Get odds for every market (live where possible, else sample).
  4. For each market, evaluate every side, keep the best positive-edge side.
  5. Apply edgr's strict quality rules; only survivors become picks.

A single game can therefore produce several picks (one per market it qualifies
in), so the dashboard can mirror the spread of markets a sportsbook offers.
"""

from datetime import datetime, timezone

from config.settings import (
    MIN_CONFIDENCE,
    MIN_EXPECTED_VALUE,
    MIN_EDGE_PCT,
    MIN_AMERICAN_ODDS,
    MAX_AMERICAN_ODDS,
)
from backend.value import (
    american_to_implied,
    expected_value,
    edge_percent,
    confidence_score,
    risk_rating,
    suggested_units,
)
from backend.odds import get_game_odds, is_live_mode
from backend.stats import get_pitcher_hand
from backend.weather import get_game_weather
from models.nrfi_model import predict_nrfi
from models.game_markets import (
    project_game,
    moneyline_prob,
    run_line_prob,
    total_prob,
)


def _passes_rules(confidence: float, ev: float, edge: float, odds: int) -> bool:
    """edgr's strict 'only show strong picks' filter."""
    return (
        confidence >= MIN_CONFIDENCE
        and ev > MIN_EXPECTED_VALUE
        and edge >= MIN_EDGE_PCT
        and MIN_AMERICAN_ODDS <= odds <= MAX_AMERICAN_ODDS
    )


def _build_market_pick(
    game: dict,
    market: str,
    sides: list[dict],
    data_quality: float,
    is_placeholder: bool,
    sportsbook: str,
    context: str,
) -> dict | None:
    """Pick the best qualifying side of one market for one game (or None).

    `sides` is a list of dicts: {selection, recommended, model_prob, odds}.
    """
    scored = []
    for side in sides:
        odds = side["odds"]
        if odds is None:
            continue
        edge = edge_percent(side["model_prob"], odds)
        ev = expected_value(side["model_prob"], odds)
        conf = confidence_score(side["model_prob"], edge, data_quality)
        scored.append((side, edge, ev, conf))

    if not scored:
        return None

    side, edge, ev, conf = max(scored, key=lambda s: s[1])   # best edge
    if not _passes_rules(conf, ev, edge, side["odds"]):
        return None

    note = " Odds are sample placeholders." if is_placeholder else ""
    # When the chosen odds are placeholders, label the book "sample" so the
    # rest of the app can treat the pick honestly (badge / filter it).
    book = "sample" if is_placeholder else sportsbook
    implied = american_to_implied(side["odds"])
    # Two-sentence note: (1) the value, (2) the supporting context.
    sentence1 = (
        f"edgr projects {side['recommended']} to hit {side['model_prob'] * 100:.1f}% "
        f"versus the market's implied {implied * 100:.1f}% — a {edge:.1f}% edge "
        f"at {side['odds']:+d}."
    )
    analysis = f"{sentence1} {context}{note}"
    return {
        "date": game["date"],
        "game_id": game["game_id"],
        "game_label": f"{game['away_team']} @ {game['home_team']}",
        "market": market,
        "selection": side["selection"],
        "recommended_pick": side["recommended"],
        "sportsbook": book,
        "odds_american": side["odds"],
        "model_probability": round(side["model_prob"], 4),
        "implied_probability": round(american_to_implied(side["odds"]), 4),
        "edge_pct": round(edge, 2),
        "expected_value": round(ev, 4),
        "confidence_score": round(conf, 1),
        "suggested_units": suggested_units(conf, edge),
        "risk_rating": risk_rating(conf),
        "explanation": analysis,
        "result": None,
    }


def _pitch_clause(game: dict) -> str:
    """A short 'AwayP (L) vs HomeP (R)' phrase for the supporting sentence."""
    ah = get_pitcher_hand(game.get("away_pitcher_id"))
    hh = get_pitcher_hand(game.get("home_pitcher_id"))
    ap = game.get("away_pitcher") or "TBD"
    hp = game.get("home_pitcher") or "TBD"
    a = f"{ap} ({ah})" if ah else ap
    h = f"{hp} ({hh})" if hh else hp
    return f"{a} faces {h}"


def build_picks_for_game(game: dict, season: int) -> list[dict]:
    """Build every qualifying pick (across all markets) for one game."""
    weather = get_game_weather(game)
    proj = project_game(game, season, weather.factor)
    nrfi = predict_nrfi(game, season)
    odds = get_game_odds(game)
    home, away = game["home_team"], game["away_team"]
    picks: list[dict] = []

    # Shared pieces for the supporting (2nd) sentence of each pick's note.
    pitch = _pitch_clause(game)
    if weather.is_dome:
        wx = " under a closed roof"
    elif weather.ok:
        wx = f" with {weather.summary}"
    else:
        wx = ""

    # --- Moneyline ---
    home_win, away_win = moneyline_prob(proj.home_runs_full, proj.away_runs_full)
    ml = odds["moneyline"]
    pick = _build_market_pick(
        game, "moneyline",
        [
            {"selection": home, "recommended": f"{home} ML",
             "model_prob": home_win, "odds": ml["home_odds"]},
            {"selection": away, "recommended": f"{away} ML",
             "model_prob": away_win, "odds": ml["away_odds"]},
        ],
        proj.data_quality, ml["is_placeholder"], odds["sportsbook"],
        f"{pitch}, with edgr projecting {home} {proj.home_runs_full:.1f} – "
        f"{away} {proj.away_runs_full:.1f}{wx}.",
    )
    if pick:
        picks.append(pick)

    # --- Run line (only the standard 1.5; the model assumes that margin) ---
    rl = odds["run_line"]
    line = rl["line"]
    if abs(line - 1.5) < 0.01:
        rp = run_line_prob(proj.home_runs_full, proj.away_runs_full)
        pick = _build_market_pick(
            game, "run_line",
            [
                {"selection": home, "recommended": f"{home} -{line}",
                 "model_prob": rp["home_-1.5"], "odds": rl["home_-1.5"]},
                {"selection": home, "recommended": f"{home} +{line}",
                 "model_prob": rp["home_+1.5"], "odds": rl["home_+1.5"]},
                {"selection": away, "recommended": f"{away} -{line}",
                 "model_prob": rp["away_-1.5"], "odds": rl["away_-1.5"]},
                {"selection": away, "recommended": f"{away} +{line}",
                 "model_prob": rp["away_+1.5"], "odds": rl["away_+1.5"]},
            ],
            proj.data_quality, rl["is_placeholder"], odds["sportsbook"],
            f"{pitch}, with edgr projecting {home} {proj.home_runs_full:.1f} – "
            f"{away} {proj.away_runs_full:.1f}{wx}.",
        )
        if pick:
            picks.append(pick)

    # --- Game total ---
    gt = odds["game_total"]
    over, under = total_prob(proj.home_runs_full, proj.away_runs_full, gt["line"])
    total_proj = proj.home_runs_full + proj.away_runs_full
    pick = _build_market_pick(
        game, "game_total",
        [
            {"selection": "Over", "recommended": f"Over {gt['line']}",
             "model_prob": over, "odds": gt["over"]},
            {"selection": "Under", "recommended": f"Under {gt['line']}",
             "model_prob": under, "odds": gt["under"]},
        ],
        proj.data_quality, gt["is_placeholder"], odds["sportsbook"],
        f"{pitch}, with edgr projecting {total_proj:.1f} combined runs against the "
        f"{gt['line']} line{wx}.",
    )
    if pick:
        picks.append(pick)

    # --- First 5 innings moneyline (no home-field edge) ---
    f5_home, f5_away = moneyline_prob(proj.home_runs_f5, proj.away_runs_f5, home_field=False)
    f5ml = odds["f5_moneyline"]
    pick = _build_market_pick(
        game, "f5_moneyline",
        [
            {"selection": home, "recommended": f"{home} F5 ML",
             "model_prob": f5_home, "odds": f5ml["home_odds"]},
            {"selection": away, "recommended": f"{away} F5 ML",
             "model_prob": f5_away, "odds": f5ml["away_odds"]},
        ],
        proj.data_quality, f5ml["is_placeholder"], odds["sportsbook"],
        f"First-5 projected runs {proj.home_runs_f5:.1f}-{proj.away_runs_f5:.1f}.",
    )
    if pick:
        picks.append(pick)

    # --- First 5 innings total ---
    f5t = odds["f5_total"]
    f5_over, f5_under = total_prob(proj.home_runs_f5, proj.away_runs_f5, f5t["line"])
    f5_total_proj = proj.home_runs_f5 + proj.away_runs_f5
    pick = _build_market_pick(
        game, "f5_total",
        [
            {"selection": "Over", "recommended": f"F5 Over {f5t['line']}",
             "model_prob": f5_over, "odds": f5t["over"]},
            {"selection": "Under", "recommended": f"F5 Under {f5t['line']}",
             "model_prob": f5_under, "odds": f5t["under"]},
        ],
        proj.data_quality, f5t["is_placeholder"], odds["sportsbook"],
        f"First-5 projected total {f5_total_proj:.1f} runs vs line {f5t['line']}.",
    )
    if pick:
        picks.append(pick)

    # --- NRFI / YRFI ---
    nr = odds["nrfi_yrfi"]
    pick = _build_market_pick(
        game, "nrfi_yrfi",
        [
            {"selection": "NRFI", "recommended": "NRFI",
             "model_prob": nrfi.nrfi_probability, "odds": nr["nrfi"]},
            {"selection": "YRFI", "recommended": "YRFI",
             "model_prob": nrfi.yrfi_probability, "odds": nr["yrfi"]},
        ],
        nrfi.data_quality, nr["is_placeholder"], odds["sportsbook"],
        nrfi.detail,
    )
    if pick:
        picks.append(pick)

    return picks


def _is_upcoming(game: dict) -> bool:
    """True only for games that have NOT started yet.

    edgr prices pre-game lines, so we must skip games that are in progress or
    final — otherwise the model's pre-game projection gets compared to live
    in-game odds, producing fake edges.
    """
    status = (game.get("game_status") or "").lower()
    if any(s in status for s in ("progress", "final", "over", "completed", "suspended")):
        return False
    t = game.get("game_time")
    if t:
        try:
            return datetime.fromisoformat(t.replace("Z", "+00:00")) > datetime.now(timezone.utc)
        except ValueError:
            pass
    return "scheduled" in status or "pre-game" in status or "warmup" in status


def build_all_picks(games: list[dict], season: int) -> list[dict]:
    """Build qualifying picks for upcoming games, ranked best-first."""
    picks: list[dict] = []
    for game in games:
        if not _is_upcoming(game):
            continue
        picks.extend(build_picks_for_game(game, season))

    # In live mode, never show picks built on placeholder prices — only real
    # odds. (Markets the free feed lacks, like F5/NRFI, drop out here.)
    if is_live_mode():
        picks = [p for p in picks if p["sportsbook"] != "sample"]

    picks.sort(
        key=lambda p: (p["confidence_score"], p["expected_value"], p["edge_pct"]),
        reverse=True,
    )
    return picks
