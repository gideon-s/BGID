"""Base-10 coin currency + valued gems."""
import database
import currency
import models
import services
from world import world


def _ws(client, token, pid=1):
    return client.websocket_connect(f"/ws/{pid}?token={token}")


def _drain_until(ws, pred, tries=14):
    for _ in range(tries):
        m = ws.receive_json()
        if pred(m):
            return m
    return None


# ---------- currency math (base-10) ----------
def test_breakdown_and_short():
    assert currency.breakdown(137) == {"platinum": 0, "gold": 1, "silver": 3, "copper": 7}
    assert currency.short(137) == "1gp 3sp 7cp"
    assert currency.short(1234) == "1pp 2gp 3sp 4cp"
    assert currency.short(50) == "5sp"
    assert currency.short(0) == "0cp"


def test_add_coins(db_session):
    assert services.ItemService.add_coins(db_session, 1, 137) == 137
    assert services.ItemService.add_coins(db_session, 1, 13) == 150
    assert services.ItemService.add_coins(db_session, 1, -200) == 0      # clamped


# ---------- coin pickup → wallet ----------
def test_pickup_coins_collects_into_wallet(client, token, db_session):
    db_session.add(models.Item(name="Pouch", item_type="coins", value=137,
                               room_id=1, tile_x=2, tile_y=2, is_movable=True, glyph="🪙"))
    db_session.commit()
    world.load()                                  # register the new ground item
    with _ws(client, token, 1) as ws:
        ws.receive_json()                         # zone_state
        ws.send_json({"cmd": "pickup"})           # standing on the pouch (spawn 2,2)
        w = _drain_until(ws, lambda m: m["event"] == "wallet")
        assert w is not None and w["coins"] == 137
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=1).first().coins == 137
        assert db.query(models.Item).filter_by(name="Pouch").first() is None   # consumed
    finally:
        db.close()


# ---------- coins surfaced in snapshot + sheet ----------
def test_zone_state_and_sheet_carry_coins(client, token, db_session):
    services.ItemService.add_coins(db_session, 1, 250)
    with _ws(client, token, 1) as ws:
        zs = _drain_until(ws, lambda m: m["event"] == "zone_state")
        assert zs["you"]["coins"] == 250
        ws.send_json({"cmd": "sheet"})
        sheet = _drain_until(ws, lambda m: m["event"] == "character_sheet")
        assert sheet["coins"] == 250


# ---------- gems are valued carried items, not currency ----------
def test_gem_is_a_valued_carried_item(client, token, db_session):
    db_session.add(models.Item(name="Sapphire", item_type="gem", value=250,
                               room_id=1, tile_x=2, tile_y=2, is_movable=True, glyph="🔷"))
    db_session.commit()
    world.load()
    with _ws(client, token, 1) as ws:
        ws.receive_json()                         # zone_state
        ws.send_json({"cmd": "pickup"})
        inv = _drain_until(ws, lambda m: m["event"] == "inventory")
        gem = next(i for i in inv["items"] if i["name"] == "Sapphire")
        assert gem["type"] == "gem" and gem["value"] == 250
    # the gem went to the pack (not the wallet)
    db = database.SessionLocal()
    try:
        p = db.query(models.Player).filter_by(id=1).first()
        assert p.coins == 0
        assert db.query(models.Item).filter_by(name="Sapphire", player_id=1).first() is not None
    finally:
        db.close()


def test_currency_migration_idempotent(db_session):
    import migrate_currency
    migrate_currency.migrate()
    migrate_currency.migrate()
    from sqlalchemy import text
    with database.engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(players)"))}
    assert "coins" in cols
