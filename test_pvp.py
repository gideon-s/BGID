"""Player-vs-player combat — bumping another player attacks them, and the hit
routes through the shared damage/respawn path."""
import asyncio

import combat
import database
import models
from world import world


def _place(room, **players):
    """Drop players onto tiles in a room: _place(1, **{'1': (2,2), '2': (3,2)})."""
    world.load()
    for pid, pos in players.items():
        world.rooms[room].player_pos[int(pid)] = pos


def test_bumping_a_player_returns_attack(db_session):
    _place(1, **{"1": (2, 2), "2": (3, 2)})
    res = world.try_step("player", 1, 1, 1, 0)        # step east into player 2
    assert res.kind == "ATTACK"
    assert res.target_kind == "player" and res.target_id == 2


def test_pvp_attack_damages_the_target(db_session, monkeypatch):
    db_session.add(models.Player(id=2, name="Rival", room_id=1, char_class="warrior",
                                 health=10, max_health=10))
    db_session.commit()
    _place(1, **{"1": (2, 2), "2": (3, 2)})
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 4})
    asyncio.run(combat.resolve_pvp_attack(1, 1, 2))
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=2).first().health == 6
    finally:
        db.close()


def test_pvp_miss_deals_no_damage(db_session, monkeypatch):
    db_session.add(models.Player(id=2, name="Rival", room_id=1, char_class="warrior",
                                 health=10, max_health=10))
    db_session.commit()
    _place(1, **{"1": (2, 2), "2": (3, 2)})
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": False, "damage": 0})
    asyncio.run(combat.resolve_pvp_attack(1, 1, 2))
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=2).first().health == 10
    finally:
        db.close()


def test_pvp_out_of_reach_is_a_noop(db_session, monkeypatch):
    db_session.add(models.Player(id=2, name="Rival", room_id=1, char_class="warrior",
                                 health=10, max_health=10))
    db_session.commit()
    _place(1, **{"1": (1, 1), "2": (5, 4)})           # far apart
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 9})
    asyncio.run(combat.resolve_pvp_attack(1, 1, 2))
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=2).first().health == 10   # untouched
    finally:
        db.close()
