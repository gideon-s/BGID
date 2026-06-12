"""WorldState unit tests (step 1)."""
import models


def test_load_populates_rooms_npcs_items(db_session):
    from world import world
    world.load()
    assert set(world.rooms) == {1, 2}
    foyer = world.rooms[1]
    # Caretaker + Innkeeper resident in the Foyer; Rusty Key on the ground
    assert len(foyer.npc_ids) == 2
    assert len(foyer.item_ids) == 1
    assert world.rooms[2].npc_ids == set()


def test_snapshot_shape(db_session):
    from world import world
    world.load()
    snap = world.room_snapshot(1)
    assert snap["room"]["name"] == "Foyer"
    assert {n["name"] for n in snap["npcs"]} == {"Caretaker", "Innkeeper"}
    assert {i["name"] for i in snap["items"]} == {"Rusty Key"}
    assert snap["players"] == []


def test_enter_and_presence(db_session):
    from world import world
    world.load()
    room_id = world.enter_world(1)
    assert room_id == 1
    assert world.occupants(1) == [1]
    assert [p["name"] for p in world.room_snapshot(1)["players"]] == ["Bryan"]


def test_move_writes_through_to_db(db_session):
    from world import world
    world.load()
    world.enter_world(1)
    assert world.move_player(1, 2) is True
    assert world.room_of(1) == 2
    assert world.occupants(1) == []           # left room 1
    assert world.occupants(2) == [1]          # now in room 2
    db_session.expire_all()
    player = db_session.query(models.Player).get(1)
    assert player.room_id == 2                 # persisted


def test_move_to_missing_room_rejected(db_session):
    from world import world
    world.load()
    world.enter_world(1)
    assert world.move_player(1, 999) is False
    assert world.room_of(1) == 1


def test_leave_world(db_session):
    from world import world
    world.load()
    world.enter_world(1)
    assert world.leave_world(1) == 1
    assert world.online_players() == []
