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


# ---------- map designer support (handoff-10 §2 / P6) ----------
def test_tiles_palette(client):
    r = client.get("/tiles")
    assert r.status_code == 200
    glyphs = {t["glyph"]: t for t in r.json()["tiles"]}
    assert "#" in glyphs and glyphs["#"]["walkable"] is False
    assert "." in glyphs and glyphs["."]["walkable"] is True
    assert glyphs[">"]["transition"] == "down"


def test_mapgen_endpoint(client, admin_headers):
    r = client.post("/admin/mapgen", json={"kind": "rooms", "width": 30, "height": 18, "seed": 3},
                    headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["width"] == 30 and body["height"] == 18 and len(body["tiles"]) == 18
    assert all(len(row) == 30 for row in body["tiles"])
    import mapgen
    assert mapgen.validate(body["tiles"])


def test_mapgen_bad_kind(client, admin_headers):
    assert client.post("/admin/mapgen", json={"kind": "nope", "width": 20, "height": 20},
                       headers=admin_headers).status_code == 400


def test_mapgen_admin_only(client, user_headers):
    assert client.post("/admin/mapgen", json={"kind": "cave", "width": 20, "height": 20},
                       headers=user_headers).status_code == 403


def test_designer_save_round_trip(client, admin_headers):
    """A generated grid saved via PUT /rooms loads back through the world."""
    from world import world
    grid = client.post("/admin/mapgen", json={"kind": "rooms", "width": 20, "height": 12, "seed": 9},
                       headers=admin_headers).json()["tiles"]
    rid = client.post("/rooms/", json={"name": "Designed", "description": "by the tool"},
                      headers=admin_headers).json()["id"]
    r = client.put(f"/rooms/{rid}", json={"width": 20, "height": 12,
                                          "tiles": "\n".join(grid), "spawn_x": 1, "spawn_y": 1},
                   headers=admin_headers)
    assert r.status_code == 200
    node = world.rooms[rid]
    assert node.width == 20 and node.height == 12 and len(node.tiles) == 12


def test_levels_endpoints(client, admin_headers, user_headers):
    assert client.get("/levels").status_code == 200
    r = client.post("/levels", json={"name": "Crypt", "description": "deep"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["name"] == "Crypt"
    assert any(l["name"] == "Crypt" for l in client.get("/levels").json())
    # admin-only create
    assert client.post("/levels", json={"name": "X"}, headers=user_headers).status_code == 403
