"""Experience, the XP curve, and level-ups (HP/mana growth, heal-to-full)."""
import asyncio

import combat
import database
import leveling
import models
import services
from world import world


# ---------- curve ----------
def test_xp_curve_is_rising_triangular():
    assert leveling.xp_to_reach(1) == 0
    assert leveling.xp_to_reach(2) == 100
    assert leveling.xp_to_reach(3) == 300
    assert leveling.xp_to_reach(5) == 1000
    assert leveling.level_for_xp(0) == 1
    assert leveling.level_for_xp(99) == 1
    assert leveling.level_for_xp(100) == 2
    assert leveling.level_for_xp(1000) == 5
    assert leveling.progress(150) == (2, 50, 200)   # 50 into L2, needs 200 for L3


# ---------- award + level-up ----------
def test_award_xp_no_level(db_session):
    res = services.PlayerService.award_xp(db_session, 1, 30)
    assert res["leveled"] is False and res["level"] == 1 and res["experience"] == 30


def test_award_xp_levels_up_and_grows(db_session):
    p = db_session.query(models.Player).filter_by(id=1).first()
    p.con = 14          # +2 CON modifier; HP grows by 4 + 2 = 6 per level
    p.health = 1; db_session.commit()
    hp0 = p.max_health
    res = services.PlayerService.award_xp(db_session, 1, 100)   # → level 2
    assert res["leveled"] and res["level"] == 2
    assert res["max_health"] == hp0 + 6
    assert res["hp"] == res["max_health"]                      # healed to full on level-up


def test_award_xp_multi_level(db_session):
    res = services.PlayerService.award_xp(db_session, 1, 300)   # 0 → level 3 in one go
    assert res["level"] == 3 and res["old_level"] == 1


def test_kill_xp_scales_with_toughness():
    assert leveling.xp_for_kill(8) == 16 and leveling.xp_for_kill(20) == 40


# ---------- combat awards XP to the killer ----------
def test_slaying_a_mob_awards_xp(db_session, monkeypatch):
    world.load()
    caretaker = db_session.query(models.Npc).filter_by(name="Caretaker").first()
    monkeypatch.setattr(combat, "_attack_roll", lambda a, d, **k: {"hit": True, "damage": 99})
    # place the player adjacent to the mob (conftest: player spawn (2,2), Caretaker (3,2))
    world.enter_world(1); world.place_player(1, 1)
    asyncio.run(combat.resolve_player_attack(1, 1, caretaker.id))
    db = database.SessionLocal()
    try:
        p = db.query(models.Player).filter_by(id=1).first()
        assert p.experience == leveling.xp_for_kill(caretaker.max_health)
    finally:
        db.close()
