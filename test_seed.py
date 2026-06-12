"""Seed idempotency tests (#4)."""
import models


def test_seed_is_idempotent(db_session):
    """Running seed twice must not duplicate rooms (the old bug)."""
    import database
    # start from an empty DB (conftest seeds; clear it first)
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)

    import seed
    seed.seed()
    seed.seed()  # second run must be a no-op

    db = database.SessionLocal()
    try:
        assert db.query(models.Room).filter_by(name="Foyer").count() == 1
        assert db.query(models.Room).filter_by(name="Great Hall").count() == 1
        assert db.query(models.Player).filter_by(name="Bryan").count() == 1
        assert db.query(models.Npc).filter_by(name="Caretaker").count() == 1
    finally:
        db.close()
