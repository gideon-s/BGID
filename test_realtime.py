"""Realtime gameplay tests over WebSocket (steps 2-4).

The DeepSeek key is blank (see conftest), so `talk` exercises the rule-based
NPC fallback. Combat uses a monkeypatched attack roll for determinism.

The WebSocket is authenticated: connects pass the admin's access token as
`?token=`, and both Bryan (id 1) and Aria are characters of that account, so
the ownership check passes. See conftest's `token` fixture.
"""
import models
import combat
from conftest import npc_id_by_name


def _ws(client, token, player_id):
    """Authenticated websocket_connect for one of the admin's characters."""
    return client.websocket_connect(f"/ws/{player_id}?token={token}")


def _make_aria(client):
    """Create Aria as a character of the authed account (so the same token
    authorizes her socket), returning her id."""
    r = client.post("/characters", json={"name": "Aria"})
    return r.json()["id"]


def test_connect_sends_room_state(client, token):
    with _ws(client, token, 1) as ws:
        m = ws.receive_json()
        assert m["event"] == "room_state"
        assert m["room"]["name"] == "Foyer"
        assert {n["name"] for n in m["npcs"]} == {"Caretaker", "Innkeeper"}


def test_two_clients_chat(client, token):
    aria_id = _make_aria(client)
    with _ws(client, token, 1) as bryan:
        bryan.receive_json()  # room_state
        with _ws(client, token, aria_id) as aria:
            aria.receive_json()  # room_state
            entered = bryan.receive_json()
            assert entered["event"] == "player_entered" and entered["name"] == "Aria"

            bryan.send_json({"cmd": "say", "text": "hi"})
            chat = aria.receive_json()
            assert chat["event"] == "chat"
            assert chat["from"] == "Bryan" and chat["text"] == "hi"


def test_move_notifies_room_and_relocates(client, token):
    aria_id = _make_aria(client)
    with _ws(client, token, 1) as bryan:
        bryan.receive_json()
        with _ws(client, token, aria_id) as aria:
            aria.receive_json()
            bryan.receive_json()  # player_entered

            bryan.send_json({"cmd": "move", "room_id": 2})
            left = aria.receive_json()
            assert left["event"] == "player_left" and left["name"] == "Bryan"
            moved = bryan.receive_json()
            assert moved["event"] == "room_state" and moved["room"]["name"] == "Great Hall"


def test_move_by_direction(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # room_state (Foyer)
        ws.send_json({"cmd": "move", "dir": "north"})
        # player_left(old room, no one) then room_state for the mover
        snap = None
        for _ in range(3):
            m = ws.receive_json()
            if m["event"] == "room_state":
                snap = m
                break
        assert snap and snap["room"]["name"] == "Great Hall"


def test_move_locked_exit_blocked_without_key(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "move", "dir": "down"})  # Cellar door, locked
        m = ws.receive_json()
        assert m["event"] == "error" and "locked" in m["detail"]


def test_move_locked_exit_with_key(client, token, db_session):
    # Give Bryan the Rusty Key
    key = db_session.query(models.Item).filter_by(name="Rusty Key").first()
    key.room_id, key.player_id = None, 1
    db_session.commit()
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "move", "dir": "down"})
        snap = None
        for _ in range(3):
            m = ws.receive_json()
            if m["event"] == "room_state":
                snap = m
                break
        assert snap and snap["room"]["name"] == "Cellar"


def test_unknown_direction_errors(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "move", "dir": "west"})
        m = ws.receive_json()
        assert m["event"] == "error" and "can't go" in m["detail"]


def test_talk_triggers_async_npc_turn(client, token):
    cid = npc_id_by_name(client, "Caretaker")
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # room_state
        ws.send_json({"cmd": "talk", "npc_id": cid, "text": "who are you?"})
        events = []
        for _ in range(5):
            events.append(ws.receive_json()["event"])
            if "npc_said" in events:
                break
        assert "chat" in events          # the player's question, echoed to the room
        assert "npc_thinking" in events
        assert "npc_said" in events


def test_attack_defeats_npc(client, token, monkeypatch):
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d: {"hit": True, "damage": 50})
    cid = npc_id_by_name(client, "Caretaker")
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # room_state
        ws.send_json({"cmd": "attack", "npc_id": cid})
        events = [ws.receive_json()["event"] for _ in range(2)]
        assert "combat" in events
        assert "npc_defeated" in events

        ws.send_json({"cmd": "look"})
        snap = ws.receive_json()
        assert snap["event"] == "room_state"
        assert "Caretaker" not in [n["name"] for n in snap["npcs"]]


def test_attack_noncombatant_rejected(client, token):
    iid = npc_id_by_name(client, "Innkeeper")
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "attack", "npc_id": iid})
        m = ws.receive_json()
        assert m["event"] == "error" and "cannot be fought" in m["detail"]


def test_player_defeat_and_respawn(client, token, db_session, monkeypatch):
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d: {"hit": True, "damage": 1})
    player = db_session.query(models.Player).get(1)
    player.health = 1
    player.max_health = 10
    db_session.commit()

    cid = npc_id_by_name(client, "Caretaker")
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # room_state
        ws.send_json({"cmd": "attack", "npc_id": cid})
        events, respawn = [], None
        for _ in range(6):
            m = ws.receive_json()
            events.append(m["event"])
            if m["event"] == "respawn":
                respawn = m
                break
        assert "player_defeated" in events
        assert respawn is not None and respawn["health"] == 10


def test_unknown_command_errors(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "dance"})
        m = ws.receive_json()
        assert m["event"] == "error"


def test_ws_rejects_without_token(client):
    """No token → handshake is closed (4401)."""
    from starlette.websockets import WebSocketDisconnect
    import pytest
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/1") as ws:
            ws.receive_json()


def test_ws_rejects_other_users_character(client, db_session):
    """A valid token for a user who doesn't own the character → closed (4403)."""
    from conftest import auth_token, OTHER_USERNAME
    from starlette.websockets import WebSocketDisconnect
    import pytest
    intruder_tok = auth_token(OTHER_USERNAME)  # intruder owns no characters
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/1?token={intruder_tok}") as ws:
            ws.receive_json()
