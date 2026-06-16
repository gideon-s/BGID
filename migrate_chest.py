#!/usr/bin/env python3
"""
Class-gear chest migration.

Adds `players.opened_chests` (JSON list of chest ids a character has already
looted, default '[]') so a chest can spawn its contents once per character.

Additive + idempotent (guards on PRAGMA table_info); preserves accounts/items.
The chest item itself is seeded by seed.py (idempotent _get_or_create). Run this,
then seed.py, then restart:

    python migrate_chest.py && python seed.py
"""
from sqlalchemy import text

from database import engine


def migrate() -> None:
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(players)"))}
        added = "opened_chests" not in cols
        if added:
            conn.execute(text(
                "ALTER TABLE players ADD COLUMN opened_chests TEXT NOT NULL DEFAULT '[]'"))
    print(f"players.opened_chests added: {added}")


if __name__ == "__main__":
    migrate()
