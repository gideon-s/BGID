"""Player-vs-player combat — intentional only (the strike action, never a bump),
and never in a safe room (the Foyer). A landed hit routes through the shared
damage/respawn path.

The Great Hall (room 2) is a normal (fightable) zone; the Foyer (room 1) is the
configured PvP-safe room.
"""
import asyncio

import combat
import config
import database
import models
from world import world


def _rival(db, room_id=2):
    db.add(models.Player(id=2, name="Rival", room_id=room_id, char_class="warrior",
                         health=10, max_health=10))
    db.commit()


def _place(room, **players):
    world.load()
    for pid, pos in players.items():
        world.rooms[room].player_pos[int(pid)] = pos


def test_bumping_a_player_is_blocked_not_an_attack(db_session):
    _place(2, **{"1": (2, 2), "2": (3, 2)})
    res = world.try_step("player", 1, 2, 1, 0)        # step east into player 2
    assert res.kind == "BLOCKED"                      # no ATTACK on a bump


def test_pvp_strike_damages_the_target(db_session, monkeypatch):
    _rival(db_session)
    _place(2, **{"1": (2, 2), "2": (3, 2)})
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 4})
    asyncio.run(combat.resolve_pvp_attack(1, 2, 2))   # explicit strike in room 2
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=2).first().health == 6
    finally:
        db.close()


def test_pvp_blocked_in_the_safe_room(db_session, monkeypatch):
    assert 1 in config.PVP_SAFE_ROOM_IDS                # the Foyer is safe
    _rival(db_session, room_id=1)
    _place(1, **{"1": (2, 2), "2": (3, 2)})            # adjacent, but in the Foyer
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 9})
    asyncio.run(combat.resolve_pvp_attack(1, 1, 2))
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=2).first().health == 10   # truce holds
    finally:
        db.close()


def test_pvp_miss_deals_no_damage(db_session, monkeypatch):
    _rival(db_session)
    _place(2, **{"1": (2, 2), "2": (3, 2)})
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": False, "damage": 0})
    asyncio.run(combat.resolve_pvp_attack(1, 2, 2))
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=2).first().health == 10
    finally:
        db.close()


def test_pvp_out_of_reach_is_a_noop(db_session, monkeypatch):
    _rival(db_session)
    _place(2, **{"1": (1, 1), "2": (5, 3)})            # far apart in the Hall
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 9})
    asyncio.run(combat.resolve_pvp_attack(1, 2, 2))
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=2).first().health == 10
    finally:
        db.close()
