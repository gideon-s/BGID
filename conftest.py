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

import pathlib
import pytest
from fastapi.testclient import TestClient


def _seed(db):
    """Seed a known world: 2 rooms, 1 player, 2 NPCs (combat + non-combat), 1 item."""
    import models
    foyer = models.Room(name="Foyer", description="A grand entrance hall.")
    hall = models.Room(name="Great Hall", description="A vast chamber.")
    cellar = models.Room(name="Cellar", description="A musty cellar.")
    db.add_all([foyer, hall, cellar])
    db.commit()

    rusty = models.Item(name="Rusty Key", description="Pitted iron.",
                        item_type="key", value=1, room_id=foyer.id)
    db.add(rusty)
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

    db.add(models.Player(id=1, name="Bryan", room_id=foyer.id))
    db.add(models.Npc(name="Caretaker", description="A watchful presence.",
                      npc_type="caretaker", room_id=foyer.id,
                      is_friendly=False, combat_enabled=True))
    db.add(models.Npc(name="Innkeeper", description="Polite, not a fighter.",
                      npc_type="innkeeper", room_id=foyer.id,
                      combat_enabled=False))
    db.commit()


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


@pytest.fixture
def client(db_session):
    """TestClient with app lifespan (startup loads the world from the seeded DB).

    Resets the in-memory singletons so state doesn't leak between tests.
    """
    import main
    import websocket_manager
    import chat_system

    websocket_manager.manager.active_connections.clear()
    websocket_manager.manager.room_subscriptions.clear()
    chat_system.chat_manager.global_messages.clear()
    chat_system.chat_manager.room_messages.clear()
    chat_system.chat_manager.private_messages.clear()

    with TestClient(main.app) as c:
        yield c


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
