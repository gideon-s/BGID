"""Portrait generation tests (Phase 5).

The Novita key is blank (see conftest), so the portrait manager is "not
configured" by default — every test that wants generation monkeypatches the
global manager to be enabled and replaces its `generate_image` with a mock that
returns fixed bytes. **No live API calls are ever made.**

The cache contract under test: one API call per portrait, ever. Identical
prompts hash to one file; a set `portrait_url`, an adopted on-disk file, or an
in-flight job all short-circuit the next call.
"""
import asyncio
import os

import pytest

import config
import database
import models
import novita_integration
import portraits
import world as world_mod
from conftest import npc_id_by_name


# ─── helpers ───
def _innkeeper_id():
    db = database.SessionLocal()
    try:
        return db.query(models.Npc).filter_by(name="Innkeeper").first().id
    finally:
        db.close()


def _portrait_url_in_db(kind, subject_id):
    db = database.SessionLocal()
    try:
        model = models.Npc if kind == "npc" else models.Player
        return db.query(model).filter_by(id=subject_id).first().portrait_url
    finally:
        db.close()


@pytest.fixture
def portrait_dir(tmp_path, monkeypatch):
    """Point the portrait store at a throwaway dir; clear the in-flight guard."""
    monkeypatch.setattr(portraits, "PORTRAIT_DIR", str(tmp_path))
    portraits._inflight.clear()
    yield tmp_path
    portraits._inflight.clear()


@pytest.fixture
def enabled_manager(monkeypatch):
    """Make the global manager 'enabled' with a counting, byte-returning mock.

    Returns a dict with a `calls` counter and the fixed `image` bytes.
    """
    state = {"calls": 0, "image": b"\x89PNG\r\n\x1a\nFAKEPORTRAIT"}

    async def fake_generate(prompt, model, width, height):
        state["calls"] += 1
        state["last"] = {"model": model, "width": width, "height": height}
        return state["image"]

    monkeypatch.setattr(novita_integration.portrait_manager, "is_enabled",
                        lambda: True)
    monkeypatch.setattr(novita_integration.portrait_manager, "generate_image",
                        fake_generate)
    return state


@pytest.fixture
def record_broadcasts(monkeypatch):
    """Record portrait broadcasts (the lazy import resolves to this manager)."""
    import websocket_manager
    sent = []

    async def fake_broadcast(room_id, message, exclude_player=None):
        sent.append((room_id, message))

    monkeypatch.setattr(websocket_manager.manager, "broadcast_to_room",
                        fake_broadcast)
    return sent


