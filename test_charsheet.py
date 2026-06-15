"""Character sheet — gender, skills, body-part equipment slots, and the
`sheet` WS command."""
import json

import models
import skills as skillbook
import services
from world import world


def _ws(client, token, pid):
    return client.websocket_connect(f"/ws/{pid}?token={token}")


def _drain_until(ws, pred, tries=12):
    for _ in range(tries):
        m = ws.receive_json()
        if pred(m):
            return m
    return None


# ---------- creation stamps gender + skills ----------
def test_create_stamps_gender_and_skills(db_session):
    import auth_service
    intruder = db_session.query(models.User).filter_by(username="intruder").first()
    p = auth_service.CharacterService.create(db_session, intruder, "Vex", "rogue", "female")
    assert p.gender == "female"
    sk = json.loads(p.skills)
    assert set(sk) == set(skillbook.SKILLS)
    assert sk["Stealth"] == 3 and sk["Melee"] == 1     # rogue signature ranks


def test_gender_defaults_to_none_and_keeps_custom():
    import auth_schemas
    assert auth_schemas.CharacterCreate(name="Nyx", char_class="mage").gender == "none"
    c = auth_schemas.CharacterCreate(name="Nyx", char_class="mage", gender="  Enby ")
    assert c.gender == "Enby"             # custom value preserved (trimmed)


# ---------- body slots ----------
def test_body_slots_in_limits():
    for slot in ["head", "torso", "upper_arms", "lower_arms", "hands",
                 "pelvis", "upper_legs", "lower_legs", "feet"]:
        assert services.SLOT_LIMITS[slot] == 1


def test_equip_body_slot(db_session):
    cap = models.Item(name="Cap", item_type="armor", player_id=1,
                      is_equippable=True, equip_slot="head", defense_bonus=1)
    db_session.add(cap); db_session.commit()
    services.ItemService.equip(db_session, 1, cap.id)
    db_session.refresh(cap)
    assert cap.equipped is True
    assert services.ItemService.equipment_bonuses(db_session, 1)["defense"] == 1


# ---------- the sheet command ----------
def test_sheet_command_shape(client, token, db_session):
    # Give Bryan a class + an equipped helm so the sheet is populated.
    p = db_session.query(models.Player).get(1)
    p.char_class = "warrior"; p.gender = "male"
    p.skills = json.dumps(skillbook.starting_skills("warrior"))
    db_session.commit()
    helm = models.Item(name="Steel Helm", glyph="⛑️", item_type="armor", player_id=1,
                       is_equippable=True, equip_slot="head", equipped=True, defense_bonus=2)
    db_session.add(helm); db_session.commit()
    with _ws(client, token, 1) as ws:
        ws.receive_json()                          # zone_state
        ws.send_json({"cmd": "sheet"})
        sh = _drain_until(ws, lambda m: m["event"] == "character_sheet")
        assert sh is not None
        assert sh["gender"] == "male" and sh["char_class"] == "warrior"
        assert set(sh["abilities"]) == {"str", "dex", "con", "intel", "wis", "cha"}
        assert sh["skills"]["Melee"] == 3          # warrior signature
        assert "head" in sh["equipment"] and sh["equipment"]["head"][0]["name"] == "Steel Helm"
        assert "feet" in sh["slots"]               # body-slot list for the paperdoll
