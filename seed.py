#!/usr/bin/env python3
"""
Seed the database with initial data.

Idempotent: safe to run repeatedly (won't duplicate rows). Run directly:

    python seed.py
"""
from database import SessionLocal, engine, Base
from models import Room, Player, Item, Npc, NpcReaction, RoomExit

# Authored tiled zones (Phase 1 palette + Phase 2 transitions). Glyphs: '#' wall,
# '.' floor, '+' door (on a border → that wall's cardinal exit), 'o' pillar,
# '~' water, '>'/'<' stairs down/up. Doors/stairs are aligned to the seeded
# RoomExits so stepping onto them moves you between zones.
#
# Foyer (12x9): north door (5,0) → Great Hall; down stairs (9,3) → Cellar
# (locked, Rusty Key). Spawn (3,4); Innkeeper (8,2), hostile Cellar Rat (9,6).
FOYER_TILES = "\n".join([
    "#####+######",
    "#..........#",
    "#..o.....o.#",
    "#........>.#",
    "#..........#",
    "#....oo....#",
    "#..........#",
    "#~~........#",
    "############",
])
FOYER_W, FOYER_H = 12, 9
FOYER_SPAWN = (3, 4)

# Great Hall (11x7): south door (5,6) → Foyer.
HALL_TILES = "\n".join([
    "###########",
    "#.........#",
    "#.........#",
    "#.........#",
    "#.........#",
    "#.........#",
    "#####+#####",
])
HALL_W, HALL_H = 11, 7
HALL_SPAWN = (5, 3)

# Cellar (8x5): up stairs (4,2) → Foyer.
CELLAR_TILES = "\n".join([
    "########",
    "#......#",
    "#...<..#",
    "#......#",
    "########",
])
CELLAR_W, CELLAR_H = 8, 5
CELLAR_SPAWN = (4, 3)


def _get_or_create(db, model, defaults=None, **filters):
    """Return an existing row matching `filters`, or create one with
    `filters` + `defaults`."""
    obj = db.query(model).filter_by(**filters).first()
    if obj is not None:
        return obj
    obj = model(**{**filters, **(defaults or {})})
    db.add(obj)
    db.commit()
    return obj


def _ensure_exit(db, from_id, direction, to_id, description="", is_locked=False, key_item_id=None):
    """Idempotently create a one-way exit (from_id --direction--> to_id)."""
    if db.query(RoomExit).filter_by(from_room_id=from_id, direction=direction).first():
        return
    db.add(RoomExit(from_room_id=from_id, to_room_id=to_id, direction=direction,
                    description=description, is_locked=is_locked, key_item_id=key_item_id))
    db.commit()


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        foyer = _get_or_create(db, Room, name="Foyer", defaults={
            "description": "A grand entrance hall.",
            "width": FOYER_W, "height": FOYER_H, "tiles": FOYER_TILES,
            "spawn_x": FOYER_SPAWN[0], "spawn_y": FOYER_SPAWN[1],
        })
        hall = _get_or_create(db, Room, name="Great Hall", defaults={
            "description": "A vast chamber with high ceilings.",
            "width": HALL_W, "height": HALL_H, "tiles": HALL_TILES,
            "spawn_x": HALL_SPAWN[0], "spawn_y": HALL_SPAWN[1],
        })
        cellar = _get_or_create(db, Room, name="Cellar", defaults={
            "description": "A cramped, musty cellar below the foyer.",
            "width": CELLAR_W, "height": CELLAR_H, "tiles": CELLAR_TILES,
            "spawn_x": CELLAR_SPAWN[0], "spawn_y": CELLAR_SPAWN[1],
        })

        # No player characters are seeded: every character now belongs to a
        # registered account (POST /characters). The first account to register
        # auto-becomes admin (see auth_service._resolve_role).

        caretaker = _get_or_create(db, Npc, name="Caretaker", defaults={
            "description": "A curt, watchful presence.", "npc_type": "caretaker",
            "room_id": foyer.id, "is_friendly": False, "combat_enabled": True,
            "is_hostile": False, "glyph": "🧹", "home_x": 2, "home_y": 2,
            "cha": 8, "wis": 12,
        })
        _get_or_create(db, Item, name="Rusty Key", defaults={
            "description": "Pitted iron, still turns.", "item_type": "key",
            "value": 1, "room_id": foyer.id, "is_movable": True, "is_usable": True,
        })

        # Non-combatant & furniture
        _get_or_create(db, Npc, name="Innkeeper", defaults={
            "description": "Polite, harried, not interested in brawls.",
            "npc_type": "innkeeper", "room_id": foyer.id,
            "combat_enabled": False, "is_hostile": False,
            "glyph": "🧑", "home_x": 8, "home_y": 2, "cha": 14, "wis": 12,
        })

        # The hostile mob lives in the Cellar, so the Foyer stays a safe
        # arrival/respawn hub. It aggros, paths toward players, and talks smack.
        _get_or_create(db, Npc, name="Cellar Rat", defaults={
            "description": "A mangy, snarling rat the size of a dog.",
            "npc_type": "combat_mob", "room_id": cellar.id,
            "combat_enabled": True, "is_hostile": True, "aggro_radius": 6,
            "glyph": "🐀", "home_x": 6, "home_y": 1,
            "str": 12, "dex": 12, "con": 10, "health": 8, "max_health": 8,
        })
        _get_or_create(db, Item, name="Sturdy Stool", defaults={
            "description": "It wobbles but holds.", "item_type": "furniture",
            "room_id": foyer.id, "is_movable": False, "is_usable": True,
        })

        # Room connections:
        #   Foyer <-> Great Hall (open, north/south)
        #   Foyer <-> Cellar (open, down/up stairs) — the Cellar holds the Rat.
        # The down stairs are unlocked for now: there's no in-game item pickup
        # yet (Phase 3), so a locked Cellar would seal the Rat away unfightable.
        # Re-lock behind the Rusty Key once inventory lands.
        _ensure_exit(db, foyer.id, "north", hall.id, description="an archway")
        _ensure_exit(db, hall.id, "south", foyer.id, description="an archway")
        _ensure_exit(db, foyer.id, "down", cellar.id, description="stairs down to the cellar")
        _ensure_exit(db, cellar.id, "up", foyer.id, description="stairs up to the foyer")

        print("Seeded.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
