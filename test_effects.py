"""Timed status effects (buff potions): application, combat fold-in, expiry."""
import asyncio

import combat
import database
import effects
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


P1 = effects.eid("player", 1)


# ---------- effects registry (unit) ----------
def test_apply_active_bonuses_haste():
    effects.apply_effect(P1, "Strength", "💪", 60, atk=2, dmg=2)
    effects.apply_effect(P1, "Haste", "⚡", 45, haste=0.5)
    assert effects.bonuses(P1) == {"attack": 2, "damage": 2, "defense": 0}
    assert effects.haste_factor(P1) == 0.5
    snap = {e["name"] for e in effects.snapshot(P1)}
    assert snap == {"Strength", "Haste"}


def test_same_name_refreshes_not_stacks():
    effects.apply_effect(P1, "Strength", "💪", 60, atk=2, dmg=2)
    effects.apply_effect(P1, "Strength", "💪", 60, atk=2, dmg=2)   # drink another
    assert effects.bonuses(P1)["attack"] == 2 and len(effects.active(P1)) == 1


def test_expiry_sweep():
    effects.apply_effect(P1, "Stoneskin", "🪨", -1, defn=3)        # already expired
    assert effects.active(P1) == [] and effects.bonuses(P1)["defense"] == 0
    gone = effects.sweep()
    assert P1 in gone and "Stoneskin" in gone[P1]
    assert effects.active(P1) == []


# ---------- combat folds in the buff ----------
def test_strength_buff_boosts_melee(db_session, monkeypatch):
    captured = {}
    def fake(a, d, atk_bonus=0, dmg_bonus=0, def_bonus=0):
        captured["atk"], captured["dmg"] = atk_bonus, dmg_bonus
        return {"hit": True, "damage": 1}
    monkeypatch.setattr(combat, "_attack_roll", fake)
    effects.apply_effect(P1, "Strength", "💪", 60, atk=2, dmg=2)
    world.load(); world.enter_world(1); world.place_player(1, 1)
    caretaker = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    asyncio.run(combat.resolve_player_attack(1, 1, caretaker.id))
    assert captured["atk"] >= 2 and captured["dmg"] >= 2          # buff added on top of gear


# ---------- drinking a buff potion over the wire ----------
def test_drink_buff_potion_applies_effect(client, token, db_session):
    tonic = models.Item(name="Strength Tonic", item_type="potion", player_id=1,
                        is_movable=True, glyph="💪")
    db_session.add(tonic); db_session.commit(); tid = tonic.id
    with _ws(client, token, 1) as ws:
        ws.receive_json()                                        # zone_state
        ws.send_json({"cmd": "use", "item_id": tid})
        ev = _drain_until(ws, lambda m: m["event"] == "effects")
        assert ev is not None
        assert any(e["name"] == "Strength" for e in ev["effects"])
    assert effects.bonuses(P1)["attack"] == 2                    # buff is live server-side
    db = database.SessionLocal()
    try:
        assert db.get(models.Item, tid) is None                  # potion consumed
    finally:
        db.close()
