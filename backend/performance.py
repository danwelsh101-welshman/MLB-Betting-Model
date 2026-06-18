"""
edgr — performance tracker.

Reads every graded pick out of the database and rolls it up into a running
record: win %, units won/lost, and ROI. Because results are stored in the
picks table, this record persists and grows for as long as edgr runs.
"""

from datetime import date, timedelta

from backend.database import get_connection
from backend.grading import summarize


def graded_picks(since: str | None = None) -> list[dict]:
    """Return graded picks (win/loss/push), optionally only on/after a date."""
    conn = get_connection()
    try:
        sql = "SELECT * FROM picks WHERE result IN ('win', 'loss', 'push')"
        params: tuple = ()
        if since:
            sql += " AND date >= ?"
            params = (since,)
        sql += " ORDER BY date"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def window_summary(days: int | None = None) -> dict:
    """Summarize results over the last `days` (None = all-time)."""
    since = None
    if days is not None:
        since = (date.today() - timedelta(days=days)).isoformat()
    picks = graded_picks(since)
    s = summarize(picks)
    s["total"] = s["wins"] + s["losses"] + s["pushes"]
    return s


def by_market() -> list[dict]:
    """Win rate + ROI broken down by market, best first."""
    picks = graded_picks()
    markets: dict = {}
    for p in picks:
        markets.setdefault(p["market"], []).append(p)
    rows = []
    for market, mp in markets.items():
        s = summarize(mp)
        rows.append({"market": market, "wins": s["wins"], "losses": s["losses"],
                     "win_pct": s["win_pct"], "roi": s["roi"],
                     "units_won": s["units_won"]})
    rows.sort(key=lambda r: r["roi"], reverse=True)
    return rows
