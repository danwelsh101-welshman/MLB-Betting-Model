"""
edgr — premium analytics dashboard (Streamlit).

Design goals: a fintech / sports-analytics terminal feel. Real data only —
every confidence, edge, unit and matchup is generated from the model + live
odds. Where real data does not exist yet (e.g. graded results), the UI shows
an honest empty state instead of placeholder numbers.

RUN:  streamlit run app/streamlit_app.py
"""

import os
import sys
import base64
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Bridge host-managed secrets (e.g. Streamlit Cloud's Secrets panel) into
# environment variables, so config/settings — which reads os.getenv — works
# in the cloud without a local .env file. Safe no-op when no secrets exist.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass

from config.settings import ODDS_WIDGET_URL
from backend.database import (
    init_db, get_connection, get_games_for_date,
    delete_picks_for_date, insert_row, upsert_row,
)
from backend.mlb_api import fetch_schedule
from backend.teams import abbr, logo_url
from backend.stats import get_pitcher_hand
from backend.odds import set_preferred_book, BOOKMAKER_KEYS
from models.picks_engine import build_all_picks
from models.strikeout_model import project_strikeouts

# Clean, non-redundant labels.
MARKET_LABEL = {
    "moneyline": "Moneyline", "run_line": "Run Line", "game_total": "Total",
    "f5_moneyline": "F5 Moneyline", "f5_total": "F5 Total", "nrfi_yrfi": "NRFI",
}
# Short chip text (avoids repeating the pick text itself).
MARKET_CHIP = {
    "moneyline": "MONEYLINE", "run_line": "RUN LINE", "game_total": "TOTAL",
    "f5_moneyline": "F5 ML", "f5_total": "F5 TOTAL", "nrfi_yrfi": "1ST INNING",
}
FILTERS = ["All Picks", "Moneyline", "Run Line", "Totals",
           "NRFI/YRFI", "Strikeout Props", "Home Run Props"]
FILTER_CODES = {
    "Moneyline": ["moneyline"], "Run Line": ["run_line"],
    "Totals": ["game_total", "f5_total"], "NRFI/YRFI": ["nrfi_yrfi"],
}

GREEN, YELLOW, RED, BLUE, MUTED = "#22C55E", "#EAB308", "#EF4444", "#3B82F6", "#8B98A9"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_picks(game_date: str) -> pd.DataFrame:
    init_db()
    conn = get_connection()
    try:
        return pd.read_sql_query(
            "SELECT * FROM picks WHERE date = ? ORDER BY confidence_score DESC",
            conn, params=(game_date,),
        )
    finally:
        conn.close()


def load_games_map(game_date: str) -> dict:
    return {g["game_id"]: g for g in get_games_for_date(game_date)}


def refresh_data(game_date: date) -> int:
    """Pull the schedule (live) and rebuild picks."""
    init_db()
    for game in fetch_schedule(game_date):
        upsert_row("games", game)
    return rebuild_picks(game_date)


def rebuild_picks(game_date: date) -> int:
    """Rebuild picks from already-stored games (no schedule re-pull).

    Used when the user switches sportsbook — fast because live odds and stats
    are already cached in memory.
    """
    iso = game_date.isoformat()
    picks = build_all_picks(get_games_for_date(iso), game_date.year)
    delete_picks_for_date(iso)
    for pick in picks:
        insert_row("picks", pick)
    return len(picks)


@st.cache_data(ttl=1800, show_spinner=False)
def strikeout_projections(game_date: str, season: int) -> pd.DataFrame:
    rows = []
    for g in get_games_for_date(game_date):
        for side in ("home", "away"):
            proj = project_strikeouts(g.get(f"{side}_pitcher_id"),
                                      g.get(f"{side}_pitcher"), season)
            if proj:
                rows.append({
                    "Pitcher": proj.pitcher_name, "Proj Ks": proj.expected_strikeouts,
                    "K/9": proj.k_per_9, "IP/start": proj.ip_per_start,
                    "Game": f"{abbr(g['away_team'])} @ {abbr(g['home_team'])}",
                })
    df = pd.DataFrame(rows)
    return df.sort_values("Proj Ks", ascending=False) if not df.empty else df


def conf_color(c: float) -> str:
    return GREEN if c >= 80 else YELLOW if c >= 75 else RED


def edge_color(e: float) -> str:
    """Traffic-light color for an edge %: elite / solid / marginal."""
    return GREEN if e >= 15 else YELLOW if e >= 5 else "#9AA7B8"


ET = ZoneInfo("America/New_York")


def time_slot(g) -> tuple[str, str]:
    """Return (display label, sort key) for a game's start time in ET."""
    t = g.get("game_time") if g else None
    if not t:
        return ("Time TBD", "9999")
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(ET)
        return (dt.strftime("%-I:%M %p ET"), dt.strftime("%H%M"))
    except ValueError:
        return ("Time TBD", "9999")


def pitchers_html(g) -> str:
    if not g:
        return ""
    ah, hh = get_pitcher_hand(g.get("away_pitcher_id")), get_pitcher_hand(g.get("home_pitcher_id"))
    ap, hp = g.get("away_pitcher") or "TBD", g.get("home_pitcher") or "TBD"
    a_tag = f" ({ah})" if ah else ""
    h_tag = f" ({hh})" if hh else ""
    return (f'<div class="pitchers">{abbr(g["away_team"])}: {ap}{a_tag}'
            f'<span class="at">@</span>{abbr(g["home_team"])}: {hp}{h_tag}</div>')


def logo_data_uri() -> str:
    svg = (PROJECT_ROOT / "app" / "assets" / "logo.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------
def matchup_html(p, games_map) -> str:
    g = games_map.get(p["game_id"])
    if not g:
        return f'<span class="mu-text">{p["game_label"]}</span>'
    a, h = g["away_team"], g["home_team"]
    return (
        '<span class="matchup">'
        f'<img class="tlogo" src="{logo_url(g["away_team_id"])}" alt="">{abbr(a)}'
        '<span class="at">@</span>'
        f'<img class="tlogo" src="{logo_url(g["home_team_id"])}" alt="">{abbr(h)}'
        '</span>'
    )


def pick_card_html(p, games_map, hero=False) -> str:
    """Return one pick card as a single-line HTML string.

    IMPORTANT: keep this as one line with no leading indentation. Streamlit's
    markdown treats indented blocks as code and would print the raw HTML.
    """
    c = float(p["confidence_score"])
    col = conf_color(c)
    odds = f'{int(p["odds_american"]):+d}'
    model_pct = p["model_probability"] * 100
    impl_pct = p["implied_probability"] * 100
    ecol = edge_color(float(p["edge_pct"]))
    cls = "card hero" if hero else "card"
    eyebrow = '<div class="eyebrow">★ BEST PICK OF THE DAY</div>' if hero else ""
    chip = MARKET_CHIP.get(p["market"], p["market"].upper())
    return (
        f'<div class="{cls}">{eyebrow}'
        f'<div class="card-top"><span class="chip">{chip}</span>'
        f'{matchup_html(p, games_map)}</div>'
        f'<div class="headline">{p["recommended_pick"]}'
        f'<span class="odds">{odds}</span></div>'
        f'{pitchers_html(games_map.get(p["game_id"]))}'
        f'<div class="metrics">'
        f'<div class="metric"><div class="m-label">Confidence</div>'
        f'<div class="m-value" style="color:{col}">{c:.0f}</div>'
        f'<div class="meter"><div class="meter-fill" '
        f'style="width:{c:.0f}%;background:{col}"></div></div></div>'
        f'<div class="metric"><div class="m-label">Edge</div>'
        f'<div class="m-value" style="color:{ecol}">{p["edge_pct"]:.1f}%</div></div>'
        f'<div class="metric"><div class="m-label">Units</div>'
        f'<div class="m-value">{p["suggested_units"]:.1f}<span class="u">u</span>'
        f'</div></div></div>'
        f'<div class="winprobs">'
        f'<div><span>Model Win %</span><b style="color:{GREEN}">{model_pct:.1f}%</b></div>'
        f'<div><span>Implied %</span><b>{impl_pct:.1f}%</b></div>'
        f'<div><span>Book</span><b>{p["sportsbook"]}</b></div></div>'
        f'<div class="analysis">{p["explanation"]}</div></div>'
    )


def dash_card(label, value, sub="") -> str:
    sub_html = f'<div class="d-sub">{sub}</div>' if sub else ""
    return f'<div class="dash-card"><div class="d-label">{label}</div><div class="d-value">{value}</div>{sub_html}</div>'


# ---------------------------------------------------------------------------
# Page setup + CSS
# ---------------------------------------------------------------------------
st.set_page_config(page_title="edgr — Daily MLB Picks", page_icon="⚾", layout="wide")

st.markdown(f"""
<style>
  header[data-testid="stHeader"] {{ background: transparent; }}
  .block-container {{ padding-top: 1.5rem; max-width: 100%;
                     padding-left: 2.5rem; padding-right: 2.5rem; }}
  .stApp {{ background: #0B0F14; }}

  .edgr-head {{ display:flex; align-items:center; gap:14px; margin-bottom:2px; }}
  .edgr-head img {{ height:46px; }}
  .edgr-tag {{ color:{MUTED}; font-size:0.9rem; margin:0 0 18px 2px; }}

  /* Dashboard metric cards */
  .dash-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
               gap:12px; margin-bottom:20px; }}
  .dash-card {{ background:#111827; border:1px solid #1C2533; border-radius:14px;
               padding:16px 18px; }}
  .d-label {{ color:{MUTED}; font-size:0.74rem; text-transform:uppercase;
             letter-spacing:0.06em; }}
  .d-value {{ font-size:1.7rem; font-weight:800; margin-top:4px; color:#E6EDF3; }}
  .d-sub {{ color:{MUTED}; font-size:0.72rem; margin-top:2px; }}

  /* Pick cards */
  .pick-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
               gap:16px; }}
  .card {{ background:#111827; border:1px solid #1C2533; border-radius:16px;
          padding:18px 20px; box-shadow:0 1px 3px rgba(0,0,0,0.4); }}
  .card.hero {{ grid-column:1/-1; background:linear-gradient(180deg,#121a2b,#111827);
               border:1px solid #2A3955; }}
  .eyebrow {{ color:{BLUE}; font-weight:700; font-size:0.78rem; letter-spacing:0.08em;
             margin-bottom:8px; }}
  .card-top {{ display:flex; justify-content:space-between; align-items:center;
              gap:10px; margin-bottom:10px; }}
  .chip {{ background:#0E1726; border:1px solid #25344b; color:{BLUE};
          font-size:0.68rem; font-weight:700; letter-spacing:0.07em;
          padding:3px 9px; border-radius:7px; }}
  .matchup {{ display:flex; align-items:center; gap:6px; color:#C7D2E0;
             font-weight:700; font-size:0.92rem; }}
  .mu-text {{ color:#C7D2E0; font-weight:600; font-size:0.85rem; }}
  .tlogo {{ height:22px; width:22px; object-fit:contain; }}
  .at {{ color:{MUTED}; margin:0 2px; font-weight:500; }}
  .headline {{ font-size:1.5rem; font-weight:800; color:#F2F6FB; margin:2px 0 4px;
              display:flex; align-items:baseline; gap:10px; }}
  .hero .headline {{ font-size:2rem; }}
  .odds {{ color:{MUTED}; font-size:1rem; font-weight:600; }}
  .pitchers {{ color:{MUTED}; font-size:0.8rem; margin-bottom:14px; }}
  .pitchers .at {{ margin:0 4px; }}
  .slot-title {{ font-size:0.92rem; font-weight:700; color:{BLUE};
                letter-spacing:0.04em; margin:22px 0 10px;
                border-left:3px solid {BLUE}; padding-left:10px; }}
  .metrics {{ display:flex; gap:18px; margin-bottom:14px; }}
  .metric {{ flex:1; }}
  .m-label {{ color:{MUTED}; font-size:0.72rem; text-transform:uppercase;
             letter-spacing:0.05em; }}
  .m-value {{ font-size:1.5rem; font-weight:800; margin-top:2px; }}
  .u {{ font-size:0.9rem; color:{MUTED}; font-weight:600; }}
  .meter {{ height:6px; background:#1C2533; border-radius:99px; margin-top:7px;
           overflow:hidden; }}
  .meter-fill {{ height:100%; border-radius:99px; }}
  .winprobs {{ display:flex; gap:10px; margin-bottom:12px; }}
  .winprobs div {{ flex:1; background:#0E1726; border:1px solid #1C2533;
                  border-radius:10px; padding:8px 10px; text-align:center; }}
  .winprobs span {{ display:block; color:{MUTED}; font-size:0.66rem;
                   text-transform:uppercase; letter-spacing:0.05em; }}
  .winprobs b {{ font-size:1.02rem; color:#E6EDF3; }}
  .analysis {{ color:#A9B6C7; font-size:0.84rem; line-height:1.5;
              border-top:1px solid #1C2533; padding-top:10px; }}

  /* Performance */
  .perf-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
               gap:12px; }}
  .perf-card {{ background:#0E1420; border:1px solid #1C2533; border-radius:14px;
               padding:14px 16px; }}
  .perf-period {{ font-weight:700; color:#E6EDF3; margin-bottom:8px; }}
  .perf-rows div {{ display:flex; justify-content:space-between; padding:3px 0;
                   font-size:0.85rem; }}
  .perf-rows span {{ color:{MUTED}; }} .perf-rows b {{ color:#6B7889; }}

  .section-title {{ font-size:1.15rem; font-weight:800; color:#E6EDF3;
                   margin:26px 0 12px; }}
  .empty {{ background:#0E1420; border:1px dashed #2A3548; border-radius:14px;
           padding:26px; text-align:center; color:{MUTED}; font-size:0.95rem; }}

  @media (max-width:640px) {{
    .metrics {{ gap:10px; }} .m-value {{ font-size:1.25rem; }}
    .headline {{ font-size:1.3rem; }} .hero .headline {{ font-size:1.5rem; }}
  }}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown(
    f'<div class="edgr-head"><img src="{logo_data_uri()}"></div>'
    '<div class="edgr-tag">Find the edge — AI-ranked MLB picks from live model output.</div>',
    unsafe_allow_html=True,
)

# Sidebar
with st.sidebar:
    st.markdown(f'<img src="{logo_data_uri()}" style="height:40px;margin-bottom:8px">',
                unsafe_allow_html=True)
    selected_date = st.date_input("Date", value=date.today())
    iso_date = selected_date.isoformat()

    book = st.selectbox("Sportsbook", list(BOOKMAKER_KEYS.keys()), index=0)
    set_preferred_book(book)

    min_edge = st.slider("Minimum edge %", 0.0, 20.0, 0.0, 0.5,
                         help="Hide picks with an edge below this value.")

    if st.button("🔄 Refresh data & picks", use_container_width=True):
        with st.spinner("Pulling live data and rebuilding picks..."):
            n = refresh_data(selected_date)
        st.cache_data.clear()
        st.success(f"{n} picks generated.")

    st.divider()
    st.caption("edgr is an analytics tool, not betting advice. Confidence reflects "
               "model confidence, not certainty. Gamble responsibly — 1-800-GAMBLER.")

# If the user switched sportsbook, rebuild picks from stored games (fast: live
# odds + stats are cached). This makes the odds reflect their chosen book.
if st.session_state.get("edgr_book") != book:
    st.session_state["edgr_book"] = book
    if get_games_for_date(iso_date):
        rebuild_picks(selected_date)

picks = load_picks(iso_date)
games_map = load_games_map(iso_date)

# On a fresh deploy the database starts empty. Auto-build the day's picks once
# (per date, per session) so visitors never land on a blank page.
if picks.empty and iso_date not in st.session_state.get("auto_built", set()):
    st.session_state.setdefault("auto_built", set()).add(iso_date)
    try:
        with st.spinner("Loading today's picks..."):
            refresh_data(selected_date)
        picks = load_picks(iso_date)
        games_map = load_games_map(iso_date)
    except Exception:
        pass

# Filter control
choice = st.segmented_control("Markets", FILTERS, default="All Picks",
                              selection_mode="single", label_visibility="collapsed")
choice = choice or "All Picks"

# Resolve the filtered view
if picks.empty:
    view = picks
elif choice in ("Strikeout Props", "Home Run Props"):
    view = picks.iloc[0:0]   # no graded prop bets exist yet
elif choice == "All Picks":
    view = picks
else:
    view = picks[picks["market"].isin(FILTER_CODES.get(choice, []))]

# Apply the sidebar minimum-edge filter.
if len(view):
    view = view[view["edge_pct"] >= min_edge]

# ---- Dashboard metrics (real data only) ----
if len(view):
    proj_value = float((view["expected_value"] * view["suggested_units"]).sum())
    cards = "".join([
        dash_card("Picks Available", len(view)),
        dash_card("Avg Confidence", f'{view["confidence_score"].mean():.0f}'),
        dash_card("Avg Edge", f'{view["edge_pct"].mean():.1f}%'),
        dash_card("Projected Value", f'+{proj_value:.1f}u', "model EV × units"),
    ])
    st.markdown(f'<div class="dash-grid">{cards}</div>', unsafe_allow_html=True)

# ---- Best pick + the rest ----
if choice == "Strikeout Props":
    st.markdown('<div class="section-title">Pitcher Strikeout Projections</div>',
                unsafe_allow_html=True)
    st.caption("Model projections (not graded bets) — live strikeout odds require a "
               "paid odds plan.")
    kdf = strikeout_projections(iso_date, selected_date.year)
    if kdf.empty:
        st.markdown('<div class="empty">No qualifying picks available</div>',
                    unsafe_allow_html=True)
    else:
        st.caption("Click any column header to sort (e.g. 'Proj Ks' for the most).")
        st.dataframe(kdf, use_container_width=True, hide_index=True)
elif view.empty:
    st.markdown('<div class="empty">No qualifying picks available</div>',
                unsafe_allow_html=True)
else:
    rows = list(view.to_dict("records"))

    # Featured best pick stays at the very top.
    st.markdown(f'<div class="pick-grid">{pick_card_html(rows[0], games_map, hero=True)}</div>',
                unsafe_allow_html=True)

    # Group the remaining picks by game start time (chronological).
    slots: dict = {}
    for r in rows[1:]:
        label, key = time_slot(games_map.get(r["game_id"]))
        slots.setdefault((key, label), []).append(r)

    for (key, label) in sorted(slots):
        st.markdown(f'<div class="slot-title">{label}</div>', unsafe_allow_html=True)
        cards = "".join(pick_card_html(r, games_map) for r in slots[(key, label)])
        st.markdown(f'<div class="pick-grid">{cards}</div>', unsafe_allow_html=True)

# ---- Performance tracking (honest empty state until results are graded) ----
st.markdown('<div class="section-title">Model Performance</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="empty">No performance data available yet — win rate and ROI unlock '
    'once game results are graded.</div>', unsafe_allow_html=True)

# ---- Live odds + projections (collapsible, real data) ----
if ODDS_WIDGET_URL:
    with st.expander("💰 Live Sportsbook Odds (FanDuel)"):
        components.iframe(ODDS_WIDGET_URL, height=430, scrolling=True)
