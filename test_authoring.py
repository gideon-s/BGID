"""World-authoring admin endpoints (handoff-10 §3): room/npc/feature CRUD + the
world-reload trigger. The `client` fixture authenticates as admin; pass
`headers=user_headers` to act as a non-admin."""
import database
import models
from world import world


def _npc_id(client, name):
    npcs = client.get("/npcs/").json()["items"]
    return next(n["id"] for n in npcs if n["name"] == name)


# ---------- NPC update / create / delete (with AI/tile fields) ----------
def test_update_npc_reflects_in_world(client, admin_headers):
    cid = _npc_id(client, "Caretaker")
    r = client.put(f"/npcs/{cid}",
                   json={"glyph": "🦂", "aggro_radius": 9, "wanders": True},
                   headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["glyph"] == "🦂" and body["aggro_radius"] == 9 and body["wanders"] is True
    meta = world.rooms[1].npc_meta[cid]            # world.reload() ran in the endpoint
    assert meta["glyph"] == "🦂" and meta["aggro_radius"] == 9 and meta["wanders"] is True


def test_update_npc_abilities(client, admin_headers):
    cid = _npc_id(client, "Caretaker")
    assert client.put(f"/npcs/{cid}", json={"abilities": {"str": 18}},
                      headers=admin_headers).status_code == 200
    db = database.SessionLocal()
    try:
        assert db.get(models.Npc, cid).str == 18
    finally:
        db.close()


def test_create_npc_with_ai_fields(client, admin_headers):
    r = client.post("/npcs/", json={"name": "Bat", "room_id": 1, "npc_type": "combat_mob",
                                    "is_hostile": True, "glyph": "🦇", "wanders": True,
                                    "aggro_radius": 5}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["glyph"] == "🦇"
    assert any(world.rooms[1].npc_meta[i]["glyph"] == "🦇" for i in world.rooms[1].npc_ids)


def test_delete_npc(client, admin_headers):
    nid = client.post("/npcs/", json={"name": "Temp", "room_id": 1, "npc_type": "combat_mob"},
                      headers=admin_headers).json()["id"]
    assert client.delete(f"/npcs/{nid}", headers=admin_headers).status_code == 200
    assert client.get(f"/npcs/{nid}").status_code == 404
    assert nid not in world.rooms[1].npc_ids


# ---------- Room update / delete ----------
def test_update_room(client, admin_headers):
    r = client.put("/rooms/1", json={"description": "Changed", "spawn_x": 3, "spawn_y": 3},
                   headers=admin_headers)
    assert r.status_code == 200
    assert world.rooms[1].description == "Changed" and world.rooms[1].spawn == (3, 3)


def test_delete_room(client, admin_headers):
    rid = client.post("/rooms/", json={"name": "Scratch", "description": "x"},
                      headers=admin_headers).json()["id"]
    assert client.delete(f"/rooms/{rid}", headers=admin_headers).status_code == 200
    assert client.get(f"/rooms/{rid}").status_code == 404
    assert rid not in world.rooms


# ---------- RoomFeature CRUD ----------
def test_feature_crud(client, admin_headers):
    r = client.post("/rooms/1/features",
                    json={"x": 2, "y": 2, "kind": "trap", "glyph": "^", "config": {"damage": 3}},
                    headers=admin_headers)
    assert r.status_code == 200 and r.json()["config"]["damage"] == 3
    fid = r.json()["id"]
    assert world.feature_at(1, 2, 2, "trap") is not None
    feats = client.get("/rooms/1/features", headers=admin_headers).json()
    assert any(f["id"] == fid for f in feats)
    r = client.put(f"/features/{fid}", json={"config": {"damage": 9}}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["config"]["damage"] == 9
    assert client.delete(f"/features/{fid}", headers=admin_headers).status_code == 200
    assert world.feature_at(1, 2, 2, "trap") is None


def test_world_reload_endpoint(client, admin_headers):
    assert client.post("/admin/world/reload", headers=admin_headers).status_code == 200


# ---------- auth: admin-only ----------
def test_authoring_admin_only(client, user_headers):
    assert client.put("/npcs/1", json={"glyph": "x"}, headers=user_headers).status_code == 403
    assert client.delete("/npcs/1", headers=user_headers).status_code == 403
    assert client.put("/rooms/1", json={"description": "x"}, headers=user_headers).status_code == 403
    assert client.delete("/rooms/1", headers=user_headers).status_code == 403
    assert client.post("/rooms/1/features", json={"x": 1, "y": 1, "kind": "sign"},
                       headers=user_headers).status_code == 403
    assert client.post("/admin/world/reload", headers=user_headers).status_code == 403
