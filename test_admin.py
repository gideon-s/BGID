"""Admin account & character management (/admin/*).

Seeded accounts (conftest): `tester` (admin, owns Bryan = player 1) and
`intruder` (plain player, owns nothing).
"""
import models


def _acct(client, headers, username):
    accts = client.get("/admin/accounts", headers=headers).json()
    return next(a for a in accts if a["username"] == username)


def test_list_accounts_admin_only(client, admin_headers, user_headers):
    r = client.get("/admin/accounts", headers=admin_headers)
    assert r.status_code == 200
    accts = {a["username"]: a for a in r.json()}
    assert {"tester", "intruder"} <= set(accts)
    assert accts["tester"]["role"] == "admin"
    assert any(c["name"] == "Bryan" for c in accts["tester"]["characters"])
    # a non-admin is forbidden
    assert client.get("/admin/accounts", headers=user_headers).status_code == 403


def test_promote_and_demote(client, admin_headers):
    intruder = _acct(client, admin_headers, "intruder")
    r = client.patch(f"/admin/accounts/{intruder['id']}", json={"role": "admin"},
                     headers=admin_headers)
    assert r.status_code == 200 and r.json()["role"] == "admin"
    r = client.patch(f"/admin/accounts/{intruder['id']}", json={"role": "player"},
                     headers=admin_headers)
    assert r.json()["role"] == "player"


def test_ban_blocks_login(client, anon_client, admin_headers):
    intruder = _acct(client, admin_headers, "intruder")
    r = client.patch(f"/admin/accounts/{intruder['id']}", json={"is_active": False},
                     headers=admin_headers)
    assert r.status_code == 200 and r.json()["is_active"] is False
    # the banned account can no longer log in
    login = anon_client.post("/auth/login", json={"username": "intruder", "password": "Passw0rd!"})
    assert login.status_code in (401, 403)


def test_cannot_demote_or_ban_self(client, admin_headers):
    me = _acct(client, admin_headers, "tester")
    assert client.patch(f"/admin/accounts/{me['id']}", json={"role": "player"},
                        headers=admin_headers).status_code == 400
    assert client.patch(f"/admin/accounts/{me['id']}", json={"is_active": False},
                        headers=admin_headers).status_code == 400


def test_delete_account_cascades_characters(client, admin_headers, db_session):
    import database
    # give intruder a character, then delete the account
    intruder = _acct(client, admin_headers, "intruder")
    p = models.Player(name="Doomed", user_id=intruder["id"], room_id=1)
    db_session.add(p); db_session.commit(); pid = p.id
    r = client.delete(f"/admin/accounts/{intruder['id']}", headers=admin_headers)
    assert r.status_code == 204
    # Assert against a FRESH session (db_session caches the rows it created).
    db = database.SessionLocal()
    try:
        assert db.get(models.Player, pid) is None           # character cascaded
        assert db.get(models.User, intruder["id"]) is None
    finally:
        db.close()


def test_cannot_delete_self(client, admin_headers):
    me = _acct(client, admin_headers, "tester")
    assert client.delete(f"/admin/accounts/{me['id']}", headers=admin_headers).status_code == 400


def test_admin_delete_character(client, admin_headers, db_session):
    r = client.delete("/admin/characters/1", headers=admin_headers)   # Bryan
    assert r.status_code == 204
    assert db_session.get(models.Player, 1) is None


def test_non_admin_cannot_manage(client, user_headers):
    assert client.patch("/admin/accounts/1", json={"role": "player"},
                        headers=user_headers).status_code == 403
    assert client.delete("/admin/accounts/1", headers=user_headers).status_code == 403
    assert client.delete("/admin/characters/1", headers=user_headers).status_code == 403
