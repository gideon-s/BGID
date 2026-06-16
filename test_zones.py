"""Phase 2 — zone transitions and the overview map.

Test world (conftest): Foyer (1) has a north door (4,0) → Great Hall (2) and
down stairs (6,3) → Cellar (3, locked w/ Rusty Key); Great Hall has a south door
(2,4) → Foyer; Cellar has up stairs (3,2) → Foyer.
"""
import asyncio

import models
import combat
import game_loop
import smack_talk
from world import world


def _ws(client, token, pid):
    return client.websocket_connect(f"/ws/{pid}?token={token}")


def _drain_until(ws, pred, tries=14):
    """Read events until `pred(event)` is truthy; return that event (or None)."""
    for _ in range(tries):
        m = ws.receive_json()
        if pred(m):
            return m
    return None


# ---------- world-level resolution ----------
def test_transition_for_tile_mapping(db_session):
    world.load()
    n = world.transition_for_tile(1, 4, 0)        # Foyer north door
    assert n and n["direction"] == "north" and n["to_room_id"] == 2
    d = world.transition_for_tile(1, 6, 3)        # Foyer down stairs
    assert d and d["direction"] == "down" and d["is_locked"] is True and d["to_room_id"] == 3
    assert world.transition_for_tile(1, 2, 2) is None   # interior floor → not a transition
    s = world.transition_for_tile(2, 2, 4)        # Hall south door
    assert s and s["direction"] == "south" and s["to_room_id"] == 1
    u = world.transition_for_tile(3, 3, 2)        # Cellar up stairs
    assert u and u["direction"] == "up" and u["to_room_id"] == 1


def test_arrival_tile_lands_inside_return_exit(db_session):
    world.load()
    assert world.arrival_tile(2, "north") == (2, 3)   # into Hall → just inside its south door (2,4)
    assert world.arrival_tile(3, "down") == (3, 3)    # into Cellar → just below its up stairs (3,2)


def test_world_map_graph(db_session):
    world.load()
    wm = world.world_map()
    assert {r["name"] for r in wm["rooms"]} >= {"Foyer", "Great Hall", "Cellar"}
    assert any(e["dir"] == "north" and e["locked"] is False for e in wm["exits"])
    assert any(e["dir"] == "down" and e["locked"] is True for e in wm["exits"])


def test_transition_leaves_no_ghost_in_old_zone(db_session, monkeypatch):
    """After moving zones, the player has a tile position in exactly one room —
    so the old zone's hostiles can't keep attacking a doorway 'ghost'."""
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(smack_talk, "maybe_smack", _noop)
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 5})
    world.load()
    world.place_player(1, 1)                       # in the Foyer
    # Transition to the Great Hall (as the WS handler does).
    world.move_player(1, 2)
    world.place_player(1, 2, at=world.arrival_tile(2, "north"))
    assert world.position_of("player", 1, 1) is None      # no Foyer ghost
    assert world.position_of("player", 2, 1) is not None   # present in the Hall
    # The Foyer's hostile Caretaker now finds no target there → player unharmed.
    full = db_session.query(models.Player).get(1).max_health
    asyncio.run(game_loop._combat_tick_once())
    db_session.expire_all()
    assert db_session.query(models.Player).get(1).health == full


