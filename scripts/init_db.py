"""
edgr — initialize the database.

Run this once (or any time) to create the empty database tables.
It is safe to run again; it won't erase anything.

HOW TO RUN (from the project's main folder, with the venv turned on):

    python -m scripts.init_db
"""

from backend.database import init_db, list_tables, DATABASE_PATH


def main() -> None:
    print("Setting up edgr's database...")
    init_db()
    tables = list_tables()

    print(f"\n✅ Database ready at: {DATABASE_PATH}")
    print("Tables created:")
    for table in tables:
        print(f"   • {table}")
    print("\nNothing else to do here — the tables start out empty.")
    print("Next we'll fill them with real MLB data.")


if __name__ == "__main__":
    main()
