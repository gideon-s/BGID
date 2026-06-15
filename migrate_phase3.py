#!/usr/bin/env python3
"""
Phase 3 (inventory & equipment) — additive column migration for `items`.

SQLite takes `ALTER TABLE ... ADD COLUMN` with a default without rewriting rows,
so this preserves all existing data (accounts, characters, game.db). Idempotent:
it checks `PRAGMA table_info(items)` and only adds columns that are missing, so
it's safe to run repeatedly.

    python migrate_phase3.py        # uses DATABASE_URL / the app's engine

After running, `python seed.py` adds the new ground items + re-locks the Cellar,
then restart the service so world.load() picks everything up.
"""
from sqlalchemy import text
from database import engine

# column name -> SQL type/default clause for ADD COLUMN
NEW_COLUMNS = {
    "glyph": "VARCHAR(8) NOT NULL DEFAULT '📦'",
    "tile_x": "INTEGER",
    "tile_y": "INTEGER",
    "equip_slot": "VARCHAR(20)",
    "equipped": "BOOLEAN NOT NULL DEFAULT 0",
    "attack_bonus": "INTEGER NOT NULL DEFAULT 0",
    "defense_bonus": "INTEGER NOT NULL DEFAULT 0",
    "damage_bonus": "INTEGER NOT NULL DEFAULT 0",
}


def migrate() -> None:
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(items)"))}
        added = []
        for col, ddl in NEW_COLUMNS.items():
            if col in existing:
                continue
            conn.execute(text(f"ALTER TABLE items ADD COLUMN {col} {ddl}"))
            added.append(col)
    if added:
        print(f"Added columns to items: {', '.join(added)}")
    else:
        print("items already has all Phase 3 columns — nothing to do.")


if __name__ == "__main__":
    migrate()
