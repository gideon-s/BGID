#!/usr/bin/env python3
"""
One-off content build: stock the Labyrinth with classic fantasy monsters.

A small **bestiary** (goblins, orcs, gnolls, slimes, kobolds, skeletons, zombies,
giant rats, cave spiders, ogres) is scattered through the Labyrinth level. The
mob's danger scales with how deep its room is from the entrance (BFS depth):
weak vermin near the mouth, orcs/ogres in the depths. Each mob is a normal
hostile (aggro / path / melee, respawns at home, drops loot via loot.py + grants
XP). Cave spiders are venomous (npc_type 'spider' → Poison, see debuffs).

Idempotent: if the Labyrinth already has NPCs, it does nothing. Deterministic.
Run as the DB owner, then restart the service:

    python populate_labyrinth.py
"""
import random

import database
import models

LEVEL_NAME = "The Labyrinth"
SEED = 20260623
DENSITY = 0.55          # fraction of rooms that get a monster

# npc_type -> archetype. str/dex/con feed the D20 resolver; hp = health pool;
# aggro = chase radius; wanders = idle ambling.
BESTIARY = {
    "giant_rat": dict(name="Giant Rat", glyph="🐀", str=9,  dex=13, con=9,  hp=5,  aggro=5, wanders=True),
    "kobold":    dict(name="Kobold",    glyph="🦎", str=9,  dex=12, con=9,  hp=6,  aggro=6, wanders=True),
    "goblin":    dict(name="Goblin",    glyph="👺", str=11, dex=13, con=10, hp=8,  aggro=7, wanders=True),
    "slime":     dict(name="Green Slime", glyph="🟢", str=12, dex=7, con=14, hp=14, aggro=4, wanders=False),
    "spider":    dict(name="Cave Spider", glyph="🕷️", str=11, dex=14, con=10, hp=10, aggro=6, wanders=True),
    "skeleton":  dict(name="Skeleton",  glyph="💀", str=12, dex=11, con=10, hp=10, aggro=6, wanders=False),
    "zombie":    dict(name="Zombie",    glyph="🧟", str=13, dex=7,  con=14, hp=16, aggro=5, wanders=False),
    "gnoll":     dict(name="Gnoll",     glyph="🐺", str=13, dex=12, con=12, hp=14, aggro=8, wanders=True),
    "orc":       dict(name="Orc",       glyph="🧌", str=15, dex=11, con=13, hp=18, aggro=7, wanders=True),
    "ogre":      dict(name="Ogre",      glyph="👹", str=17, dex=9,  con=15, hp=28, aggro=7, wanders=False),
}

# Depth tiers (near / mid / deep) → weighted monster pools.
TIERS = [
    [("giant_rat", 4), ("kobold", 4), ("goblin", 3), ("spider", 2), ("slime", 1)],
    [("goblin", 3), ("spider", 2), ("skeleton", 3), ("gnoll", 2), ("slime", 2), ("zombie", 2)],
    [("gnoll", 3), ("orc", 4), ("skeleton", 2), ("zombie", 2), ("ogre", 1)],
]


def _weighted(pool, rng):
    total = sum(w for _, w in pool)
    r = rng.uniform(0, total)
    upto = 0
    for key, w in pool:
        upto += w
        if r <= upto:
            return key
    return pool[-1][0]


def build():
    db = database.SessionLocal()
    try:
        level = db.query(models.Level).filter_by(name=LEVEL_NAME).first()
        if level is None:
            print(f"'{LEVEL_NAME}' not found — run add_labyrinth.py first.")
            return
        rooms = db.query(models.Room).filter_by(level_id=level.id).all()
        room_ids = {r.id for r in rooms}
        existing = (db.query(models.Npc)
                    .filter(models.Npc.room_id.in_(room_ids)).count())
        if existing:
            print(f"Labyrinth already has {existing} NPCs — nothing to do.")
            return

        # BFS depth from the entrance (a labyrinth room linked from the Great Hall).
        hall = db.query(models.Room).filter_by(name="Great Hall").first()
        exits = db.query(models.RoomExit).all()
        adj = {}
        for x in exits:
            adj.setdefault(x.from_room_id, []).append(x.to_room_id)
        entrance = next((x.to_room_id for x in exits
                         if x.from_room_id == hall.id and x.to_room_id in room_ids), None)
        depth = {}
        if entrance is not None:
            depth[entrance] = 0
            q = [entrance]
            while q:
                n = q.pop(0)
                for m in adj.get(n, []):
                    if m in room_ids and m not in depth:
                        depth[m] = depth[n] + 1
                        q.append(m)
        maxd = max(depth.values()) if depth else 1

        rng = random.Random(SEED)
        placed = {}
        for room in rooms:
            if rng.random() > DENSITY:
                continue
            d = depth.get(room.id, 0)
            tier = 0 if d <= maxd / 3 else (1 if d <= 2 * maxd / 3 else 2)
            ntype = _weighted(TIERS[tier], rng)
            b = BESTIARY[ntype]
            sx = room.spawn_x if room.spawn_x is not None else room.width // 2
            sy = room.spawn_y if room.spawn_y is not None else room.height // 2
            db.add(models.Npc(
                name=b["name"], description=f"A {b['name'].lower()} of the labyrinth.",
                npc_type=ntype, room_id=room.id, combat_enabled=True, is_hostile=True,
                is_friendly=False, aggro_radius=b["aggro"], wanders=b["wanders"],
                glyph=b["glyph"], home_x=sx, home_y=sy,
                health=b["hp"], max_health=b["hp"],
                str=b["str"], dex=b["dex"], con=b["con"]))
            placed[ntype] = placed.get(ntype, 0) + 1
        db.commit()
        total = sum(placed.values())
        print(f"Placed {total} monsters across the Labyrinth ({len(rooms)} rooms):")
        for k in sorted(placed):
            print(f"  {placed[k]:>2}  {BESTIARY[k]['glyph']} {BESTIARY[k]['name']}")
    finally:
        db.close()


if __name__ == "__main__":
    build()
