"""Room exit (connection) API tests."""


def test_list_seeded_exits(client):
    exits = client.get("/rooms/1/exits").json()
    dirs = {e["direction"] for e in exits}
    assert dirs == {"north", "down"}
    down = next(e for e in exits if e["direction"] == "down")
    assert down["is_locked"] is True and down["to_room_id"] == 3


def test_create_exit_auto_reverses(client):
    # New room to connect to
    new_room = client.post("/rooms/", json={"name": "Attic", "description": "dusty"}).json()
    rid = new_room["id"]
    # Great Hall (2) --up--> Attic, should auto-create Attic --down--> Great Hall
    r = client.post("/rooms/2/exits", json={"direction": "up", "to_room_id": rid})
    assert r.status_code == 200, r.text
    assert r.json()["direction"] == "up" and r.json()["to_room_id"] == rid

    back = client.get(f"/rooms/{rid}/exits").json()
    assert any(e["direction"] == "down" and e["to_room_id"] == 2 for e in back)


def test_create_exit_one_way(client):
    new_room = client.post("/rooms/", json={"name": "Pit", "description": "deep"}).json()
    rid = new_room["id"]
    client.post("/rooms/2/exits", json={"direction": "down", "to_room_id": rid,
                                        "bidirectional": False})
    # No reverse exit created
    assert client.get(f"/rooms/{rid}/exits").json() == []


def test_invalid_direction_rejected(client):
    r = client.post("/rooms/1/exits", json={"direction": "sideways", "to_room_id": 2})
    assert r.status_code == 400


def test_duplicate_direction_conflict(client):
    # Foyer already has a 'north' exit (seeded)
    r = client.post("/rooms/1/exits", json={"direction": "north", "to_room_id": 3})
    assert r.status_code == 409


def test_self_loop_rejected(client):
    r = client.post("/rooms/1/exits", json={"direction": "east", "to_room_id": 1})
    assert r.status_code == 400


def test_delete_exit(client):
    r = client.delete("/rooms/1/exits/north")
    assert r.status_code == 200
    dirs = {e["direction"] for e in client.get("/rooms/1/exits").json()}
    assert "north" not in dirs


def test_create_refreshes_world(client):
    """Adding an exit via the API should be visible in the live world snapshot."""
    new_room = client.post("/rooms/", json={"name": "Garden", "description": "green"}).json()
    client.post("/rooms/2/exits", json={"direction": "east", "to_room_id": new_room["id"]})
    import world as world_mod
    assert world_mod.world.exit_in_direction(2, "east")["to_room_id"] == new_room["id"]
