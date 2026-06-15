#!/usr/bin/env python3
"""
Phase 5 portraits migration.

Adds the generate-once portrait pointer to both subject tables:
    - players.portrait_url  (nullable VARCHAR)
    - npcs.portrait_url     (nullable VARCHAR)

Additive + idempotent (guards on PRAGMA table_info); preserves accounts, items,
and existing characters. The 5th migration in this series — identical pattern to
migrate_phase3 / migrate_phase4 / migrate_charsheet / migrate_race_slots.

Back up game.db first, then run, then restart the service:

    python migrate_phase5.py
"""
from sqlalchemy import text

from database import engine


def _add_col_if_missing(conn, table: str, column: str, ddl: str) -> bool:
    cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
    if column in cols:
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    return True


def migrate() -> None:
    with engine.begin() as conn:
        players_added = _add_col_if_missing(
            conn, "players", "portrait_url", "portrait_url VARCHAR(255)")
        npcs_added = _add_col_if_missing(
            conn, "npcs", "portrait_url", "portrait_url VARCHAR(255)")
    print(f"players.portrait_url added: {players_added}")
    print(f"npcs.portrait_url added: {npcs_added}")


if __name__ == "__main__":
    migrate()
