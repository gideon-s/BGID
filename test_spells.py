"""Phase 4 — classes, spells & mana.

Test world (conftest): Foyer (8x6), Bryan (player 1) spawns (2,2); the Caretaker
(hostile combat mob) sits at (3,2), the Innkeeper at (5,4). The combat tick is
disabled in tests, so casts resolve in isolation. Bryan is a `wanderer` by
default — tests that cast reclass him first (as the gate would at creation).
"""
import asyncio

import classes
import spells
import casting
import combat
import game_loop
import models
from world import world


def _reclass(db, player_id, class_id):
    """Stamp a class onto an existing character (abilities + full mana), as
    CharacterService.create does — for tests that need a caster."""
    p = db.query(models.Player).get(player_id)
    cdef = classes.get_class(class_id)
    p.char_class = class_id
    p.glyph = cdef["glyph"]
    p.max_mana = cdef["max_mana"]
    p.mana = cdef["max_mana"]
    for ability, score in cdef["abilities"].items():
        setattr(p, ability, score)
    db.commit()


def _npc(db, name):
    return db.query(models.Npc).filter_by(name=name).first()


# ---------- registries ----------
def test_registry_integrity():
    for cid, c in classes.CLASSES.items():
        assert isinstance(c["max_mana"], int) and c["max_mana"] >= 0
        for sid in c["spells"]:
            sp = spells.get_spell(sid)
            assert sp is not None, f"{cid} -> missing spell {sid}"
            assert sp["cost"] >= 0 and sp["shape"] in {"self", "bolt", "blast"}
    assert set(classes.SELECTABLE) == {"warrior", "mage", "cleric", "rogue"}
    assert "wanderer" not in classes.SELECTABLE


# ---------- class creation ----------
def test_create_stamps_class(db_session):
    import auth_service
    intruder = db_session.query(models.User).filter_by(username="intruder").first()
    p = auth_service.CharacterService.create(db_session, intruder, "Gandalf", "mage")
    assert p.char_class == "mage" and p.max_mana == 30 and p.mana == 30
    assert p.glyph == "🧙" and p.intel == 15


def test_create_rejects_unknown_class():
    import auth_schemas
    import pytest
    with pytest.raises(Exception):
        auth_schemas.CharacterCreate(name="Bad", char_class="lich")


# ---------- LOS & radius ----------
def test_line_of_sight_clear_and_blocked(db_session):
    world.load()
    node = world.rooms[1]
    assert world.line_of_sight(1, (1, 1), (6, 1)) is True       # open row
    node.tiles[2] = "#..#...#"                                  # wall at (3,2)
    assert world.line_of_sight(1, (1, 2), (6, 2)) is False      # blocked between
    assert world.line_of_sight(1, (1, 1), (6, 1)) is True       # row 1 unaffected


def test_tiles_in_radius_bounds(db_session):
    world.load()
    tiles = world.tiles_in_radius(1, (3, 2), 1)
    assert (3, 2) in tiles and all(world.is_walkable(1, x, y) for x, y in tiles)
    assert all(abs(x - 3) <= 1 and abs(y - 2) <= 1 for x, y in tiles)


# ---------- casting (direct; manager calls no-op without connections) ----------
def _setup_caster(db_session, class_id="mage"):
    _reclass(db_session, 1, class_id)
    world.load()
    world.place_player(1, 1)            # spawn (2,2); Caretaker at home (3,2)


def test_firebolt_damages_target_and_spends_mana(db_session):
    _setup_caster(db_session, "mage")
    rat = _npc(db_session, "Caretaker")
    asyncio.run(casting.resolve_cast(1, 1, "firebolt", 3, 2))
    db_session.expire_all()
    assert db_session.query(models.Npc).get(rat.id).health < rat.max_health
    assert db_session.query(models.Player).get(1).mana == 30 - 3


def test_insufficient_mana_no_spend_no_damage(db_session):
    _setup_caster(db_session, "mage")
    p = db_session.query(models.Player).get(1); p.mana = 1; db_session.commit()
    world.load(); world.place_player(1, 1)
    rat = _npc(db_session, "Caretaker"); before = rat.health
    asyncio.run(casting.resolve_cast(1, 1, "firebolt", 3, 2))
    db_session.expire_all()
    assert db_session.query(models.Npc).get(rat.id).health == before
    assert db_session.query(models.Player).get(1).mana == 1


def test_cooldown_blocks_immediate_recast(db_session):
    _setup_caster(db_session, "mage")
    asyncio.run(casting.resolve_cast(1, 1, "firebolt", 3, 2))
    asyncio.run(casting.resolve_cast(1, 1, "firebolt", 3, 2))   # on cooldown → no spend
    db_session.expire_all()
    assert db_session.query(models.Player).get(1).mana == 30 - 3   # only one cast paid