async def _drain_pending():
    """Await every task except the current one (lets a spawned job finish)."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


# ─── service disabled (no key) ───
def test_manager_disabled_without_key():
    # conftest blanks NOVITA_API_KEY, so the global manager is dark.
    assert config.NOVITA_API_KEY == ""
    assert novita_integration.portrait_manager.is_enabled() is False


def test_ensure_portrait_noop_when_disabled(db_session, portrait_dir, monkeypatch):
    # Disabled: ensure_portrait returns None, spawns no job, sets no url.
    spawned = []
    monkeypatch.setattr(portraits.asyncio, "create_task",
                        lambda coro: spawned.append(coro))
    nid = _innkeeper_id()
    assert portraits.ensure_portrait("npc", nid, 1) is None
    assert spawned == []
    assert _portrait_url_in_db("npc", nid) is None


# ─── prompt building / hashing ───
def test_prompt_hash_stable_and_distinct():
    a = portraits.build_player_prompt("Bryan", "male", "dwarf", "warrior")
    b = portraits.build_player_prompt("Bryan", "male", "dwarf", "warrior")
    assert portraits._hash(a) == portraits._hash(b)        # stable
    # Distinct across each of race / gender / class.
    diff_race = portraits.build_player_prompt("Bryan", "male", "elf", "warrior")
    diff_gender = portraits.build_player_prompt("Bryan", "female", "dwarf", "warrior")
    diff_class = portraits.build_player_prompt("Bryan", "male", "dwarf", "mage")
    hashes = {portraits._hash(x) for x in (a, diff_race, diff_gender, diff_class)}
    assert len(hashes) == 4


def test_prompt_skips_empty_and_placeholder_tokens():
    # none/empty/wanderer tokens are dropped so the hash stays clean.
    p = portraits.build_player_prompt("Bryan", "none", "", "wanderer")
    assert "none" not in p and "wanderer" not in p
    assert p == portraits.build_player_prompt("Bryan", "", "none", "wanderer")


def test_npc_prompt_includes_type_and_description():
    p = portraits.build_npc_prompt("Innkeeper", "innkeeper", "Polite, not a fighter.")
    assert "Innkeeper" in p and "innkeeper" in p and "Polite" in p
    assert portraits.STYLE_SUFFIX in p


def test_appearance_folds_into_prompt_and_rekeys_hash():
    base = portraits.build_player_prompt("Bryan", "male", "dwarf", "warrior")
    looked = portraits.build_player_prompt("Bryan", "male", "dwarf", "warrior",
                                           "braided red beard, scarred hands")
    assert "braided red beard, scarred hands" in looked
    assert portraits._hash(base) != portraits._hash(looked)        # editing re-keys
    # Same appearance → same hash (stable / generate-once holds).
    again = portraits.build_player_prompt("Bryan", "male", "dwarf", "warrior",
                                          "braided red beard, scarred hands")
    assert portraits._hash(looked) == portraits._hash(again)


# ─── appearance editing (regenerate-on-change) ───
def test_set_appearance_changes_text_and_clears_portrait(db_session):
    import auth_service
    db = database.SessionLocal()
    try:
        p = db.query(models.Player).filter_by(id=1).first()
        p.portrait_url = "/static/portraits/old.png"
        p.appearance = "plain"
        db.commit()
    finally:
        db.close()
    # A real change updates the text AND clears the cached portrait (→ regen).
    assert auth_service.CharacterService.set_appearance(database.SessionLocal(), 1,
                                                        "weathered, grey-eyed") is True
    db = database.SessionLocal()
    try:
        p = db.query(models.Player).filter_by(id=1).first()
        assert p.appearance == "weathered, grey-eyed"
        assert p.portrait_url is None
    finally:
        db.close()


def test_set_appearance_noop_when_unchanged(db_session):
    import auth_service
    db = database.SessionLocal()
    try:
        p = db.query(models.Player).filter_by(id=1).first()
        p.appearance = "same"
        p.portrait_url = "/static/portraits/keep.png"
        db.commit()
    finally:
        db.close()
    # No change → returns False, portrait pointer left intact.
    assert auth_service.CharacterService.set_appearance(database.SessionLocal(), 1,
                                                        "  same  ") is False
    db = database.SessionLocal()
    try:
        assert db.query(models.Player).filter_by(id=1).first().portrait_url \
            == "/static/portraits/keep.png"
    finally:
        db.close()


def test_create_stores_appearance(client):
    r = client.post("/characters", json={"name": "Mirabel", "char_class": "mage",
                                         "race": "elf", "gender": "female",
                                         "appearance": "violet eyes, silver circlet"})
    assert r.status_code == 201
    assert r.json()["appearance"] == "violet eyes, silver circlet"


def test_appearance_too_long_rejected(client):
    r = client.post("/characters", json={"name": "Verbose", "appearance": "x" * 401})
    assert r.status_code == 422


def test_set_appearance_over_ws_updates_sheet(client, token):
    with client.websocket_connect("/ws/1?token=" + token) as ws:
        ws.receive_json()                                # zone_state
        ws.send_json({"cmd": "set_appearance", "text": "cloaked in midnight blue"})
        msg = ws.receive_json()
        while msg["event"] != "character_sheet":
            msg = ws.receive_json()
        assert msg["appearance"] == "cloaked in midnight blue"


# ─── generate-once + caching ───
def test_generate_once_writes_file_sets_url_and_broadcasts(
        db_session, portrait_dir, enabled_manager, record_broadcasts):
    nid = _innkeeper_id()

    async def go():
        first = portraits.ensure_portrait("npc", nid, 1)
        await _drain_pending()
        return first

    first = asyncio.run(go())
    assert first is None                       # nothing cached yet → returns None
    assert enabled_manager["calls"] == 1       # exactly one API call
    # The portrait style's model + size were passed through to the generator.
    assert enabled_manager["last"] == {
        "model": config.NOVITA_PORTRAIT_MODEL,
        "width": config.NOVITA_PORTRAIT_WIDTH,
        "height": config.NOVITA_PORTRAIT_HEIGHT}
    # File written under the hash, DB pointer set, broadcast emitted.
    prompt = portraits.build_npc_prompt("Innkeeper", "innkeeper", "Polite, not a fighter.")
    h = portraits._hash(prompt)
    path = os.path.join(str(portrait_dir), f"{h}.png")
    assert os.path.exists(path)
    url = portraits._url_for(h)
    assert _portrait_url_in_db("npc", nid) == url
    assert record_broadcasts and record_broadcasts[0][1] == {
        "event": "portrait", "kind": "npc", "id": nid, "url": url}

    # Second call: cached url returned, NO new API call.
    assert portraits.ensure_portrait("npc", nid, 1) == url
    assert enabled_manager["calls"] == 1


def test_inflight_guard_dedupes_concurrent_calls(
        db_session, portrait_dir, enabled_manager, record_broadcasts):
    nid = _innkeeper_id()

    async def go():
        portraits.ensure_portrait("npc", nid, 1)   # spawns the one job
        portraits.ensure_portrait("npc", nid, 1)   # in-flight → no second job
        await _drain_pending()

    asyncio.run(go())
    assert enabled_manager["calls"] == 1


def test_existing_file_adopted_without_api_call(
        db_session, portrait_dir, enabled_manager, record_broadcasts):
    nid = _innkeeper_id()
    prompt = portraits.build_npc_prompt("Innkeeper", "innkeeper", "Polite, not a fighter.")
    h = portraits._hash(prompt)
    # Pre-stage a file for this subject's hash (e.g. surviving a DB wipe).
    portraits.ensure_portrait_dir()
    with open(portraits._path_for(h), "wb") as fh:
        fh.write(b"cached")
    url = portraits.ensure_portrait("npc", nid, 1)
    assert url == portraits._url_for(h)
    assert _portrait_url_in_db("npc", nid) == url
    assert enabled_manager["calls"] == 0       # adopted, never generated


def test_set_url_short_circuits(db_session, portrait_dir, enabled_manager):
    nid = _innkeeper_id()
    db = database.SessionLocal()
    try:
        npc = db.query(models.Npc).filter_by(id=nid).first()
        npc.portrait_url = "/static/portraits/preset.png"
        db.commit()
    finally:
        db.close()
    assert portraits.ensure_portrait("npc", nid, 1) == "/static/portraits/preset.png"
    assert enabled_manager["calls"] == 0


# ─── snapshot / sheet carry portrait_url ───
def test_zone_snapshot_carries_portrait_url(db_session):
    world_mod.world.load()
    world_mod.world.enter_world(1)
    world_mod.world.place_player(1, 1)
    snap = world_mod.world.zone_snapshot(1, 1)
    assert "portrait_url" in snap["you"]
    assert snap["you"]["portrait_url"] is None          # none generated yet
    for e in snap["entities"]:
        assert "portrait_url" in e


def test_character_sheet_carries_portrait_url(client, token):
    with client.websocket_connect(f"/ws/1?token={token}") as ws:
        ws.receive_json()                                # zone_state
        ws.send_json({"cmd": "sheet"})
        # The sheet is the next message addressed to this client.
        msg = ws.receive_json()
        while msg["event"] != "character_sheet":
            msg = ws.receive_json()
        assert "portrait_url" in msg
        assert msg["portrait_url"] is None


# ─── migration idempotency ───
def test_migration_idempotent(db_session):
    import migrate_phase5
    # Columns already exist (create_all built the current schema): re-running is
    # a no-op and must not raise.
    migrate_phase5.migrate()
    migrate_phase5.migrate()
    from sqlalchemy import text
    with database.engine.begin() as conn:
        pcols = {r[1] for r in conn.execute(text("PRAGMA table_info(players)"))}
        ncols = {r[1] for r in conn.execute(text("PRAGMA table_info(npcs)"))}
    assert "portrait_url" in pcols and "portrait_url" in ncols


def test_appearance_migration_idempotent(db_session):
    import migrate_appearance
    migrate_appearance.migrate()
    migrate_appearance.migrate()
    from sqlalchemy import text
    with database.engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(players)"))}
    assert "appearance" in cols
