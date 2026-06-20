"""Traps & environments (handoff-09): RoomFeature loading, traps/hazards (incl.
AoE), signs, powder kegs, spawners, wandering mobs, sanctuaries, and tavern rest."""
import asyncio
import json
import time

import casting
import combat
import config
import database
import features
import game_loop
import models
from world import world


def _ws(client, token, pid=1):
    return client.websocket_connect(f"/ws/{pid}?token={token}")


def _drain_until(ws, pred, tries=16):
    for _ in range(tries):
        m = ws.receive_json()
        if pred(m):
            return m
    return None


def _add_feature(db, room_id, x, y, kind, glyph="", **config_kw):
    db.add(models.RoomFeature(room_id=room_id, x=x, y=y, kind=kind, glyph=glyph,
                              config=json.dumps(config_kw)))
    db.commit()


def _place(pid_or_npc, kind, ent_id, x, y, room_id=1):
    (world.rooms[room_id].player_pos if kind == "player"
     else world.rooms[room_id].npc_pos)[ent_id] = (x, y)


def _hp(model, ent_id):
    db = database.SessionLocal()
    try:
        return db.get(model, ent_id).health
    finally:
        db.close()


# ---------- §6 feature loading + lookup ----------
def test_feature_loads_and_lookup(db_session):
    _add_feature(db_session, 1, 4, 2, "sign", glyph="🪧", text="hi")
    world.load()
    f = world.feature_at(1, 4, 2)
    assert f and f["kind"] == "sign" and f["config"]["text"] == "hi"
    assert world.feature_near(1, 5, 2, kind="sign")          # adjacent reach
    assert world.feature_at(1, 0, 0) is None


# ---------- §1 traps: damage on entry, one-shot, AoE ----------
def test_trap_damages_on_entry(db_session):
    _add_feature(db_session, 1, 4, 2, "trap", glyph="^", name="Spikes", damage=3)
    world.load(); world.enter_world(1); world.place_player(1, 1)
    _place(None, "player", 1, 4, 2)
    before = _hp(models.Player, 1)
    asyncio.run(features.on_enter(1, "player", 1, 4, 2))
    assert _hp(models.Player, 1) == before - 3


def test_one_shot_trap_fires_once(db_session):
    _add_feature(db_session, 1, 4, 2, "trap", glyph="^", name="Dart", damage=2, one_shot=True)
    world.load(); world.enter_world(1); world.place_player(1, 1)
    _place(None, "player", 1, 4, 2)
    before = _hp(models.Player, 1)
    asyncio.run(features.on_enter(1, "player", 1, 4, 2))
    asyncio.run(features.on_enter(1, "player", 1, 4, 2))      # second step: inert
    assert _hp(models.Player, 1) == before - 2


def test_trap_applies_debuff(db_session):
    import effects
    _add_feature(db_session, 1, 4, 2, "trap", glyph="☠️", name="Gas", damage=0, debuff="Poison")
    world.load(); world.enter_world(1); world.place_player(1, 1)
    _place(None, "player", 1, 4, 2)
    asyncio.run(features.on_enter(1, "player", 1, 4, 2))
    assert any(e["name"] == "Poison" for e in effects.snapshot(effects.eid("player", 1)))


def test_keg_aoe_and_consumed(db_session):
    _add_feature(db_session, 1, 3, 3, "keg", glyph="🛢️", name="Keg", damage=4, radius=1)
    world.load(); world.enter_world(1); world.place_player(1, 1)
    rat = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    _place(None, "player", 1, 3, 3)                          # in blast
    _place(None, "npc", rat.id, 3, 2)                        # adjacent → in blast
    php, nhp = _hp(models.Player, 1), _hp(models.Npc, rat.id)
    feat = world.feature_at(1, 3, 3, "keg")
    asyncio.run(features.trigger_keg(1, feat))
    assert _hp(models.Player, 1) == php - 4
    assert _hp(models.Npc, rat.id) == nhp - 4
    assert world.feature_at(1, 3, 3) is None                 # consumed
    db = database.SessionLocal()
    try:
        assert db.get(models.RoomFeature, feat["id"]) is None
    finally:
        db.close()


