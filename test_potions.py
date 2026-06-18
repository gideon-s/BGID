"""Consumable potions — drinking applies an effect and consumes the item."""
import database
import models
import potions


def _ws(client, token, pid=1):
    return client.websocket_connect(f"/ws/{pid}?token={token}")


def _drain_until(ws, pred, tries=14):
    for _ in range(tries):
        m = ws.receive_json()
        if pred(m):
            return m
    return None


def _give(db, name, item_type="potion"):
    it = models.Item(name=name, item_type=item_type, player_id=1, is_movable=True, glyph="🧪")
    db.add(it); db.commit()
    return it.id


# ---------- effect application (unit) ----------
def test_heal_effect_clamped(db_session):
    p = db_session.query(models.Player).filter_by(id=1).first()
    p.health, p.max_health = 2, 10
    res = potions.apply(p, potions.effect_for("Healing Draught"))   # +12, clamps at 10
    assert p.health == 10 and res["hp_restored"] == 8


def test_restore_full(db_session):
    p = db_session.query(models.Player).filter_by(id=1).first()
    p.health, p.max_health = 1, 10
    p.mana, p.max_mana = 0, 20
    potions.apply(p, potions.effect_for("Elixir of Vigor"))
    assert p.health == 10 and p.mana == 20


# ---------- drinking over the wire ----------
def test_drink_heals_and_consumes(client, token, db_session):
    p = db_session.query(models.Player).filter_by(id=1).first()
    p.health, p.max_health = 3, 20
    pid = _give(db_session, "Healing Draught")
    with _ws(client, token, 1) as ws:
        ws.receive_json()                                  # zone_state
        ws.send_json({"cmd": "use", "item_id": pid})
        st = _drain_until(ws, lambda m: m["event"] == "stats" and m.get("hp") is not None)
        assert st["hp"] == 15                              # 3 + 12
    db = database.SessionLocal()
    try:
        assert db.get(models.Item, pid) is None            # consumed
        assert db.query(models.Player).filter_by(id=1).first().health == 15
    finally:
        db.close()


def test_cannot_drink_a_non_potion(client, token, db_session):
    sword = _give(db_session, "Iron Sword", item_type="weapon")
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "use", "item_id": sword})
        err = _drain_until(ws, lambda m: m["event"] == "error")
        assert err is not None and "drink" in err["detail"]


def test_unknown_potion_is_inert_and_not_consumed(client, token, db_session):
    pid = _give(db_session, "Mystery Brew")          # not in the registry
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "use", "item_id": pid})
        err = _drain_until(ws, lambda m: m["event"] == "error")
        assert err is not None
    db = database.SessionLocal()
    try:
        assert db.get(models.Item, pid) is not None      # a dud isn't wasted
    finally:
        db.close()
