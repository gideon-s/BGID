#!/usr/bin/env python3
"""
Character-sheet migration — gender/skills columns on `players`, and a one-time
rename of the legacy 'armor' equip slot to 'torso' so existing armour lands in
the body-part paperdoll.

Additive + idempotent (guards on PRAGMA table_info); preserves all accounts and
characters. Existing characters get gender 'none' and empty skills until edited
or re-rolled. Run, then restart the service.

    python migrate_charsheet.py
"""
from sqlalchemy import text
from database import engine

NEW_COLUMNS = {
    "gender": "VARCHAR(50) NOT NULL DEFAULT ''",
    "skills": "TEXT NOT NULL DEFAULT '{}'",
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
        # Legacy 'armor' slot -> 'torso' (the body paperdoll's chest box).
        moved = conn.execute(
            text("UPDATE items SET equip_slot='torso' WHERE equip_slot='armor'")
        ).rowcount
    print(f"Added columns to players: {', '.join(added) or '(none)'}")
    print(f"Re-slotted {moved} 'armor' item(s) to 'torso'.")


if __name__ == "__main__":
    migrate()