# ---------- §2 signs ----------
def test_read_sign(client, token):
    db = database.SessionLocal()
    try:
        db.add(models.RoomFeature(room_id=1, x=2, y=3, kind="sign", glyph="🪧",
               config=json.dumps({"title": "Notice", "text": "Beware the cellar"})))
        db.commit()
    finally:
        db.close()
    world.load()                                             # pick up the sign (no one online)
    with _ws(client, token, 1) as ws:
        ws.receive_json()                                    # zone_state
        ws.send_json({"cmd": "read"})
        ev = _drain_until(ws, lambda m: m["event"] == "sign")
        assert ev is not None and "Beware" in ev["text"]


# ---------- §3 spawners ----------
def test_spawner_caps_and_refills(db_session):
    _add_feature(db_session, 1, 1, 1, "spawner", glyph="🕳️",
                 interval=0, max_active=2, radius=3,
                 template={"name": "Bat", "glyph": "🦇", "is_hostile": True, "health": 4})
    world.load(); world.enter_world(1); world.place_player(1, 1)
    sid = world.feature_at(1, 1, 1, "spawner")["id"]
    for _ in range(4):
        asyncio.run(game_loop._spawn_tick(time.monotonic()))
    assert len(game_loop._spawner_children[sid]) == 2        # capped
    child = next(iter(game_loop._spawner_children[sid]))
    asyncio.run(combat.damage_npc(1, child, 999, "tester", 1, "player"))  # kill one
    asyncio.run(game_loop._spawn_tick(time.monotonic()))     # prune + refill
    assert len(game_loop._spawner_children[sid]) == 2
    assert child not in game_loop._spawner_children[sid]


# ---------- §4 wandering ----------
def test_wandering_mob_moves(db_session, monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(combat, "resolve_mob_attack", _noop)  # silence the hostile Caretaker
    ink = db_session.query(models.Npc).filter_by(name="Innkeeper").first()
    ink.wanders = True; db_session.commit()
    world.load(); world.enter_world(1); world.place_player(1, 1)
    iid = ink.id
    start = world.position_of("npc", 1, iid)
    moved = False
    for _ in range(12):
        game_loop._last_wander_at.clear()                    # allow a wander each tick
        asyncio.run(game_loop._combat_tick_once())
        if world.position_of("npc", 1, iid) != start:
            moved = True
            break
    assert moved
    pos = world.position_of("npc", 1, iid)
    assert max(abs(pos[0] - start[0]), abs(pos[1] - start[1])) <= config.MOB_WANDER_LEASH


# ---------- §5 sanctuary + tavern rest ----------
def test_sanctuary_suppresses_aggro(db_session):
    foyer = db_session.get(models.Room, 1)
    foyer.is_safe = True; db_session.commit()
    world.load(); world.enter_world(1); world.place_player(1, 1)
    rat = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    _place(None, "player", 1, 2, 2)
    _place(None, "npc", rat.id, 3, 2)                        # adjacent — would attack if able
    before = _hp(models.Player, 1)
    asyncio.run(game_loop._combat_tick_once())
    assert _hp(models.Player, 1) == before                   # no aggro, no hit
    assert rat.id not in game_loop._aggroed


def test_rest_in_tavern(client, token, db_session):
    foyer = db_session.get(models.Room, 1)
    foyer.room_type = "tavern"; db_session.commit()
    care = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    care.is_hostile = False; db_session.commit()             # no hostiles → safe to rest
    hurt = db_session.get(models.Player, 1)
    hurt.health = 1; db_session.commit()
    world.load()
    with _ws(client, token, 1) as ws:
        ws.receive_json()                                    # zone_state
        ws.send_json({"cmd": "rest"})
        ev = _drain_until(ws, lambda m: m["event"] == "stats")
        assert ev is not None and ev["hp"] == ev["max_hp"]


# ---------- AoE spell (Fireball) ----------
def test_fireball_aoe_damages(db_session):
    world.load(); world.enter_world(1); world.place_player(1, 1)
    bryan = db_session.get(models.Player, 1)
    bryan.char_class, bryan.mana, bryan.max_mana = "mage", 30, 30
    db_session.commit()
    rat = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    npos = world.position_of("npc", 1, rat.id)
    before = _hp(models.Npc, rat.id)
    asyncio.run(casting.resolve_cast(1, 1, "fireball", npos[0], npos[1]))
    assert _hp(models.Npc, rat.id) < before
