"""Per-account rate limiting for LLM `talk` (DeepSeek cost control).

The limiter is in-memory and reset between tests (conftest._reset_singletons).
Limits are read from config per check, so we monkeypatch config to drive the
edge without waiting on wall-clock windows.
"""
import config
import rate_limit


# ---------- Unit ----------
def test_limiter_allows_then_blocks():
    rate_limit.reset()
    w = [(3, 60)]
    store = rate_limit._SlidingWindows()
    allowed = [store.check(("k", 1), w)[0] for _ in range(4)]
    assert allowed == [True, True, True, False]


def test_limiter_is_per_key():
    store = rate_limit._SlidingWindows()
    w = [(1, 60)]
    assert store.check(("k", "a"), w)[0] is True
    assert store.check(("k", "a"), w)[0] is False   # a is now blocked
    assert store.check(("k", "b"), w)[0] is True     # b is independent


def test_both_windows_enforced():
    """A hit is allowed only when every window has room."""
    store = rate_limit._SlidingWindows()
    w = [(100, 60), (2, 3600)]  # generous per-minute, tight per-hour
    res = [store.check(("k", 1), w)[0] for _ in range(3)]
    assert res == [True, True, False]  # blocked by the hourly cap


# ---------- REST /chat/npc ----------
def test_chat_npc_429_after_limit(client, monkeypatch):
    monkeypatch.setattr(config, "TALK_RATE_PER_MIN", 2)
    monkeypatch.setattr(config, "TALK_RATE_PER_HOUR", 1000)
    rate_limit.reset()
    cid = next(n["id"] for n in client.get("/npcs/").json()["items"] if n["name"] == "Caretaker")
    body = {"player_id": 1, "npc_id": cid, "message": "hello"}
    assert client.post("/chat/npc", json=body).status_code == 200
    assert client.post("/chat/npc", json=body).status_code == 200
    r = client.post("/chat/npc", json=body)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


# ---------- WebSocket talk ----------
def test_ws_talk_rate_limited(client, token, monkeypatch):
    """With the per-minute cap at 0, a `talk` is throttled before it echoes or
    spawns an NPC turn — the only reply is a rate-limit error."""
    monkeypatch.setattr(config, "TALK_RATE_PER_MIN", 0)
    rate_limit.reset()
    cid = next(n["id"] for n in client.get("/npcs/").json()["items"] if n["name"] == "Caretaker")
    with client.websocket_connect(f"/ws/1?token={token}") as ws:
        ws.receive_json()  # room_state
        ws.send_json({"cmd": "talk", "npc_id": cid, "text": "hi"})
        m = ws.receive_json()
        assert m["event"] == "error"
        assert "too quickly" in m["detail"] and m["retry_after"] >= 1
