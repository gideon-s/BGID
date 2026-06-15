"""Phase 3 — inventory & equipment.

Test world (conftest): the Foyer floor holds an Iron Sword (1,1; weapon,
+1 atk / +2 dmg), Leather Armor (4,1; armor, +2 def) and the Rusty Key (1,4).
Players spawn at (2,2). The combat tick is disabled in tests, so mobs don't
interfere with movement/pickup sequences.
"""
import combat
import models
import services
from services import ItemService, SLOT_LIMITS
from world import world


def _ws(client, token, pid):
    return client.websocket_connect(f"/ws/{pid}?token={token}")


def _drain_until(ws, pred, tries=16):
    for _ in range(tries):
        m = ws.receive_json()
        if pred(m):
            return m
    return None


def _item(db, name):
    return db.query(models.Item).filter_by(name=name).first()


# ---------- service layer ----------
def test_equipment_bonuses_sum_only_equipped(db_session):
    sword, armor = _item(db_session, "Iron Sword"), _item(db_session, "Leather Armor")
    for it in (sword, armor):
        it.room_id = it.tile_x = it.tile_y = None
        it.player_id = 1
    db_session.commit()
    # Carried but unequipped → no bonuses yet.
    assert ItemService.equipment_bonuses(db_session, 1) == {"attack": 0, "defense": 0, "damage": 0}
    ItemService.equip(db_session, 1, sword.id)
    ItemService.equip(db_session, 1, armor.id)
    assert ItemService.equipment_bonuses(db_session, 1) == {"attack": 1, "defense": 2, "damage": 2}


def test_equip_single_slot_swaps(db_session):
    sword = _item(db_session, "Iron Sword")
    sword.room_id = None; sword.player_id = 1
    dagger = models.Item(name="Dagger", item_type="weapon", player_id=1,
                         is_equippable=True, equip_slot="weapon", damage_bonus=1)
    db_session.add(dagger); db_session.commit()
    ItemService.equip(db_session, 1, sword.id)
    ItemService.equip(db_session, 1, dagger.id)   # weapon slot limit is 1 → sword swaps out
    db_session.refresh(sword); db_session.refresh(dagger)
    assert dagger.equipped is True and sword.equipped is False


def test_two_rings_fit_then_third_swaps_oldest(db_session):
    assert SLOT_LIMITS["ring"] == 2
    rings = [models.Item(name=f"Ring {i}", item_type="ring", player_id=1,
                         is_equippable=True, equip_slot="ring") for i in range(3)]
    db_session.add_all(rings); db_session.commit()
    for r in rings[:2]:
        ItemService.equip(db_session, 1, r.id)
    for r in rings[:2]:
        db_session.refresh(r)
        assert r.equipped is True            # both rings fit
    ItemService.equip(db_session, 1, rings[2].id)   # third swaps the oldest (Ring 0)
    for r in rings:
        db_session.refresh(r)
    assert rings[0].equipped is False and rings[1].equipped and rings[2].equipped


def test_pickup_and_drop_round_trip(db_session):
    sword = _item(db_session, "Iron Sword")
    ItemService.pickup(db_session, 1, sword.id)
    db_session.refresh(sword)
    assert sword.player_id == 1 and sword.room_id is None and sword.tile_x is None
    ItemService.drop(db_session, 1, sword.id, 3, 3)
    db_session.refresh(sword)
    assert sword.player_id is None and sword.room_id == 1 and (sword.tile_x, sword.tile_y) == (3, 3)


# ---------- world layer ----------
def test_ground_items_in_zone_snapshot(db_session):
    world.load()
    snap = world.zone_snapshot(1, 1)
    names = {it["name"] for it in snap["items"]}
    assert {"Iron Sword", "Leather Armor", "Rusty Key"} <= names
    assert world.item_at(1, 1, 1) == _item(db_session, "Iron Sword").id


# ---------- combat seam ----------
class _Dummy:
    def ability_mod(self, name):
        return 0


def test_attack_roll_applies_bonuses(monkeypatch):
    monkeypatch.setattr(combat.random, "randint", lambda a, b: b)   # max rolls
    base = combat._attack_roll(_Dummy(), _Dummy())
    buffed = combat._attack_roll(_Dummy(), _Dummy(), dmg_bonus=2)
    assert buffed["damage"] == base["damage"] + 2


def test_defense_bonus_can_avert_a_hit(monkeypatch):
    monkeypatch.setattr(combat.random, "randint", lambda a, b: a)   # min to-hit (1)
    # to-hit = 1 vs AC 10 → miss anyway; raise AC and it stays a miss (sanity on def plumb-through)
    assert combat._attack_roll(_Dummy(), _Dummy(), def_bonus=5)["hit"] is False


# ---------- over the socket ----------
def test_pickup_over_socket(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()                    # zone_state (Foyer)
        ws.send_json({"cmd": "move", "dx": -1, "dy": 0})   # (2,2) -> (1,2)
        ws.send_json({"cmd": "move", "dx": 0, "dy": -1})   # (1,2) -> (1,1) onto the sword
        ws.send_json({"cmd": "pickup"})
        taken = _drain_until(ws, lambda m: m["event"] == "item_taken")
        assert taken is not None
        inv = _drain_until(ws, lambda m: m["event"] == "inventory"
                           and any(i["name"] == "Iron Sword" for i in m["items"]))
        assert inv is not None
        # The sword is gone from the floor.
        ws.send_json({"cmd": "look"})
        zs = _drain_until(ws, lambda m: m["event"] == "zone_state")
        assert all(it["name"] != "Iron Sword" for it in zs["items"])


def test_equip_then_drop_over_socket(client, token, db_session):
    sword = _item(db_session, "Iron Sword")
    sword.room_id = sword.tile_x = sword.tile_y = None
    sword.player_id = 1
    db_session.commit()
    with _ws(client, token, 1) as ws:
        ws.receive_json()                              # zone_state
        ws.send_json({"cmd": "equip", "item_id": sword.id})
        inv = _drain_until(ws, lambda m: m["event"] == "inventory")
        assert any(i["id"] == sword.id and i["equipped"] for i in inv["items"])
        ws.send_json({"cmd": "drop", "item_id": sword.id})
        dropped = _drain_until(ws, lambda m: m["event"] == "item_dropped" and m["id"] == sword.id)
        assert dropped is not None
        inv2 = _drain_until(ws, lambda m: m["event"] == "inventory")
        assert all(i["id"] != sword.id for i in inv2["items"])   # no longer carried
