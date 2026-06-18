"""
edgr — grade a day's picks against final scores.

Pulls the latest (final) scores for a date, grades every stored pick, saves
the win/loss result, and prints how edgr did.

HOW TO RUN (venv on, from the project's main folder):

    python -m scripts.grade_results 2026-06-17     # a specific date
    python -m scripts.grade_results                # yesterday
"""

import sys
from datetime import date, datetime, timedelta

from backend.database import get_connection, upsert_row, get_games_for_date
from backend.mlb_api import fetch_schedule
from backend.grading import grade_pick, summarize


def _read_date_argument() -> date:
    if len(sys.argv) > 1:
        return datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    return date.today() - timedelta(days=1)   # default: yesterday


def main() -> None:
    game_date = _read_date_argument()
    iso = game_date.isoformat()

    # 1) Refresh scores — finished games now carry final runs.
    print(f"Fetching final scores for {iso}...")
    for game in fetch_schedule(game_date):
        upsert_row("games", game)

    games = {g["game_id"]: g for g in get_games_for_date(iso)}

    # 2) Grade every stored pick for that date.
    conn = get_connection()
    picks = [dict(r) for r in conn.execute(
        "SELECT * FROM picks WHERE date = ? ORDER BY confidence_score DESC", (iso,)
    ).fetchall()]

    if not picks:
        print(f"No picks stored for {iso}.")
        conn.close()
        return

    graded = []
    for p in picks:
        g = games.get(p["game_id"])
        is_final = g and g.get("game_status") == "Final"
        if not is_final or g.get("home_score") is None or g.get("away_score") is None:
            p["result"] = None          # game not final / no score yet — don't grade
        else:
            p["result"] = grade_pick(p, g["home_team"], g["away_team"],
                                     g["home_score"], g["away_score"])
        conn.execute("UPDATE picks SET result = ? WHERE id = ?",
                     (p["result"], p["id"]))
        graded.append(p)
    conn.commit()
    conn.close()

    # 3) Report.
    gradable = [g for g in graded if g["result"] in ("win", "loss", "push")]
    if not gradable:
        print("Those games aren't final yet — no results to grade.")
        return

    s = summarize(gradable)
    sign = "+" if s["units_won"] >= 0 else ""
    print(f"\n📊 edgr results for {iso}\n")
    print(f"   Record:     {s['wins']}-{s['losses']}"
          + (f"-{s['pushes']} (push)" if s["pushes"] else ""))
    print(f"   Win rate:   {s['win_pct']:.1f}%")
    print(f"   Units:      {sign}{s['units_won']:.2f}u on {s['units_staked']:.1f}u staked")
    print(f"   ROI:        {sign}{s['roi']:.1f}%\n")

    print(f"   {'RESULT':<7}{'PICK':<22}{'GAME':<26}{'SCORE'}")
    print("   " + "-" * 70)
    for p in graded:
        g = games.get(p["game_id"], {})
        score = (f"{g.get('away_team','')[:3]} {g.get('away_score','?')}-"
                 f"{g.get('home_score','?')} {g.get('home_team','')[:3]}")
        mark = {"win": "✅ WIN", "loss": "❌ LOSS",
                "push": "➖ PUSH"}.get(p["result"], "• n/a")
        print(f"   {mark:<7}{p['recommended_pick'][:21]:<22}{p['game_label'][:25]:<26}{score}")


if __name__ == "__main__":
    main()
