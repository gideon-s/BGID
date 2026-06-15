"""
Shared pytest fixtures.

Tests run the app in-process via FastAPI's TestClient against an isolated
SQLite database, with the DeepSeek key blanked so NPC responses fall back to
the deterministic rule-based path (no network, no cost).

The env vars MUST be set before any app module imports config, so they live at
the top of this file (conftest is imported before test modules).
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_bgid.db"
os.environ["DEEPSEEK_API_KEY"] = ""  # force rule-based NPC fallback; no network
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")  # stable tokens
# Disable the live mob-AI tick during tests so it can't inject nondeterministic
# combat events into WS streams; the AI is exercised by calling
# game_loop._combat_tick_once() directly. Drop the move cooldown so movement
# tests aren't silently rate-limited.
os.environ["COMBAT_TICK_SECONDS"] = "3600"
os.environ["MOVE_COOLDOWN_SECONDS"] = "0"

# Tiled test world. Foyer (8x6): players spawn at (2,2); the Caretaker (hostile
# test mob) sits at (3,2), the Innkeeper at (5,4). North door (4,0) → Great Hall;
# down stairs (6,3) → Cellar (locked, Rusty Key). Doors/stairs align to the
# seeded RoomExits below so zone transitions are exercised.
FOYER_TILES = "\n".join([
    "####+###",   # north door (4,0) -> Great Hall
    "#......#",
    "#......#",
    "#.....>#",   # down stairs (6,3) -> Cellar (locked)
    "#......#",
    "########",
])
FOYER_W, FOYER_H, FOYER_SPAWN = 8, 6, (2, 2)

# Great Hall (7x5): south door (2,4) -> Foyer.
HALL_TILES = "\n".join([
    "#######",
    "#.....#",
    "#.....#",
    "#.....#",
    "##+####",
])
HALL_W, HALL_H, HALL_SPAWN = 7, 5, (3, 2)

# Cellar (7x5): up stairs (3,2) -> Foyer.
CELLAR_TILES = "\n".join([
    "#######",
    "#.....#",
    "#..<..#",
    "#.....#",
    "#######",
])
CELLAR_W, CELLAR_H, CELLAR_SPAWN = 7, 5, (3, 3)

import pathlib
import pytest
from fastapi.testclient import TestClient

# Known account credentials seeded into every test DB.
ADMIN_USERNAME = "tester"      # admin role; owns Bryan (player id=1)
OTHER_USERNAME = "intruder"    # plain player; owns no characters


def _seed(db):
    """Seed a known world + two accounts.

    Accounts: `tester` (admin, owns Bryan) and `intruder` (plain player, owns
    nothing) — enough to exercise auth, ownership, and admin gating.
    World: 3 rooms, Bryan (player id=1), 2 NPCs (combat + non-combat), 1 item.
    """
    import models
    from security import hash_password

    tester = models.User(username=ADMIN_USERNAME, password_hash=hash_password("Passw0rd!"),
                         role="admin")
    intruder = models.User(username=OTHER_USERNAME, password_hash=hash_password("Passw0rd!"),
                           role="player")
    db.add_all([tester, intruder])
    db.commit()

    foyer = models.Room(name="Foyer", description="A grand entrance hall.",
                        width=FOYER_W, height=FOYER_H, tiles=FOYER_TILES,
                        spawn_x=FOYER_SPAWN[0], spawn_y=FOYER_SPAWN[1])
    hall = models.Room(name="Great Hall", description="A vast chamber.",
                       width=HALL_W, height=HALL_H, tiles=HALL_TILES,
                       spawn_x=HALL_SPAWN[0], spawn_y=HALL_SPAWN[1])
    cellar = models.Room(name="Cellar", description="A musty cellar.",
                         width=CELLAR_W, height=CELLAR_H, tiles=CELLAR_TILES,
                         spawn_x=CELLAR_SPAWN[0], spawn_y=CELLAR_SPAWN[1])
    db.add_all([foyer, hall, cellar])
    db.commit()

    rusty = models.Item(name="Rusty Key", description="Pitted iron.",
                        item_type="key", value=1, room_id=foyer.id,
                        glyph="🔑", tile_x=1, tile_y=4)
    # Phase 3 gear on the Foyer floor (for inventory/equipment tests).
    sword = models.Item(name="Iron Sword", description="A plain blade.",
                        item_type="weapon", room_id=foyer.id, glyph="⚔️",
                        tile_x=1, tile_y=1, is_movable=True, is_equippable=True,
                        equip_slot="weapon", attack_bonus=1, damage_bonus=2)
    armor = models.Item(name="Leather Armor", description="Boiled hide.",
                        item_type="armor", room_id=foyer.id, glyph="🛡️",
                        tile_x=4, tile_y=1, is_movable=True, is_equippable=True,
                        equip_slot="armor", defense_bonus=2)
    db.add_all([rusty, sword, armor])
    db.commit()

    # Foyer <-> Great Hall (open); Foyer -> Cellar (locked, Rusty Key); Cellar -> Foyer (open)
    db.add_all([
        models.RoomExit(from_room_id=foyer.id, to_room_id=hall.id, direction="north"),
        models.RoomExit(from_room_id=hall.id, to_room_id=foyer.id, direction="south"),
        models.RoomExit(from_room_id=foyer.id, to_room_id=cellar.id, direction="down",
                        is_locked=True, key_item_id=rusty.id),
        models.RoomExit(from_room_id=cellar.id, to_room_id=foyer.id, direction="up"),
    ])
    db.commit()

    db.add(models.Player(id=1, name="Bryan", room_id=foyer.id, user_id=tester.id))
    # Caretaker doubles as the hostile mob for tile/AI tests: combat_enabled AND
    # is_hostile, positioned one tile east of the player spawn so bump- and
    # explicit-attack tests reach it without moving.
    db.add(models.Npc(name="Caretaker", description="A watchful presence.",
                      npc_type="combat_mob", room_id=foyer.id,
                      is_friendly=False, combat_enabled=True, is_hostile=True,
                      aggro_radius=6, glyph="👺", home_x=3, home_y=2))
    db.add(models.Npc(name="Innkeeper", description="Polite, not a fighter.",
                      npc_type="innkeeper", room_id=foyer.id,
                      combat_enabled=False, is_hostile=False,
                      glyph="🧑", home_x=5, home_y=4))
    db.commit()


def auth_token(username=ADMIN_USERNAME):
    """Mint a raw access token for a seeded user (no login round-trip).
    Used for the `?token=` WebSocket query param."""
    import database, models, security
    db = database.SessionLocal()
    try:
        user = db.query(models.User).filter_by(username=username).first()
        return security.create_access_token(user.id)
    finally:
        db.close()


def _headers_for(username):
    """Mint a Bearer auth header for a seeded user."""
    return {"Authorization": f"Bearer {auth_token(username)}"}


@pytest.fixture(autouse=True)
def _reset_mob_clocks():
    """Clear mob aggro/cooldown state before every test so unit tests that drive
    game_loop._combat_tick_once() directly aren't affected by a prior test's
    clocks (the client fixture also clears these via _reset_singletons)."""
    import game_loop
    import smack_talk
    import combat
    import casting
    game_loop._aggroed.clear()
    game_loop._last_move_at.clear()
    game_loop._last_attack_at.clear()
    combat._respawn_grace.clear()
    casting.reset()
    smack_talk.reset()
    yield


@pytest.fixture
def db_session():
    """Fresh, seeded database for each test. Yields an open session."""
    import database
    import models  # noqa: F401 — registers tables on Base.metadata
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    db = database.SessionLocal()
    try:
        _seed(db)
        yield db
    finally:
        db.close()


def _reset_singletons():
    import websocket_manager
    import chat_system
    import rate_limit
    import smack_talk
    import game_loop
    websocket_manager.manager.active_connections.clear()
    websocket_manager.manager.room_subscriptions.clear()
    chat_system.chat_manager.global_messages.clear()
    chat_system.chat_manager.room_messages.clear()
    chat_system.chat_manager.private_messages.clear()
    rate_limit.reset()       # clear per-account talk + mob-chatter counters
    smack_talk.reset()       # clear per-mob smack-talk cooldowns
    game_loop._aggroed.clear()      # clear mob aggro state
    game_loop._last_move_at.clear()    # clear mob move/attack cooldown clocks
    game_loop._last_attack_at.clear()
    import combat
    combat._respawn_grace.clear()   # clear post-respawn invulnerability windows
    import casting
    casting.reset()                 # clear per-(player,spell) cast cooldowns


@pytest.fixture
def client(db_session):
    """Authenticated TestClient — sends `tester` (admin, owns Bryan) by default,
    so the bulk of gameplay/admin tests work without per-call headers.

    Startup loads the world from the seeded DB; in-memory singletons are reset
    so state doesn't leak between tests. Use `anon_client` for public/negative
    auth tests and `user_headers` to act as a non-owner.
    """
    import main
    _reset_singletons()
    with TestClient(main.app) as c:
        c.headers.update(_headers_for(ADMIN_USERNAME))
        yield c


@pytest.fixture
def anon_client(db_session):
    """Unauthenticated TestClient — for public endpoints, the auth flows, and
    '401 without a token' negative tests."""
    import main
    _reset_singletons()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def user_headers():
    """Auth header for `intruder` — a logged-in account that owns no characters
    (used to assert cross-account 403s)."""
    return _headers_for(OTHER_USERNAME)


@pytest.fixture
def admin_headers():
    return _headers_for(ADMIN_USERNAME)


@pytest.fixture
def token(db_session):
    """Raw admin access token (for `?token=` on WebSocket connects)."""
    return auth_token(ADMIN_USERNAME)


def npc_id_by_name(client, name):
    """Helper: look up an NPC id by name via the API."""
    npcs = client.get("/npcs/").json()["items"]
    return next(n["id"] for n in npcs if n["name"] == name)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_db():
    yield
    p = pathlib.Path("test_bgid.db")
    if p.exists():
        p.unlink()
