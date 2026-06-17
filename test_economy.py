"""Economy loop: mob loot drops, the vendor (buy/sell), and admin coin grants."""
import random

import database
import loot
import models
import services
import shops
from world import world


def _ws(client, token, pid=1):
    return client.websocket_connect(f"/ws/{pid}?token={token}")


def _drain_until(ws, pred, tries=16):
    for _ in range(tries):
        m = ws.receive_json()
        if pred(m):
            return m
    return None


# ---------- loot tables ----------
def test_loot_rolls_coins_and_maybe_gems():
    rng = random.Random(1)
    drops = [loot.roll("combat_mob", rng) for _ in range(40)]
    flat = [d for batch in drops for d in batch]
    assert any(d["item_type"] == "coins" for d in flat)
    assert any(d["item_type"] == "gem" for d in flat)        # gem_chance fires within 40 rolls
    # an unknown type still rolls without error
    assert isinstance(loot.roll("mystery"), list)


# ---------- vendor ----------
def test_innkeeper_is_a_vendor():
    assert shops.is_vendor("innkeeper") and shops.stock_for("innkeeper")
    assert not shops.is_vendor("combat_mob")


def test_buy_deducts_coins_and_adds_item(client, token, db_session):
    services.ItemService.add_coins(db_session, 1, 500)
    npc = db_session.query(models.Npc).filter_by(name="Innkeeper").first()
    g = shops.stock_for("innkeeper")[0]                       # the cheapest ration (3cp)
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "buy", "npc_id": npc.id, "sku": g["sku"]})
        w = _drain_until(ws, lambda m: m["event"] == "wallet")
        assert w["coins"] == 500 - g["price"]
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=1).first().coins == 500 - g["price"]
        assert db.query(models.Item).filter_by(name=g["name"], player_id=1).first() is not None
    finally:
        db.close()


def test_cannot_buy_without_coins(client, token, db_session):
    npc = db_session.query(models.Npc).filter_by(name="Innkeeper").first()
    dagger = shops.good("innkeeper", "dagger")               # 60cp; player has 0
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "buy", "npc_id": npc.id, "sku": "dagger"})
        err = _drain_until(ws, lambda m: m["event"] == "error" and "afford" in m["detail"])
        assert err is not None


def test_sell_gem_for_coins(client, token, db_session):
    npc = db_session.query(models.Npc).filter_by(name="Innkeeper").first()
    gem = models.Item(name="Sapphire", item_type="gem", value=250, player_id=1, is_movable=True)
    db_session.add(gem); db_session.commit(); gid = gem.id
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "sell", "npc_id": npc.id, "item_id": gid})
        w = _drain_until(ws, lambda m: m["event"] == "wallet")
        assert w["coins"] == 250
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=1).first().coins == 250
        assert db.get(models.Item, gid) is None              # the gem left the pack
    finally:
        db.close()


def test_shop_command_only_at_a_vendor(client, token, db_session):
    # the Caretaker (combat_mob) is not a vendor
    npc = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "shop", "npc_id": npc.id})
        err = _drain_until(ws, lambda m: m["event"] == "error" and "merchant" in m["detail"])
        assert err is not None


# ---------- admin grant ----------
def test_admin_grant_coins(client, admin_headers, db_session):
    r = client.post("/admin/characters/1/coins", json={"amount": 137}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["coins"] == 137
    r = client.post("/admin/characters/1/coins", json={"amount": -1000}, headers=admin_headers)
    assert r.json()["coins"] == 0                            # clamped


def test_admin_grant_requires_admin(client, user_headers):
    assert client.post("/admin/characters/1/coins", json={"amount": 50},
                       headers=user_headers).status_code == 403
