#!/usr/bin/env python3
"""
Seed the database with initial data.

Idempotent: safe to run repeatedly (won't duplicate rows). Run directly:

    python seed.py
"""
from database import SessionLocal, engine, Base
from models import Room, Player, Item, Npc, NpcReaction


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


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        foyer = _get_or_create(db, Room, name="Foyer",
                               defaults={"description": "A grand entrance hall."})
        _get_or_create(db, Room, name="Great Hall",
                       defaults={"description": "A vast chamber with high ceilings."})

        _get_or_create(db, Player, name="Bryan", defaults={"id": 1, "room_id": foyer.id})

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

        # Baseline reaction Caretaker -> Bryan
        bryan = db.query(Player).filter_by(name="Bryan").first()
        if not db.query(NpcReaction).filter_by(npc_id=caretaker.id, player_id=bryan.id).first():
            db.add(NpcReaction(npc_id=caretaker.id, player_id=bryan.id,
                               threat=10, attraction=5, arousal=0, aggression=5))
            db.commit()

        print("Seeded.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
