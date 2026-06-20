"""Status-effect extensions (handoff-08): entity-keyed effects, DoT, debuffs,
gear effects, and spell buffs/debuffs."""
import asyncio

import casting
import combat
import database
import debuffs
import effects
import game_loop
import gear_effects
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


def _caretaker(db):
    return db.query(models.Npc).filter_by(name="Caretaker").first()


# ---------- §1 entity-keyed effects ----------
def test_effects_keyed_by_entity():
    p, n = effects.eid("player", 1), effects.eid("npc", 3)
    effects.apply_effect(p, "Strength", "💪", 60, atk=2)
    effects.apply_effect(n, "Weaken", "🥀", 30, atk=-2, dmg=-2, harm=True)
    assert effects.bonuses(p)["attack"] == 2
    assert effects.bonuses(n) == {"attack": -2, "damage": -2, "defense": 0}
    snap = effects.snapshot(n)
    assert {e["name"] for e in snap} == {"Weaken"} and snap[0]["harm"] is True


# ---------- §1 DoT drains + kills through the shared path ----------
def test_dot_drains_and_kills_npc(db_session):
    world.load(); world.enter_world(1); world.place_player(1, 1)
    rat = _caretaker(db_session)
    rat.health = 3; db_session.commit()
    nkey = effects.eid("npc", rat.id)
    effects.apply_effect(nkey, "Poison", "🤢", 60, dot=2, dot_interval=0, harm=True,
                         source_name="Bryan", source_id=1, source_type="player")
    asyncio.run(game_loop._apply_dots())                  # 3 -> 1
    assert world.room_of_npc(rat.id) == 1
    asyncio.run(game_loop._apply_dots())                  # 1 -> dead
    assert world.room_of_npc(rat.id) is None              # removed via the death path
    assert effects.active(nkey) == []                     # effect cleared on death
    db = database.SessionLocal()
    try:
        assert db.get(models.Player, 1).experience > 0    # XP routed to the source
    finally:
        db.close()


# ---------- §2 a mob's Weaken lowers its own attack ----------
def test_weaken_lowers_mob_attack(db_session, monkeypatch):
    captured = {}
    def fake(a, d, atk_bonus=0, dmg_bonus=0, def_bonus=0):
        captured["atk"], captured["dmg"] = atk_bonus, dmg_bonus
        return {"hit": False, "damage": 0}
    monkeypatch.setattr(combat, "_attack_roll", fake)
    world.load(); world.enter_world(1); world.place_player(1, 1)
    rat = _caretaker(db_session)
    effects.apply_effect(effects.eid("npc", rat.id), "Weaken", "🥀", 30,
                         atk=-2, dmg=-2, harm=True)
    asyncio.run(combat.resolve_mob_attack(rat.id, 1, 1))
    assert captured["atk"] == -2 and captured["dmg"] == -2


# ---------- §2 a venomous mob poisons the player it hits ----------
def test_venomous_mob_poisons_player(db_session, monkeypatch):
    monkeypatch.setattr(combat, "_attack_roll", lambda *a, **k: {"hit": True, "damage": 1})
    monkeypatch.setitem(debuffs.VENOM_BY_TYPE, "combat_mob", "Poison")
    world.load(); world.enter_world(1); world.place_player(1, 1)
    rat = _caretaker(db_session)
    asyncio.run(combat.resolve_mob_attack(rat.id, 1, 1))
    snap = effects.snapshot(effects.eid("player", 1))
    assert any(e["name"] == "Poison" and e["harm"] for e in snap)


# ---------- §3 gear effects: equip grants, unequip removes ----------
def test_ring_of_haste_gear_effect(db_session):
    ring = models.Item(name="Ring of Haste", item_type="ring", player_id=1,
                       equip_slot="ring", is_equippable=True, equipped=True, glyph="💍")
    db_session.add(ring); db_session.commit()
    pkey = effects.eid("player", 1)
    gear_effects.sync(1)
    assert effects.haste_factor(pkey) == 0.5
    snap = effects.snapshot(pkey)
    assert snap and snap[0]["gear"] is True and snap[0]["remaining"] is None
    ring.equipped = False; db_session.commit()
    gear_effects.sync(1)                                  # idempotent rebuild
    assert effects.haste_factor(pkey) == 1.0


def test_gear_effect_resynced_on_connect(client, token):
    db = database.SessionLocal()
    try:
        db.add(models.Item(name="Ring of Haste", item_type="ring", player_id=1,
                           equip_slot="ring", is_equippable=True, equipped=True, glyph="💍"))
        db.commit()
    finally:
        db.close()
    with _ws(client, token, 1) as ws:
        ws.receive_json()                                # zone_state
        ev = _drain_until(ws, lambda m: m["event"] == "effects")
        assert ev is not None
        assert any(e["name"] == "Ring of Haste" and e["gear"] for e in ev["effects"])
    assert effects.haste_factor(effects.eid("player", 1)) == 0.5


# ---------- §5 spell buff (self) + debuff (target) ----------
def test_cast_bless_self_buff(db_session):
    world.load(); world.enter_world(1); world.place_player(1, 1)
    bryan = db_session.get(models.Player, 1)
    bryan.char_class, bryan.mana, bryan.max_mana = "cleric", 20, 24
    db_session.commit()
    asyncio.run(casting.resolve_cast(1, 1, "bless", None, None))
    pkey = effects.eid("player", 1)
    assert any(e["name"] == "Bless" for e in effects.snapshot(pkey))
    assert effects.bonuses(pkey)["attack"] == 2


def test_cast_slow_debuffs_target(db_session):
    world.load(); world.enter_world(1); world.place_player(1, 1)
    bryan = db_session.get(models.Player, 1)
    bryan.char_class, bryan.mana, bryan.max_mana = "mage", 30, 30
    db_session.commit()
    rat = _caretaker(db_session)
    npos = world.position_of("npc", 1, rat.id)
    asyncio.run(casting.resolve_cast(1, 1, "slow", npos[0], npos[1]))
    snap = effects.snapshot(effects.eid("npc", rat.id))
    assert any(e["name"] == "Slow" and e["harm"] for e in snap)
