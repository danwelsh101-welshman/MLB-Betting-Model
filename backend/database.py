"""
edgr — the database layer (the "filing cabinet").

This module is the ONLY place in edgr that talks directly to the database.
Everything else (data pulls, models, the dashboard) goes through the helper
functions here. Keeping all database code in one file means that when you're
ready to upgrade from SQLite to PostgreSQL later, you mostly change THIS file
and little else.

We use Python's built-in `sqlite3`, so there is nothing extra to install.

Key ideas for a beginner:
- A "table" is like one sheet in a spreadsheet (rows and columns).
- "SQL" is the language we use to talk to the database.
- A "connection" is an open line to the database file.
"""

import sqlite3
from pathlib import Path

from config.settings import DATABASE_PATH, PROCESSED_DATA_DIR


# ---------------------------------------------------------------------------
# Connecting to the database
# ---------------------------------------------------------------------------
def get_connection(db_path: Path = DATABASE_PATH) -> sqlite3.Connection:
    """Open a connection to the SQLite database file.

    If the file (or its folder) doesn't exist yet, we create it.
    `row_factory` makes query results behave like dictionaries, so we can
    write row["home_team"] instead of remembering column numbers.
    """
    # Make sure the data/processed/ folder exists before writing the file.
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row          # results act like dictionaries
    conn.execute("PRAGMA foreign_keys = ON")  # enforce table relationships
    return conn


# ---------------------------------------------------------------------------
# The table definitions (our database "blueprint", a.k.a. the schema)
# ---------------------------------------------------------------------------
# Each block of SQL below creates one table IF IT DOESN'T ALREADY EXIST,
# so running init_db() many times is safe.

SCHEMA = {
    # 1) GAMES — one row per MLB game on the schedule.
    "games": """
        CREATE TABLE IF NOT EXISTS games (
            game_id       INTEGER PRIMARY KEY,   -- MLB's unique game id (gamePk)
            date          TEXT NOT NULL,          -- "2026-06-17"
            game_time     TEXT,                   -- UTC ISO start time
            season        INTEGER,
            home_team     TEXT NOT NULL,
            away_team     TEXT NOT NULL,
            home_team_id  INTEGER,                -- MLB team id (for stats lookups)
            away_team_id  INTEGER,
            home_pitcher  TEXT,                   -- probable starter (may be empty)
            away_pitcher  TEXT,
            home_pitcher_id INTEGER,              -- MLB pitcher id (for stats lookups)
            away_pitcher_id INTEGER,
            venue         TEXT,
            game_status   TEXT,                   -- "Scheduled", "Final", etc.
            home_score    INTEGER,                -- filled in after the game ends
            away_score    INTEGER,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """,

    # 2) ODDS — sportsbook prices. Many rows per game (one per market/selection).
    "odds": """
        CREATE TABLE IF NOT EXISTS odds (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id       INTEGER NOT NULL,
            market        TEXT NOT NULL,          -- "moneyline", "game_total", ...
            selection     TEXT NOT NULL,          -- team name, "Over", a player, ...
            line          REAL,                   -- e.g. 8.5 for a total (NULL if n/a)
            odds_american INTEGER NOT NULL,       -- e.g. -120 or +145
            sportsbook    TEXT,                   -- e.g. "DraftKings"
            pulled_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (game_id) REFERENCES games (game_id)
        )
    """,

    # 3) PICKS — the recommendations edgr produces. This feeds the dashboard.
    "picks": """
        CREATE TABLE IF NOT EXISTS picks (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT NOT NULL,
            game_id             INTEGER,
            game_label          TEXT,             -- "Yankees @ Red Sox"
            market              TEXT NOT NULL,
            selection           TEXT NOT NULL,    -- team or player name
            recommended_pick    TEXT NOT NULL,    -- "Over 8.5", "NRFI", "Yankees ML"
            sportsbook          TEXT,
            odds_american       INTEGER,
            model_probability   REAL,             -- 0.0 - 1.0
            implied_probability REAL,             -- 0.0 - 1.0 (from the odds)
            edge_pct            REAL,             -- model% minus implied%, as %
            expected_value      REAL,             -- EV per 1 unit staked
            confidence_score    REAL,             -- 0 - 100
            suggested_units     REAL,
            risk_rating         TEXT,             -- "Low", "Medium", "High"
            explanation         TEXT,             -- short "why we like it"
            result              TEXT,             -- "win"/"loss"/"push"/NULL (graded later)
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (game_id) REFERENCES games (game_id)
        )
    """,
}


# ---------------------------------------------------------------------------
# Creating / inspecting the database
# ---------------------------------------------------------------------------
def init_db(db_path: Path = DATABASE_PATH) -> None:
    """Create all tables if they don't exist yet. Safe to run repeatedly."""
    conn = get_connection(db_path)
    try:
        for table_name, create_sql in SCHEMA.items():
            conn.execute(create_sql)
        _migrate(conn)
        conn.commit()  # "save" the changes
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any new columns to existing tables (a tiny 'migration').

    `CREATE TABLE IF NOT EXISTS` won't add columns to a table that already
    exists, so when we add a new column to the schema above, we also add it
    here. SQLite ignores the add if the column is already present? It does
    not — so we check first and only add what's missing.
    """
    extra_columns = {
        "games": {
            "game_time": "TEXT",
            "home_team_id": "INTEGER",
            "away_team_id": "INTEGER",
            "home_pitcher_id": "INTEGER",
            "away_pitcher_id": "INTEGER",
        },
    }
    for table, columns in extra_columns.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, col_type in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def list_tables(db_path: Path = DATABASE_PATH) -> list[str]:
    """Return the names of all tables currently in the database."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return [row["name"] for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Small, reusable helpers used by the rest of edgr
# ---------------------------------------------------------------------------
def insert_row(table: str, data: dict, db_path: Path = DATABASE_PATH) -> int:
    """Insert one row into `table` from a dictionary of {column: value}.

    Returns the new row's id. Uses parameter placeholders (?) — never paste
    values straight into SQL — which keeps the database safe and tidy.
    """
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

    conn = get_connection(db_path)
    try:
        cursor = conn.execute(sql, tuple(data.values()))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def upsert_row(table: str, data: dict, db_path: Path = DATABASE_PATH) -> None:
    """Insert a row, OR replace it if one with the same primary key exists.

    Great for data we re-pull daily (like the schedule): running the pull
    twice updates the existing game instead of creating a duplicate.
    """
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    sql = f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})"

    conn = get_connection(db_path)
    try:
        conn.execute(sql, tuple(data.values()))
        conn.commit()
    finally:
        conn.close()


def count_rows(table: str, db_path: Path = DATABASE_PATH) -> int:
    """Return how many rows are in `table` (handy for quick checks)."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        return row["n"]
    finally:
        conn.close()


def get_games_for_date(game_date: str, db_path: Path = DATABASE_PATH) -> list[dict]:
    """Return all games stored for a given date ("YYYY-MM-DD") as dictionaries."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM games WHERE date = ? ORDER BY game_id", (game_date,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_picks_for_date(game_date: str, db_path: Path = DATABASE_PATH) -> None:
    """Remove existing picks for a date so we can regenerate cleanly."""
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM picks WHERE date = ?", (game_date,))
        conn.commit()
    finally:
        conn.close()
