#!/usr/bin/env python3
"""
Content config-layer migration (handoff-10 §1).

Creates the `content` table — editable overrides that overlay the authored code
registries (spells/potions/debuffs/gear). Additive + idempotent (create_all only
makes the table if missing); accounts and the live world are untouched, and an
empty table means pure code defaults. Run this, then restart:

    python migrate_content.py
"""
from database import engine
import models  # noqa: F401 — registers Content on Base.metadata


def migrate() -> None:
    models.Base.metadata.create_all(bind=engine, tables=[models.Content.__table__])
    print("content table ensured")


if __name__ == "__main__":
    migrate()
