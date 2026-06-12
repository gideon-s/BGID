"""HTTP API tests — covers the P0 fixes (ability serialization, error handler,
chat endpoints) plus basic CRUD."""
from conftest import npc_id_by_name


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_list_players_includes_abilities(client):
    r = client.get("/players/")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    abilities = items[0]["abilities"]
    assert set(abilities) == {"str", "dex", "con", "intel", "wis", "cha"}


def test_get_player(client):
    r = client.get("/players/1")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Bryan"
    assert "abilities" in body


def test_create_player(client):
    r = client.post("/players/", json={"name": "Aria", "room_id": 1})
    assert r.status_code == 200
    assert r.json()["name"] == "Aria"
    assert "abilities" in r.json()


def test_create_player_with_abilities(client):
    """Passing an abilities object must persist onto the flat columns (was a crash)."""
    r = client.post("/players/", json={
        "name": "Thora", "room_id": 1,
        "abilities": {"str": 16, "dex": 12, "con": 14, "intel": 8, "wis": 10, "cha": 13},
    })
    assert r.status_code == 200, r.text
    abilities = r.json()["abilities"]
    assert abilities["str"] == 16 and abilities["cha"] == 13


def test_create_npc_with_abilities(client):
    r = client.post("/npcs/", json={
        "name": "Ogre", "description": "huge", "npc_type": "combat_mob", "room_id": 1,
        "abilities": {"str": 18, "dex": 8, "con": 16, "intel": 6, "wis": 7, "cha": 5},
    })
    assert r.status_code == 200, r.text
    assert r.json()["abilities"]["str"] == 18


def test_list_npcs_includes_abilities(client):
    r = client.get("/npcs/")
    assert r.status_code == 200
    items = r.json()["items"]
    assert {n["name"] for n in items} == {"Caretaker", "Innkeeper"}
    assert "abilities" in items[0]


def test_create_npc(client):
    r = client.post("/npcs/", json={"name": "Goblin", "description": "snarls",
                                    "npc_type": "combat_mob", "room_id": 1})
    assert r.status_code == 200
    assert r.json()["name"] == "Goblin"


def test_404_returns_structured_json(client):
    """The error handler must return JSON, not crash with 'ErrorResponse not callable'."""
    r = client.get("/players/9999")
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert body["error"] == "Not Found"


def test_chat_send_and_history(client):
    r = client.post("/chat/send", json={"sender_id": 1, "message_type": "global",
                                        "content": "hello world"})
    assert r.status_code == 200
    sent = r.json()
    assert sent["sender_name"] == "Bryan"  # resolved from the DB
    assert sent["content"] == "hello world"

    h = client.get("/chat/history/global")
    assert h.status_code == 200
    contents = [m["content"] for m in h.json()["messages"]]
    assert "hello world" in contents


def test_rooms_and_items_work(client):
    assert client.get("/rooms/").status_code == 200
    assert client.get("/items/").status_code == 200
    assert client.get("/players/1/sheet").status_code == 200
    cid = npc_id_by_name(client, "Caretaker")
    assert client.get(f"/npcs/{cid}/sheet").status_code == 200


def test_chat_npc_rest_fallback(client):
    """/chat/npc returns a rule-based reply when DeepSeek is unavailable."""
    cid = npc_id_by_name(client, "Caretaker")
    r = client.post("/chat/npc", json={"player_id": 1, "npc_id": cid, "message": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["npc_name"] == "Caretaker"
    assert isinstance(body["response"], str) and body["response"]
