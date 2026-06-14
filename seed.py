#!/usr/bin/env python3
"""
Seed the database with initial data.

Idempotent: safe to run repeatedly (won't duplicate rows). Run directly:

    python seed.py
"""
from database import SessionLocal, engine, Base
from models import Room, Player, Item, Npc, NpcReaction, RoomExit

# Authored 12x9 tiled Foyer (Phase 1 graphical overhaul). A non-rectangular
# hall showing off the tile palette: '#' wall, '.' floor, '+' door, 'o' pillar
# (solid column), '~' water (a corner pool). The top-right and bottom-right
# corners are chamfered so it isn't a plain box. Players spawn at (3, 4); the
# Innkeeper (8, 2) and hostile Cellar Rat (9, 6) sit on open floor.
FOYER_TILES = "\n".join([
    "############",
    "#.........##",
    "#..o.....o.#",
    "#..........#",
    "#..........#",
    "#....oo....#",
    "#.........+#",
    "#~~.......##",
    "#####++#####",
])
FOYER_W, FOYER_H = 12, 9
FOYER_SPAWN = (3, 4)


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
        hall = _get_or_create(db, Room, name="Great Hall",
                              defaults={"description": "A vast chamber with high ceilings."})
        cellar = _get_or_create(db, Room, name="Cellar",
                                defaults={"description": "A cramped, musty cellar below the foyer."})

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

        # The Phase 1 hostile mob: aggros, paths toward players, talks smack.
        _get_or_create(db, Npc, name="Cellar Rat", defaults={
            "description": "A mangy, snarling rat the size of a dog.",
            "npc_type": "combat_mob", "room_id": foyer.id,
            "combat_enabled": True, "is_hostile": True, "aggro_radius": 6,
            "glyph": "🐀", "home_x": 9, "home_y": 6,
            "str": 12, "dex": 12, "con": 10, "health": 8, "max_health": 8,
        })
        _get_or_create(db, Item, name="Sturdy Stool", defaults={
            "description": "It wobbles but holds.", "item_type": "furniture",
            "room_id": foyer.id, "is_movable": False, "is_usable": True,
        })

        # Room connections:
        #   Foyer <-> Great Hall (open, north/south)
        #   Foyer  -> Cellar via a locked door (down), needs the Rusty Key
        #   Cellar -> Foyer (up, open)
        key = db.query(Item).filter_by(name="Rusty Key").first()
        _ensure_exit(db, foyer.id, "north", hall.id, description="an archway")
        _ensure_exit(db, hall.id, "south", foyer.id, description="an archway")
        _ensure_exit(db, foyer.id, "down", cellar.id, description="a heavy cellar door",
                     is_locked=True, key_item_id=key.id if key else None)
        _ensure_exit(db, cellar.id, "up", foyer.id, description="stairs up to the foyer")

        print("Seeded.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
