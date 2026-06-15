#!/usr/bin/env python3
"""
Race + independent-limb-slots migration.

- Adds `players.race` (default 'human').
- Re-slots the previous single limb slots to their left-side equivalent so any
  existing armour lands somewhere sensible on the new L/R paperdoll
  (head/torso/pelvis are unchanged).

Additive + idempotent (guards on PRAGMA table_info); preserves accounts/items.
Run, then restart the service.

    python migrate_race_slots.py
"""
from sqlalchemy import text
from database import engine

# old single slot -> new sided slot (left side by convention).
SLOT_RENAMES = {
    "upper_arms": "left_upper_arm",
    "lower_arms": "left_lower_arm",
    "hands": "left_hand",
    "upper_legs": "left_upper_leg",
    "lower_legs": "left_lower_leg",
    "feet": "left_foot",
}


def migrate() -> None:
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(players)"))}
        added = "race" not in cols
        if added:
            conn.execute(text(
                "ALTER TABLE players ADD COLUMN race VARCHAR(30) NOT NULL DEFAULT 'human'"))
        moved = 0
        for old, new in SLOT_RENAMES.items():
            moved += conn.execute(
                text("UPDATE items SET equip_slot=:new WHERE equip_slot=:old"),
                {"new": new, "old": old},
            ).rowcount
    print(f"players.race added: {added}")
    print(f"Re-slotted {moved} limb item(s) to left-side slots.")


if __name__ == "__main__":
    migrate()
