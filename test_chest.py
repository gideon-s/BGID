"""Class-gear chest — grants a character its class's starting kit, once each.

Test world (conftest): an 'Old Chest' (immovable) sits in the Great Hall (room 2)
at tile (3,1). Bryan is player 1 (defaults to the 'wanderer' class).
"""
import database
import models
import services
import classes
from world import world


def _chest(db):
    return db.query(models.Item).filter_by(item_type="chest").first()


def _as_class(db, class_id, player_id=1):
    p = db.query(models.Player).filter_by(id=player_id).first()
    p.char_class = class_id
    p.opened_chests = "[]"
    db.commit()
    return p


def test_gear_differs_by_class():
    warrior = {g["name"] for g in classes.starting_gear("warrior")}
    rogue = {g["name"] for g in classes.starting_gear("rogue")}
    assert warrior and rogue and warrior != rogue


def test_open_chest_grants_and_equips_class_gear(db_session):
    p = _as_class(db_session, "warrior")
    granted, already = services.ItemService.open_chest(db_session, p, _chest(db_session))
    assert not already
    assert {g.name for g in granted} == {g["name"] for g in classes.starting_gear("warrior")}
    inv = services.ItemService.inventory_of(db_session, 1)
    assert len(inv) == len(classes.starting_gear("warrior"))
    # every equippable piece was auto-worn
    assert all(it.equipped for it in inv if it.equip_slot)


def test_open_chest_only_once_per_character(db_session):
    p = _as_class(db_session, "mage")
    services.ItemService.open_chest(db_session, p, _chest(db_session))
    granted2, already = services.ItemService.open_chest(db_session, p, _chest(db_session))
    assert already is True and granted2 == []
    # inventory not doubled
    assert len(services.ItemService.inventory_of(db_session, 1)) == len(classes.starting_gear("mage"))


def test_open_chest_grants_the_openers_class(db_session):
    # A rogue and (after reset) a cleric opening the same chest get their own kits.
    p = _as_class(db_session, "rogue")
    granted, _ = services.ItemService.open_chest(db_session, p, _chest(db_session))
    assert {g.name for g in granted} == {g["name"] for g in classes.starting_gear("rogue")}


def test_chest_near_detects_on_and_adjacent(db_session):
    world.load()
    cid = _chest(database.SessionLocal()).id
    assert world.chest_near(2, 3, 1) == cid     # standing on it
    assert world.chest_near(2, 2, 1) == cid     # adjacent (diagonal counts)
    assert world.chest_near(2, 5, 3) is None    # out of reach


def test_grabbable_skips_the_immovable_chest(db_session):
    # An item resting on the chest's tile must still be retrievable (the bug:
    # the immovable chest shadowed it, so pickup-by-tile grabbed the chest).
    world.load()
    world.add_ground_item(2, 999, 3, 1, "Lost Coin", "🪙")   # onto the chest tile (3,1)
    assert world.grabbable_at(2, 3, 1) == 999                # the coin, not the chest
    world.remove_ground_item(999)
    assert world.grabbable_at(2, 3, 1) is None               # the chest alone isn't grabbable


def test_chest_migration_idempotent(db_session):
    import migrate_chest
    migrate_chest.migrate()
    migrate_chest.migrate()
    from sqlalchemy import text
    with database.engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(players)"))}
    assert "opened_chests" in cols
