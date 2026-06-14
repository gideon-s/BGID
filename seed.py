#!/usr/bin/env python3
"""
Seed the database with initial data.

Idempotent: safe to run repeatedly (won't duplicate rows). Run directly:

    python seed.py
"""
from database import SessionLocal, engine, Base
from models import Room, Player, Item, Npc, NpcReaction, RoomExit


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
        foyer = _get_or_create(db, Room, name="Foyer",
                               defaults={"description": "A grand entrance hall."})
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
            "combat_enabled": False, "cha": 14, "wis": 12,
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
