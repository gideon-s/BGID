"""Game-loop tick tests (step 4)."""
import asyncio
import models


def test_npc_regen_tick(db_session):
    import game_loop
    from world import world
    world.load()
    npc = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    npc.health, npc.max_health = 2, 8
    db_session.commit()

    asyncio.run(game_loop._tick_once())

    db_session.expire_all()
    npc = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    assert npc.health == 3


def test_regen_caps_at_max(db_session):
    import game_loop
    from world import world
    world.load()
    npc = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    npc.health, npc.max_health = 8, 8
    db_session.commit()

    asyncio.run(game_loop._tick_once())

    db_session.expire_all()
    npc = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    assert npc.health == 8


def test_defeated_npc_not_regenerated(db_session):
    """An NPC at 0 hp removed from its room is not healed by the tick."""
    import game_loop
    from world import world
    world.load()
    npc = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    npc.health, npc.max_health = 0, 8
    db_session.commit()
    world.rooms[1].npc_ids.discard(npc.id)  # simulate defeat removal

    asyncio.run(game_loop._tick_once())

    db_session.expire_all()
    npc = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    assert npc.health == 0
