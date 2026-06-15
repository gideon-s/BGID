#!/usr/bin/env python3
"""
Character appearance migration.

Adds `players.appearance` (free-form looks/bio, default '') — set at character
creation and editable from the character sheet; it feeds the portrait prompt.

Additive + idempotent (guards on PRAGMA table_info); preserves accounts/items.
Back up game.db first, then run, then restart the service:

    python migrate_appearance.py
"""
from sqlalchemy import text

from database import engine


def migrate() -> None:
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(players)"))}
        added = "appearance" not in cols
        if added:
            conn.execute(text(
                "ALTER TABLE players ADD COLUMN appearance TEXT NOT NULL DEFAULT ''"))
    print(f"players.appearance added: {added}")


if __name__ == "__main__":
    migrate()
