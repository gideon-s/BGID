"""Auth + character-ownership tests.

`client` is authenticated as the seeded admin `tester` (owns Bryan/id 1).
`anon_client` is unauthenticated. `user_headers` belongs to `intruder`, a
logged-in account that owns no characters.
"""


# ---------- Registration / login ----------
def test_register_returns_user_and_tokens(anon_client):
    r = anon_client.post("/auth/register", json={"username": "Newbie", "password": "Passw0rd!"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["username"] == "Newbie"
    assert body["tokens"]["access_token"] and body["tokens"]["refresh_token"]
    # role is 'player' (an admin already exists: the seeded tester)
    assert body["user"]["role"] == "player"


def test_register_rejects_duplicate_username(anon_client):
    assert anon_client.post("/auth/register",
                            json={"username": "tester", "password": "Passw0rd!"}).status_code == 409


def test_register_rejects_weak_password(anon_client):
    r = anon_client.post("/auth/register", json={"username": "Weakling", "password": "short"})
    assert r.status_code == 422


def test_login_and_use_token(anon_client):
    anon_client.post("/auth/register", json={"username": "Dana", "password": "Passw0rd!"})
    r = anon_client.post("/auth/login", json={"username": "Dana", "password": "Passw0rd!"})
    assert r.status_code == 200, r.text
    token = r.json()["tokens"]["access_token"]
    me = anon_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "Dana"


def test_login_wrong_password_401(anon_client):
    anon_client.post("/auth/register", json={"username": "Erin", "password": "Passw0rd!"})
    r = anon_client.post("/auth/login", json={"username": "Erin", "password": "WrongPass9"})
    assert r.status_code == 401


def test_me_requires_auth(anon_client):
    assert anon_client.get("/auth/me").status_code == 401  # no bearer credentials


def test_refresh_rotates_and_revokes(anon_client):
    reg = anon_client.post("/auth/register", json={"username": "Finn", "password": "Passw0rd!"}).json()
    rt = reg["tokens"]["refresh_token"]
    first = anon_client.post("/auth/refresh", json={"refresh_token": rt})
    assert first.status_code == 200
    # The consumed refresh token is now revoked (single-use rotation).
    again = anon_client.post("/auth/refresh", json={"refresh_token": rt})
    assert again.status_code == 401


# ---------- Characters ----------
def test_create_and_list_character(anon_client):
    reg = anon_client.post("/auth/register", json={"username": "Gwen", "password": "Passw0rd!"}).json()
    h = {"Authorization": f"Bearer {reg['tokens']['access_token']}"}
    c = anon_client.post("/characters", json={"name": "Gwendolyn"}, headers=h)
    assert c.status_code == 201, c.text
    assert c.json()["name"] == "Gwendolyn" and c.json()["room_id"] == 1
    lst = anon_client.get("/characters", headers=h).json()
    assert [ch["name"] for ch in lst] == ["Gwendolyn"]


def test_character_name_collision_409(anon_client):
    reg = anon_client.post("/auth/register", json={"username": "Hank", "password": "Passw0rd!"}).json()
    h = {"Authorization": f"Bearer {reg['tokens']['access_token']}"}
    # "Bryan" is already taken (seeded, owned by tester)
    assert anon_client.post("/characters", json={"name": "Bryan"}, headers=h).status_code == 409


def test_me_lists_owned_characters(client):
    # client = admin 'tester', who owns the seeded Bryan
    me = client.get("/auth/me").json()
    assert me["user"]["username"] == "tester"
    assert "Bryan" in [c["name"] for c in me["characters"]]


# ---------- Ownership / admin gates ----------
def test_action_requires_auth(anon_client):
    r = anon_client.post("/action", json={"player_id": 1, "action_type": "move",
                                          "parameters": {"direction": "north"}})
    assert r.status_code == 401  # no bearer credentials


def test_action_rejects_unowned_character(anon_client, user_headers):
    # intruder owns no characters; acting as Bryan (id 1) must 403
    r = anon_client.post("/action", json={"player_id": 1, "action_type": "move",
                                          "parameters": {"direction": "north"}},
                         headers=user_headers)
    assert r.status_code == 403


def test_admin_endpoint_blocked_for_plain_user(anon_client, user_headers):
    r = anon_client.post("/npcs/", json={"name": "Wraith", "description": "x",
                                         "npc_type": "combat_mob", "room_id": 1},
                         headers=user_headers)
    assert r.status_code == 403


def test_admin_endpoint_allowed_for_admin(client):
    # client = admin
    r = client.post("/npcs/", json={"name": "Wraith", "description": "x",
                                    "npc_type": "combat_mob", "room_id": 1})
    assert r.status_code == 200, r.text
