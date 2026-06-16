#!/usr/bin/env python3
"""
Coin-currency migration.

Adds `players.coins` (the wallet, in copper; default 0). Base-10 denominations
are derived for display (see currency.py) — no per-coin columns.

Additive + idempotent (guards on PRAGMA table_info); preserves accounts/items.
The seeded coin pile + gems are added by seed.py (idempotent). Run this, then
seed.py, then restart:

    python migrate_currency.py && python seed.py
"""
from sqlalchemy import text

from database import engine


def migrate() -> None:
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(players)"))}
        added = "coins" not in cols
        if added:
            conn.execute(text(
                "ALTER TABLE players ADD COLUMN coins INTEGER NOT NULL DEFAULT 0"))
    print(f"players.coins added: {added}")


if __name__ == "__main__":
    migrate()
