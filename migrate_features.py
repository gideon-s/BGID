#!/usr/bin/env python3
"""
Traps & environments migration (handoff-09).

Additive + idempotent (guards on PRAGMA / sqlite_master); preserves accounts:
  - creates the `room_features` table (per-tile traps/signs/spawners/kegs);
  - adds `rooms.room_type` (default 'dungeon') + `rooms.is_safe` (default 0);
  - adds `npcs.wanders` (default 0).

The features themselves + sanctuary/tavern flags are (idempotently) seeded by
seed.py. Run this, then seed.py, then restart:

    python migrate_features.py && python seed.py
"""
from sqlalchemy import text

from database import engine
import models  # noqa: F401 — registers RoomFeature on Base.metadata


def migrate() -> None:
    with engine.begin() as conn:
        # 1) room_features table (create_all only makes missing tables).
        models.Base.metadata.create_all(bind=conn, tables=[models.RoomFeature.__table__])
        # 2) rooms.room_type / rooms.is_safe
        rcols = {row[1] for row in conn.execute(text("PRAGMA table_info(rooms)"))}
        add_rt = "room_type" not in rcols
        add_safe = "is_safe" not in rcols
        if add_rt:
            conn.execute(text(
                "ALTER TABLE rooms ADD COLUMN room_type TEXT NOT NULL DEFAULT 'dungeon'"))
        if add_safe:
            conn.execute(text(
                "ALTER TABLE rooms ADD COLUMN is_safe BOOLEAN NOT NULL DEFAULT 0"))
        # 3) npcs.wanders
        ncols = {row[1] for row in conn.execute(text("PRAGMA table_info(npcs)"))}
        add_w = "wanders" not in ncols
        if add_w:
            conn.execute(text(
                "ALTER TABLE npcs ADD COLUMN wanders BOOLEAN NOT NULL DEFAULT 0"))
    print(f"room_features ensured; rooms.room_type added: {add_rt}; "
          f"rooms.is_safe added: {add_safe}; npcs.wanders added: {add_w}")


if __name__ == "__main__":
    migrate()
