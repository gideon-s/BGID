#!/usr/bin/env python3
"""
Maps overhaul migration (handoff-11 Slice B): levels & z-floors.

Additive + idempotent (guards on PRAGMA / create_all-missing-only); preserves
accounts and the live world:
  - creates the `levels` table;
  - adds `rooms.level_id` (FK → levels.id, nullable) + `rooms.z` (default 0).

Existing rooms keep `level_id = NULL` until seed.py assigns them (each room → a
default single-floor level, or an authored multi-floor level like the Manor), so
the world is unchanged until levels are authored. Run this, then seed.py:

    python migrate_maps.py && python seed.py
"""
from sqlalchemy import text

from database import engine
import models  # noqa: F401 — registers Level on Base.metadata


def migrate() -> None:
    with engine.begin() as conn:
        # 1) levels table (create_all only makes missing tables).
        models.Base.metadata.create_all(bind=conn, tables=[models.Level.__table__])
        # 2) rooms.level_id / rooms.z
        rcols = {row[1] for row in conn.execute(text("PRAGMA table_info(rooms)"))}
        add_level = "level_id" not in rcols
        add_z = "z" not in rcols
        if add_level:
            conn.execute(text("ALTER TABLE rooms ADD COLUMN level_id INTEGER REFERENCES levels(id)"))
        if add_z:
            conn.execute(text("ALTER TABLE rooms ADD COLUMN z INTEGER NOT NULL DEFAULT 0"))
    print(f"levels ensured; rooms.level_id added: {add_level}; rooms.z added: {add_z}")


if __name__ == "__main__":
    migrate()
