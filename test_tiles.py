"""Tile layer unit tests (Phase 1 graphical overhaul).

Covers the in-memory tile model directly (walkability, occupancy, try_step,
pathing, zone snapshot) plus the mob-AI tick and the smack-talk fallback —
without standing up a WebSocket. The live combat tick is disabled in tests
(see conftest), so AI is driven by calling game_loop._combat_tick_once().
"""
import asyncio

import models
import combat
import game_loop
import smack_talk
from world import world


def _npc_id(db, name):
    return db.query(models.Npc).filter_by(name=name).first().id


# ---------- walkability / occupancy ----------
def test_is_walkable_and_bounds(db_session):
    world.load()
    assert world.is_walkable(1, 2, 2) is True    # interior floor
    assert world.is_walkable(1, 0, 0) is False   # wall corner
    assert world.is_walkable(1, 2, 0) is False   # top wall
    assert world.is_walkable(1, 2, 5) is False   # bottom wall
    assert world.is_walkable(1, -1, 2) is False  # off-grid (x<0)
    assert world.is_walkable(1, 8, 2) is False   # off-grid (x>=w)


def test_terrain_types_block_movement(db_session):
    """Pillars and water block movement; floor, door and rubble are walkable."""
    world.load()
    node = world.rooms[1]
    node.tiles[2] = "#.o~:.+#"   # x: 0# 1. 2:pillar 3:water 4:rubble 5. 6:door 7#
    assert world.is_walkable(1, 1, 2) is True    # floor
    assert world.is_walkable(1, 2, 2) is False   # pillar
    assert world.is_walkable(1, 3, 2) is False   # water
    assert world.is_walkable(1, 4, 2) is True    # rubble (walkable)
    assert world.is_walkable(1, 6, 2) is True    # door


def test_occupant_at(db_session):
    care = _npc_id(db_session, "Caretaker")
    inn = _npc_id(db_session, "Innkeeper")
    world.load()
    assert world.occupant_at(1, 3, 2) == ("npc", care)
    assert world.occupant_at(1, 5, 4) == ("npc", inn)
    assert world.occupant_at(1, 2, 2) is None
    world.place_player(1, 1)  # Bryan onto spawn (2,2)
    assert world.occupant_at(1, 2, 2) == ("player", 1)


# ---------- try_step: MOVED / BLOCKED / ATTACK ----------
def test_try_step_moved(db_session):
    world.load()
    world.place_player(1, 1)                       # (2,2)
    res = world.try_step("player", 1, 1, 0, -1)    # north -> (2,1)
    assert res.kind == "MOVED" and (res.x, res.y) == (2, 1)
    assert world.position_of("player", 1, 1) == (2, 1)


def test_try_step_blocked_by_wall(db_session):
    world.load()
    world.rooms[1].player_pos[1] = (1, 2)
    res = world.try_step("player", 1, 1, -1, 0)    # west into the wall (0,2)
    assert res.kind == "BLOCKED"
    assert world.position_of("player", 1, 1) == (1, 2)  # didn't move


def test_try_step_attacks_combatant(db_session):
    care = _npc_id(db_session, "Caretaker")
    world.load()
    world.place_player(1, 1)                       # (2,2), Caretaker at (3,2)
    res = world.try_step("player", 1, 1, 1, 0)     # east into the Caretaker
    assert res.kind == "ATTACK" and res.target_kind == "npc" and res.target_id == care


def test_try_step_blocked_by_noncombatant(db_session):
    world.load()
    world.rooms[1].player_pos[1] = (5, 3)          # just north of the Innkeeper (5,4)
    res = world.try_step("player", 1, 1, 0, 1)     # bump the non-combatant
    assert res.kind == "BLOCKED"


# ---------- pathing ----------
def test_step_candidates_head_toward_target(db_session):
    world.load()
    assert world.step_candidates((3, 2), (6, 2))[0] == (1, 0)   # longer axis = east
    assert world.step_candidates((3, 2), (3, 4))[0] == (0, 1)   # longer axis = south


def test_combat_tick_mob_paths_toward_player(db_session, monkeypatch):
    # Silence smack-talk side effects; we only assert movement here.
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(smack_talk, "maybe_smack", _noop)
    care = _npc_id(db_session, "Caretaker")
    world.load()
    world.rooms[1].player_pos[1] = (6, 2)          # player far east; mob at (3,2)
    before = world.chebyshev(world.position_of("npc", 1, care), (6, 2))
    asyncio.run(game_loop._combat_tick_once())
    after = world.chebyshev(world.position_of("npc", 1, care), (6, 2))
    assert after < before                          # stepped closer


def test_mob_melee_on_adjacency_damages_player(db_session, monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(smack_talk, "maybe_smack", _noop)
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 3})
    care = _npc_id(db_session, "Caretaker")
    world.load()
    world.place_player(1, 1)                        # (2,2), adjacent to mob (3,2)
    asyncio.run(game_loop._combat_tick_once())      # mob is adjacent -> melees
    db_session.expire_all()
    assert db_session.query(models.Player).get(1).health == 7  # 10 - 3


