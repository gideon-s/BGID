#!/usr/bin/env python3
"""
Phase 4 (classes, spells & mana) — additive column migration for `players`.

Adds char_class / mana / max_mana. Existing characters default to the 'wanderer'
class (melee, 0 mana) so they keep working unchanged; new characters pick a real
class at creation. SQLite takes `ALTER TABLE ... ADD COLUMN` with a default
without rewriting rows, preserving all accounts/characters. Idempotent: guards on
`PRAGMA table_info(players)`, so it's safe to run repeatedly.

    python migrate_phase4.py

After running, restart the service so world.load() / the regen tick see the new
columns. (No seed change is required for Phase 4.)
"""
from sqlalchemy import text
from database import engine

NEW_COLUMNS = {
    "char_class": "VARCHAR(20) NOT NULL DEFAULT 'wanderer'",
    "mana": "INTEGER NOT NULL DEFAULT 0",
    "max_mana": "INTEGER NOT NULL DEFAULT 0",
}


def migrate() -> None:
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(players)"))}
        added = []
        for col, ddl in NEW_COLUMNS.items():
            if col in existing:
                continue
            conn.execute(text(f"ALTER TABLE players ADD COLUMN {col} {ddl}"))
            added.append(col)
    if added:
        print(f"Added columns to players: {', '.join(added)}")
    else:
        print("players already has all Phase 4 columns — nothing to do.")


if __name__ == "__main__":
    migrate()
