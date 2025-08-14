#!/usr/bin/env python3
"""
Seed script to populate the database with initial data
"""
from database import SessionLocal, engine, Base
from models import Room, Player, Item, Npc, NpcReaction

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# Create rooms
foyer = Room(name="Foyer", description="A grand entrance hall.")
hall = Room(name="Great Hall", description="A vast chamber with high ceilings.")

db.add_all([foyer, hall])
db.commit()

# Example player/NPC/items if missing
if not db.query(Player).filter_by(name="Bryan").first():
    db.add(Player(id=1, name="Bryan", room_id=foyer.id))

caretaker = db.query(Npc).filter_by(name="Caretaker").first()
if not caretaker:
    caretaker = Npc(
        name="Caretaker",
        description="A curt, watchful presence.",
        npc_type="caretaker",
        room_id=foyer.id,
        is_friendly=False,
        combat_enabled=True,
        cha=8, wis=12
    )
    db.add(caretaker)

key = db.query(Item).filter_by(name="Rusty Key").first()
if not key:
    key = Item(
        name="Rusty Key",
        description="Pitted iron, still turns.",
        item_type="key",
        value=1,
        room_id=foyer.id,
        is_movable=True,
        is_usable=True
    )
    db.add(key)

# Non-combatant & furniture
inn = db.query(Npc).filter_by(name="Innkeeper").first()
if not inn:
    inn = Npc(
        name="Innkeeper",
        description="Polite, harried, not interested in brawls.",
        npc_type="innkeeper",
        room_id=foyer.id,
        combat_enabled=False,
        cha=14, wis=12
    )
    db.add(inn)

stool = db.query(Item).filter_by(name="Sturdy Stool").first()
if not stool:
    stool = Item(
        name="Sturdy Stool",
        description="It wobbles but holds.",
        item_type="furniture",
        room_id=foyer.id,
        is_movable=False,
        is_usable=True
    )
    db.add(stool)

db.commit()

# Baseline reaction Caretaker -> Player 1
p1 = db.query(Player).get(1)
if caretaker and p1:
    existing = db.query(NpcReaction).filter_by(npc_id=caretaker.id, player_id=p1.id).first()
    if not existing:
        db.add(NpcReaction(npc_id=caretaker.id, player_id=p1.id, threat=10, attraction=5, arousal=0, aggression=5))
        db.commit()

db.close()
print("Seeded.")