def test_hostile_mob_respawns_after_death(db_session, monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(smack_talk, "maybe_smack", _noop)
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 50})
    care = _npc_id(db_session, "Caretaker")  # hostile in the test world
    world.load()
    world.place_player(1, 1)                       # (2,2), adjacent to mob (3,2)
    asyncio.run(combat.resolve_player_attack(1, 1, care))
    # Slain: off the map, but scheduled to come back.
    assert world.position_of("npc", 1, care) is None
    assert care in world.pending_respawns
    # Force the timer and respawn.
    world.pending_respawns[care]["due"] = 0.0
    assert world.due_respawns() == [care]
    res = world.respawn_npc(care)
    assert res and res["room_id"] == 1
    assert world.position_of("npc", 1, care) == (3, 2)   # back at its home tile
    db_session.expire_all()
    assert db_session.query(models.Npc).get(care).health == 8  # full health


def test_dead_npc_revived_on_load(db_session):
    """A mob left at 0 hp in the DB (a prior run) is revived + placed on load,
    not resurrected as an unkillable zombie."""
    care = _npc_id(db_session, "Caretaker")
    db_session.query(models.Npc).get(care).health = 0
    db_session.commit()
    world.load()
    assert world.position_of("npc", 1, care) == (3, 2)   # on the map
    db_session.expire_all()
    assert db_session.query(models.Npc).get(care).health == 8  # healed


def test_respawn_grace_blocks_immediate_rehit(db_session, monkeypatch):
    """After a player is killed and respawns, a hostile can't land a hit during
    the grace window — preventing the chain-kill / endless-respawn loop."""
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(smack_talk, "maybe_smack", _noop)
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 50})
    care = _npc_id(db_session, "Caretaker")
    world.load()
    world.place_player(1, 1)
    asyncio.run(combat.resolve_mob_attack(care, 1, 1))   # kills → respawn (full hp, grace set)
    db_session.expire_all()
    full = db_session.query(models.Player).get(1).max_health
    assert db_session.query(models.Player).get(1).health == full
    asyncio.run(combat.resolve_mob_attack(care, 1, 1))   # immediate re-hit suppressed by grace
    db_session.expire_all()
    assert db_session.query(models.Player).get(1).health == full   # unharmed


# ---------- zone snapshot ----------
def test_zone_snapshot_shape(db_session):
    care = _npc_id(db_session, "Caretaker")
    world.load()
    world.place_player(1, 1)
    snap = world.zone_snapshot(1, 1)
    assert snap["room"]["name"] == "Foyer"
    assert snap["tiles"]["w"] == 8 and snap["tiles"]["h"] == 6
    assert len(snap["tiles"]["grid"]) == 6
    assert snap["you"]["id"] == 1 and (snap["you"]["x"], snap["you"]["y"]) == (2, 2)
    assert snap["you"]["glyph"] and "max_hp" in snap["you"]
    by_name = {e["name"]: e for e in snap["entities"]}
    assert set(by_name) == {"Caretaker", "Innkeeper"}
    assert by_name["Caretaker"]["kind"] == "npc" and by_name["Caretaker"]["hostile"] is True
    assert by_name["Innkeeper"]["hostile"] is False


# ---------- smack-talk fallback ----------
def test_smack_talk_canned_fallback_offline(db_session, monkeypatch):
    """With DeepSeek blank (conftest), maybe_smack emits a canned npc_said."""
    care = _npc_id(db_session, "Caretaker")
    sent = []

    async def fake_broadcast(room_id, msg, exclude_player=None):
        sent.append(msg)

    monkeypatch.setattr(smack_talk.manager, "broadcast_to_room", fake_broadcast)
    smack_talk.reset()
    asyncio.run(smack_talk.maybe_smack(care, 1, "Caretaker", "aggro"))
    assert len(sent) == 1
    assert sent[0]["event"] == "npc_said" and sent[0]["name"] == "Caretaker"
    assert isinstance(sent[0]["text"], str) and sent[0]["text"]


def test_smack_talk_respects_cooldown(db_session, monkeypatch):
    care = _npc_id(db_session, "Caretaker")
    sent = []

    async def fake_broadcast(room_id, msg, exclude_player=None):
        sent.append(msg)

    monkeypatch.setattr(smack_talk.manager, "broadcast_to_room", fake_broadcast)
    smack_talk.reset()

    async def _twice():
        await smack_talk.maybe_smack(care, 1, "Caretaker", "aggro")
        await smack_talk.maybe_smack(care, 1, "Caretaker", "landed_hit")  # within cooldown

    asyncio.run(_twice())
    assert len(sent) == 1   # second call suppressed by the per-mob cooldown