def test_out_of_range_rejected(db_session):
    _setup_caster(db_session, "rogue")                 # backstab range 1
    rat = _npc(db_session, "Caretaker"); before = rat.health
    # Caretaker at (3,2); cast at (5,4) (Innkeeper tile) is >1 away → out of range.
    asyncio.run(casting.resolve_cast(1, 1, "backstab", 5, 4))
    db_session.expire_all()
    assert db_session.query(models.Player).get(1).mana == 16        # no spend
    assert db_session.query(models.Npc).get(rat.id).health == before


def test_no_line_of_sight_rejected(db_session):
    _setup_caster(db_session, "mage")
    world.rooms[1].tiles[2] = "#..#...#"               # wall at (3,2) — onto the target
    # Target a tile beyond the wall from the caster: caster (2,2) → (5,2) crosses (3,2).
    asyncio.run(casting.resolve_cast(1, 1, "firebolt", 5, 2))
    db_session.expire_all()
    assert db_session.query(models.Player).get(1).mana == 30        # no spend


def test_heal_restores_hp_and_costs_mana(db_session):
    _setup_caster(db_session, "cleric")
    p = db_session.query(models.Player).get(1); p.health = 3; db_session.commit()
    world.load(); world.place_player(1, 1)
    asyncio.run(casting.resolve_cast(1, 1, "heal", None, None))
    db_session.expire_all()
    p2 = db_session.query(models.Player).get(1)
    assert p2.health > 3 and p2.mana == 24 - 5


def test_blast_hits_multiple(db_session):
    # A second mob adjacent to the Caretaker so a radius-1 blast catches both.
    db_session.add(models.Npc(name="Rat Two", npc_type="combat_mob", room_id=1,
                              combat_enabled=True, is_hostile=True, glyph="🐀",
                              home_x=4, home_y=2))
    db_session.commit()
    _setup_caster(db_session, "mage")
    a, b = _npc(db_session, "Caretaker"), _npc(db_session, "Rat Two")
    ha, hb = a.health, b.health
    asyncio.run(casting.resolve_cast(1, 1, "frost_blast", 3, 2))   # covers (3,2)+(4,2)
    db_session.expire_all()
    assert db_session.query(models.Npc).get(a.id).health < ha
    assert db_session.query(models.Npc).get(b.id).health < hb


def test_spell_kill_removes_mob_and_schedules_respawn(db_session):
    _setup_caster(db_session, "mage")
    rat = _npc(db_session, "Caretaker"); rat.health = 1; db_session.commit()
    rid = rat.id
    asyncio.run(casting.resolve_cast(1, 1, "firebolt", 3, 2))
    assert world.position_of("npc", 1, rid) is None        # gone from the map
    assert rid in world.pending_respawns                    # hostile → respawn queued


def test_mana_regen_on_tick(db_session):
    _reclass(db_session, 1, "mage")
    p = db_session.query(models.Player).get(1); p.mana = 5; db_session.commit()
    world.load()
    world.enter_world(1)                 # mark online so the regen tick sees them
    asyncio.run(game_loop._tick_once())
    db_session.expire_all()
    assert db_session.query(models.Player).get(1).mana == 5 + 3   # mage regen = 3


# ---------- over the socket (main.py command wiring) ----------
def _drain_until(ws, pred, tries=18):
    for _ in range(tries):
        m = ws.receive_json()
        if pred(m):
            return m
    return None


def test_cast_over_socket(client, token, db_session):
    _reclass(db_session, 1, "mage")
    rat = _npc(db_session, "Caretaker")
    with client.websocket_connect(f"/ws/1?token={token}") as ws:
        ws.receive_json()                                  # zone_state (Foyer)
        ws.send_json({"cmd": "spells"})
        sb = _drain_until(ws, lambda m: m["event"] == "spellbook")
        assert sb and any(s["id"] == "firebolt" for s in sb["spells"])
        ws.send_json({"cmd": "cast", "spell_id": "firebolt", "x": 3, "y": 2})
        fx = _drain_until(ws, lambda m: m["event"] == "spell_cast")
        assert fx and fx["spell"] == "firebolt"
        hit = _drain_until(ws, lambda m: m["event"] == "combat" and m["target_id"] == rat.id)
        assert hit and hit["damage"] >= 1


def test_wanderer_cannot_cast(db_session):
    world.load(); world.place_player(1, 1)               # Bryan stays a wanderer
    asyncio.run(casting.resolve_cast(1, 1, "firebolt", 3, 2))
    db_session.expire_all()
    rat = _npc(db_session, "Caretaker")
    assert rat.health == rat.max_health                  # nothing happened