# ---------- over the socket ----------
def test_walk_through_door_changes_zone(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # zone_state (Foyer), spawn (2,2)
        for dx, dy in [(0,-1),(1,0),(1,0),(0,-1)]:   # N,E,E,N onto the north door (4,0)
            ws.send_json({"cmd": "move", "dx": dx, "dy": dy})
        zs = _drain_until(ws, lambda m: m["event"] == "zone_state" and m["room"]["name"] == "Great Hall")
        assert zs is not None
        assert (zs["you"]["x"], zs["you"]["y"]) == (2, 3)   # arrival just inside the south door


def test_other_players_see_you_leave_and_arrive(client, token):
    aria = client.post("/characters", json={"name": "Aria"}).json()["id"]
    with _ws(client, token, 1) as bryan:
        bryan.receive_json()
        with _ws(client, token, aria) as a:
            a.receive_json()                 # zone_state
            bryan.receive_json()             # entity_spawned (Aria) in Foyer
            # Bryan walks out through the north door.
            for dx, dy in [(0,-1),(1,0),(1,0),(0,-1)]:
                bryan.send_json({"cmd": "move", "dx": dx, "dy": dy})
            left = _drain_until(a, lambda m: m["event"] == "entity_left" and m["id"] == 1)
            assert left is not None           # Aria (still in the Foyer) sees Bryan leave


def test_locked_stairs_block_without_key(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        for dx, dy in [(0,1),(1,0),(1,0),(1,0),(1,0)]:   # S then E×4 onto down stairs (6,3)
            ws.send_json({"cmd": "move", "dx": dx, "dy": dy})
        err = _drain_until(ws, lambda m: m["event"] == "error" and "locked" in m["detail"])
        assert err is not None
        ws.send_json({"cmd": "look"})       # still in the Foyer
        assert _drain_until(ws, lambda m: m["event"] == "zone_state")["room"]["name"] == "Foyer"


def test_locked_stairs_pass_with_key(client, token, db_session):
    key = db_session.query(models.Item).filter_by(name="Rusty Key").first()
    key.room_id, key.player_id = None, 1     # give Bryan the Rusty Key
    db_session.commit()
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        for dx, dy in [(0,1),(1,0),(1,0),(1,0),(1,0)]:   # onto the down stairs
            ws.send_json({"cmd": "move", "dx": dx, "dy": dy})
        zs = _drain_until(ws, lambda m: m["event"] == "zone_state" and m["room"]["name"] == "Cellar")
        assert zs is not None
        assert (zs["you"]["x"], zs["you"]["y"]) == (3, 3)   # just below the up stairs


def test_using_key_crumbles_it_and_opens_door(client, token, db_session):
    import database
    key = db_session.query(models.Item).filter_by(name="Rusty Key").first()
    key.room_id = key.tile_x = key.tile_y = None
    key.player_id = 1                       # Bryan carries the Rusty Key
    db_session.commit()
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        for dx, dy in [(0, 1), (1, 0), (1, 0), (1, 0), (1, 0)]:   # onto the down stairs
            ws.send_json({"cmd": "move", "dx": dx, "dy": dy})
        assert _drain_until(ws, lambda m: m["event"] == "zone_state"
                            and m["room"]["name"] == "Cellar") is not None
    assert world.door_is_open(1, "down")    # open for everyone now
    db = database.SessionLocal()
    try:                                    # the key crumbled to dust (nowhere)
        k = db.query(models.Item).filter_by(name="Rusty Key").first()
        assert k.player_id is None and k.room_id is None and k.tile_x is None
    finally:
        db.close()


def test_open_door_lets_keyless_player_pass(client, token, db_session):
    world.open_door(1, "down", 600)         # someone already opened it; no key needed
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        for dx, dy in [(0, 1), (1, 0), (1, 0), (1, 0), (1, 0)]:
            ws.send_json({"cmd": "move", "dx": dx, "dy": dy})
        assert _drain_until(ws, lambda m: m["event"] == "zone_state"
                            and m["room"]["name"] == "Cellar") is not None


def test_relock_respawns_key(db_session):
    import database, services
    world.load()                            # arms doors → records the key's floor home
    assert (1, "down") not in world.door_unlocks
    kid = db_session.query(models.Item).filter_by(name="Rusty Key").first().id
    assert kid in world.key_home
    # Open the door and crumble the key, then force the window to expire.
    world.open_door(1, "down", 600)
    db = database.SessionLocal()
    try:
        services.ItemService.destroy(db, kid)
    finally:
        db.close()
    world.door_unlocks[(1, "down")] = 0.0   # expired
    asyncio.run(game_loop._relock_doors())
    assert not world.door_is_open(1, "down")        # re-locked
    db = database.SessionLocal()
    try:                                    # key reformed on the Foyer floor
        k = db.query(models.Item).filter_by(id=kid).first()
        assert k.room_id == 1 and k.tile_x is not None and k.player_id is None
    finally:
        db.close()
    assert world.item_at(1, k.tile_x, k.tile_y) == kid   # present in the live world


def test_zone_state_carries_room_description(client, token):
    with _ws(client, token, 1) as ws:
        zs = _drain_until(ws, lambda m: m["event"] == "zone_state")
        assert zs["room"]["name"] == "Foyer"
        assert zs["room"]["description"] == "A grand entrance hall."   # for the Room window


def test_map_command_returns_graph(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "map"})
        m = ws.receive_json()
        assert m["event"] == "world_map"
        assert {r["name"] for r in m["rooms"]} >= {"Foyer", "Great Hall", "Cellar"}
