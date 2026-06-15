"""Realtime gameplay tests over WebSocket — tile protocol (Phase 1).

The DeepSeek key is blank (see conftest), so `talk` exercises the rule-based
NPC fallback. Combat uses a monkeypatched attack roll for determinism. The live
combat tick is disabled in tests (conftest sets COMBAT_TICK_SECONDS huge), so
mobs don't act on their own and event streams stay deterministic.

The WebSocket is authenticated: connects pass the admin's access token as
`?token=`, and Bryan (id 1) and Aria are characters of that account, so the
ownership check passes. See conftest's `token` fixture.

Tile geometry (conftest Foyer 8x6): player spawns at (2,2); the Caretaker (the
hostile, combatant test mob) sits one tile east at (3,2); the Innkeeper
(non-combatant) at (5,4).
"""
import main
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


def test_connect_sends_zone_state(client, token):
    with _ws(client, token, 1) as ws:
        m = ws.receive_json()
        assert m["event"] == "zone_state"
        assert m["room"]["name"] == "Foyer"
        assert m["tiles"]["w"] == 8 and m["tiles"]["h"] == 6
        assert (m["you"]["x"], m["you"]["y"]) == (2, 2)
        assert {e["name"] for e in m["entities"]} == {"Caretaker", "Innkeeper"}


def test_two_clients_chat(client, token):
    aria_id = _make_aria(client)
    with _ws(client, token, 1) as bryan:
        bryan.receive_json()  # zone_state
        with _ws(client, token, aria_id) as aria:
            aria.receive_json()  # zone_state
            spawned = bryan.receive_json()
            assert spawned["event"] == "entity_spawned" and spawned["name"] == "Aria"
            assert spawned["kind"] == "player" and "x" in spawned

            bryan.send_json({"cmd": "say", "text": "hi"})
            chat = aria.receive_json()
            assert chat["event"] == "chat"
            assert chat["from"] == "Bryan" and chat["text"] == "hi"


def test_move_broadcasts_entity_moved(client, token):
    aria_id = _make_aria(client)
    with _ws(client, token, 1) as bryan:
        bryan.receive_json()
        with _ws(client, token, aria_id) as aria:
            aria.receive_json()
            bryan.receive_json()  # entity_spawned (Aria)

            # Bryan steps north (2,2) -> (2,1); both clients see entity_moved.
            bryan.send_json({"cmd": "move", "dx": 0, "dy": -1})
            moved = aria.receive_json()
            assert moved["event"] == "entity_moved"
            assert moved["id"] == 1 and (moved["x"], moved["y"]) == (2, 1)


def test_move_into_wall_is_silent(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # zone_state at (2,2)
        # West twice: (2,2)->(1,2) MOVED, then (1,2)->(0,2) is a wall -> no event.
        ws.send_json({"cmd": "move", "dx": -1, "dy": 0})
        assert ws.receive_json()["event"] == "entity_moved"
        ws.send_json({"cmd": "move", "dx": -1, "dy": 0})  # blocked, silent
        ws.send_json({"cmd": "look"})
        assert ws.receive_json()["event"] == "zone_state"  # next msg, not a move


def test_diagonal_move_rejected(client, token):
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "move", "dx": 1, "dy": 1})
        m = ws.receive_json()
        assert m["event"] == "error" and "orthogonal" in m["detail"]


def test_move_cooldown_enforced(client, token, monkeypatch):
    monkeypatch.setattr(main, "MOVE_COOLDOWN_SECONDS", 30.0)
    main._last_move.clear()
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # zone_state
        ws.send_json({"cmd": "move", "dx": 0, "dy": -1})
        assert ws.receive_json()["event"] == "entity_moved"
        ws.send_json({"cmd": "move", "dx": 0, "dy": -1})  # within cooldown -> dropped
        ws.send_json({"cmd": "look"})
        assert ws.receive_json()["event"] == "zone_state"  # not a 2nd entity_moved


def test_bump_to_attack(client, token, monkeypatch):
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 3})
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # zone_state, player at (2,2), Caretaker at (3,2)
        ws.send_json({"cmd": "move", "dx": 1, "dy": 0})  # bump east into the Caretaker
        m = ws.receive_json()
        assert m["event"] == "combat"
        assert m["attacker"] == "Bryan" and m["target"] == "Caretaker"
        assert m["hit"] is True and m["damage"] == 3


def test_explicit_attack_defeats_npc(client, token, monkeypatch):
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 50})
    cid = npc_id_by_name(client, "Caretaker")
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # zone_state (player adjacent to the Caretaker)
        ws.send_json({"cmd": "attack", "target_id": cid})
        events = [ws.receive_json() for _ in range(2)]
        kinds = [e["event"] for e in events]
        assert "combat" in kinds
        died = next(e for e in events if e["event"] == "entity_died")
        assert died["id"] == cid and died["kind"] == "npc"

        ws.send_json({"cmd": "look"})
        snap = ws.receive_json()
        assert snap["event"] == "zone_state"
        assert "Caretaker" not in {e["name"] for e in snap["entities"]}


def test_attack_out_of_reach_rejected(client, token):
    cid = npc_id_by_name(client, "Caretaker")
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # at (2,2)
        # Step west away from the Caretaker so it's no longer adjacent.
        ws.send_json({"cmd": "move", "dx": -1, "dy": 0})
        ws.receive_json()  # entity_moved to (1,2)
        ws.send_json({"cmd": "attack", "target_id": cid})
        m = ws.receive_json()
        assert m["event"] == "error" and "out of reach" in m["detail"]


def test_attack_noncombatant_rejected(client, token):
    iid = npc_id_by_name(client, "Innkeeper")
    with _ws(client, token, 1) as ws:
        ws.receive_json()
        ws.send_json({"cmd": "attack", "target_id": iid})
        m = ws.receive_json()
        assert m["event"] == "error" and "cannot be fought" in m["detail"]


def test_talk_triggers_async_npc_turn(client, token):
    cid = npc_id_by_name(client, "Caretaker")
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # zone_state
        ws.send_json({"cmd": "talk", "npc_id": cid, "text": "who are you?"})
        events = []
        for _ in range(5):
            events.append(ws.receive_json()["event"])
            if "npc_said" in events:
                break
        assert "chat" in events          # the player's question, echoed to the room
        assert "npc_thinking" in events
        assert "npc_said" in events


def test_player_defeat_and_respawn(client, token, db_session, monkeypatch):
    """A mob's strike (via the combat tick) can defeat and respawn the player."""
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 50})
    player = db_session.query(models.Player).get(1)
    player.health, player.max_health = 1, 10
    db_session.commit()

    import game_loop
    with _ws(client, token, 1) as ws:
        ws.receive_json()  # zone_state (player at (2,2), hostile Caretaker adjacent)
        # Drive one mob-AI tick from the test (the live tick is disabled).
        client.portal.call(game_loop._combat_tick_once)
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
