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
        rusty = _get_or_create(db, Item, name="Rusty Key", defaults={
            "description": "Pitted iron, still turns.", "item_type": "key",
            "value": 1, "room_id": foyer.id, "is_movable": True, "is_usable": True,
            "glyph": "🔑", "tile_x": 3, "tile_y": 6,
        })
        # Phase 3: the key now sits on the Foyer floor as a grabbable ground item.
        # On an existing DB (pre-Phase-3) the row predates the glyph/tile columns,
        # so set them in place (idempotent — _get_or_create won't rewrite a hit).
        if rusty.room_id == foyer.id and rusty.tile_x is None:
            rusty.glyph, rusty.tile_x, rusty.tile_y = "🔑", 3, 6
            db.commit()

        # Starter gear on the Foyer floor (Phase 3). Walk onto a tile + grab.
        _get_or_create(db, Item, name="Iron Sword", defaults={
            "description": "A plain but honest blade.", "item_type": "weapon",
            "value": 10, "room_id": foyer.id, "glyph": "⚔️", "tile_x": 2, "tile_y": 1,
            "is_movable": True, "is_equippable": True, "equip_slot": "weapon",
            "attack_bonus": 1, "damage_bonus": 2,
        })
        armor = _get_or_create(db, Item, name="Leather Armor", defaults={
            "description": "Boiled hide; better than nothing.", "item_type": "armor",
            "value": 8, "room_id": foyer.id, "glyph": "🛡️", "tile_x": 7, "tile_y": 1,
            "is_movable": True, "is_equippable": True, "equip_slot": "torso",
            "defense_bonus": 2,
        })
        # In-place re-slot for a pre-charsheet row (was 'armor' → now 'torso').
        if armor.equip_slot == "armor":
            armor.equip_slot = "torso"; db.commit()
        # A few body-part pieces so the paperdoll is populated (head/hands/feet).
        _get_or_create(db, Item, name="Leather Cap", defaults={
            "description": "A snug boiled-leather cap.", "item_type": "armor",
            "value": 4, "room_id": foyer.id, "glyph": "🧢", "tile_x": 2, "tile_y": 6,
            "is_movable": True, "is_equippable": True, "equip_slot": "head",
            "defense_bonus": 1,
        })
        # Gloves and boots are now per-hand / per-foot (independent L/R slots).
        _get_or_create(db, Item, name="Leather Glove (L)", defaults={
            "description": "Worn but supple.", "item_type": "armor",
            "value": 2, "room_id": foyer.id, "glyph": "🧤", "tile_x": 8, "tile_y": 6,
            "is_movable": True, "is_equippable": True, "equip_slot": "left_hand",
            "defense_bonus": 1,
        })
        _get_or_create(db, Item, name="Leather Glove (R)", defaults={
            "description": "Worn but supple.", "item_type": "armor",
            "value": 2, "room_id": foyer.id, "glyph": "🧤", "tile_x": 9, "tile_y": 6,
            "is_movable": True, "is_equippable": True, "equip_slot": "right_hand",
            "defense_bonus": 1,
        })
        _get_or_create(db, Item, name="Worn Boot (L)", defaults={
            "description": "It's walked some miles.", "item_type": "armor",
            "value": 2, "room_id": foyer.id, "glyph": "🥾", "tile_x": 4, "tile_y": 6,
            "is_movable": True, "is_equippable": True, "equip_slot": "left_foot",
            "defense_bonus": 1,
        })
        _get_or_create(db, Item, name="Worn Boot (R)", defaults={
            "description": "It's walked some miles.", "item_type": "armor",
            "value": 2, "room_id": foyer.id, "glyph": "🥾", "tile_x": 5, "tile_y": 6,
            "is_movable": True, "is_equippable": True, "equip_slot": "right_foot",
            "defense_bonus": 1,
        })
        # A ring in the Cellar — the reward for braving the Rat past the locked door.
        _get_or_create(db, Item, name="Ring of Vigor", defaults={
            "description": "A warm iron band that steadies the hand.",
            "item_type": "ring", "value": 25, "room_id": cellar.id,
            "glyph": "💍", "tile_x": 2, "tile_y": 1,
            "is_movable": True, "is_equippable": True, "equip_slot": "ring",
            "attack_bonus": 1, "defense_bonus": 1,
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
        stool = _get_or_create(db, Item, name="Sturdy Stool", defaults={
            "description": "It wobbles but holds.", "item_type": "furniture",
            "room_id": foyer.id, "is_movable": False, "is_usable": True,
            "glyph": "🪑", "tile_x": 10, "tile_y": 1,
        })
        # In-place glyph/tile for a pre-Phase-3 Stool row (predates the columns,
        # so _get_or_create above is a no-op there) — same pattern as the key.
        if stool.tile_x is None:
            stool.glyph, stool.tile_x, stool.tile_y = "🪑", 10, 1
            db.commit()

        # Class-gear chest in the Great Hall. Immovable; opening it (the `open`
        # command / O key) grants the opener their class's starting kit, once per
        # character (see ItemService.open_chest + classes.starting_gear).
        _get_or_create(db, Item, name="Old Chest", defaults={
            "description": "A banded oak chest. It seems to hold something fitting "
                           "for each who opens it.",
            "item_type": "chest", "room_id": hall.id, "is_movable": False,
            "is_usable": True, "glyph": "🧰", "tile_x": 5, "tile_y": 1,
        })

        # Treasure in the Cellar (behind the locked door). A coin pile collects
        # straight into the wallet on pickup; gems are valued items you carry.
        # `value` is in COPPER (base-10: 100cp = 1gp). See currency.py.
        _get_or_create(db, Item, name="Pouch of Coins", defaults={
            "description": "Loose coins in a stained leather pouch.",
            "item_type": "coins", "value": 137, "room_id": cellar.id,
            "is_movable": True, "glyph": "🪙", "tile_x": 1, "tile_y": 3,
        })
        _get_or_create(db, Item, name="Garnet", defaults={
            "description": "A small, blood-red gem.", "item_type": "gem",
            "value": 50, "room_id": cellar.id, "is_movable": True,
            "glyph": "🔴", "tile_x": 2, "tile_y": 3,
        })
        _get_or_create(db, Item, name="Sapphire", defaults={
            "description": "A flawless blue stone, cool to the touch.",
            "item_type": "gem", "value": 250, "room_id": cellar.id,
            "is_movable": True, "glyph": "🔷", "tile_x": 5, "tile_y": 3,
        })

        # Room connections:
        #   Foyer <-> Great Hall (open, north/south)
        #   Foyer  -> Cellar (down stairs, LOCKED behind the Rusty Key) — the
        #            Cellar holds the Rat and the ring; Cellar -> Foyer (open up).
        # Phase 3 re-locks the down stairs now that the Rusty Key can be grabbed
        # off the Foyer floor (Phase 2 had left it open for lack of pickup).
        _ensure_exit(db, foyer.id, "north", hall.id, description="an archway")
        _ensure_exit(db, hall.id, "south", foyer.id, description="an archway")
        _ensure_exit(db, foyer.id, "down", cellar.id, description="stairs down to the cellar",
                     is_locked=True, key_item_id=rusty.id)
        _ensure_exit(db, cellar.id, "up", foyer.id, description="stairs up to the foyer")
        # In-place re-lock for an existing DB (the Phase-2 row exists unlocked, so
        # _ensure_exit above is a no-op there — update the row directly).
        down = db.query(RoomExit).filter_by(from_room_id=foyer.id, direction="down").first()
        if down is not None and not down.is_locked:
            down.is_locked, down.key_item_id = True, rusty.id
            db.commit()

        print("Seeded.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
