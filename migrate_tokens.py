#!/usr/bin/env python3
"""
Overhead map tokens migration (Phase 6).

Adds the generate-once token pointer to every map subject:
    - players.token_url  (nullable VARCHAR)
    - npcs.token_url      (nullable VARCHAR)
    - items.token_url     (nullable VARCHAR)

Additive + idempotent (guards on PRAGMA table_info); preserves accounts, items,
and existing characters. Same pattern as migrate_phase5 / migrate_appearance.

Back up game.db first, then run, then restart the service:

    python migrate_tokens.py
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
        p = _add_col_if_missing(conn, "players", "token_url", "token_url VARCHAR(255)")
        n = _add_col_if_missing(conn, "npcs", "token_url", "token_url VARCHAR(255)")
        i = _add_col_if_missing(conn, "items", "token_url", "token_url VARCHAR(255)")
    print(f"players.token_url added: {p}")
    print(f"npcs.token_url added: {n}")
    print(f"items.token_url added: {i}")


if __name__ == "__main__":
    migrate()
