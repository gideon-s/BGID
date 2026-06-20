"""Content config layer (handoff-10 §1): editable code registries with overlay,
hot-reload, validation, and revert-to-default."""
import content
import spells
import potions


# ---------- registry mechanics (unit) ----------
def test_overlay_hot_reload_unit(db_session):
    # Override an existing spell's cost; the live registry reflects it immediately.
    content.upsert("spells", "firebolt", {**spells.get_spell("firebolt"), "cost": 99})
    assert spells.get_spell("firebolt")["cost"] == 99
    # Revert → back to the code default.
    content.delete("spells", "firebolt")
    assert spells.get_spell("firebolt")["cost"] == 3


def test_add_new_entry(db_session):
    content.upsert("spells", "zap", {"name": "Zap", "cost": 1, "shape": "bolt",
                                     "glyph": "⚡", "cooldown": 1.0, "range": 4,
                                     "effect": {"kind": "damage", "dice": [1, 4], "mod": "intel"}})
    assert spells.get_spell("zap")["name"] == "Zap"
    assert not content.is_default("spells", "zap")     # an addition, not a default


def test_validation_rejects_bad_doc(db_session):
    import pytest
    with pytest.raises(ValueError):
        content.upsert("spells", "broken", {"name": "x"})          # missing fields
    with pytest.raises(ValueError):
        content.upsert("potions", "bad", {"kind": "explode"})      # bad potion kind
    # the live registry is unchanged (nothing leaked in)
    assert spells.get_spell("broken") is None


def test_reset_isolation(db_session):
    content.upsert("potions", "Healing Draught", {"kind": "heal", "amount": 999})
    assert potions.effect_for("Healing Draught")["amount"] == 999
    content.reset()                                    # what conftest does between tests
    assert potions.effect_for("Healing Draught")["amount"] == 12


# ---------- endpoints + live effect over the wire ----------
def test_content_endpoints_and_casting(client, admin_headers):
    # list kinds
    kinds = client.get("/admin/content", headers=admin_headers).json()["kinds"]
    assert {"spells", "potions", "debuffs", "gear"} <= set(kinds)
    # get a registry (merged + which keys are defaults)
    body = client.get("/admin/content/spells", headers=admin_headers).json()
    assert "firebolt" in body["entries"] and "firebolt" in body["defaults"]
    # edit a spell's cost via the API → casting sees it live
    edited = {**spells.get_spell("firebolt"), "cost": 1}
    r = client.put("/admin/content/spells/firebolt", json={"data": edited}, headers=admin_headers)
    assert r.status_code == 200
    assert spells.get_spell("firebolt")["cost"] == 1
    # delete the override → reverts
    client.delete("/admin/content/spells/firebolt", headers=admin_headers)
    assert spells.get_spell("firebolt")["cost"] == 3


def test_content_validation_400(client, admin_headers):
    r = client.put("/admin/content/spells/oops", json={"data": {"name": "x"}}, headers=admin_headers)
    assert r.status_code == 400


def test_content_unknown_kind_404(client, admin_headers):
    assert client.get("/admin/content/nope", headers=admin_headers).status_code == 404


def test_content_admin_only(client, user_headers):
    assert client.get("/admin/content", headers=user_headers).status_code == 403
    assert client.put("/admin/content/spells/firebolt", json={"data": {}},
                      headers=user_headers).status_code == 403


# ---------- classes & races on the config layer (handoff-10 §6) ----------
import classes
import races


def test_class_overlay_recomputes_selectable(db_session):
    # Add a brand-new class → live + offered at character creation (SELECTABLE).
    content.upsert("classes", "ranger", {"name": "Ranger", "glyph": "🏹",
                   "max_mana": 12, "mana_regen": 1, "abilities": {"dex": 15},
                   "spells": ["throw_dagger"], "starting_gear": []})
    assert classes.get_class("ranger")["name"] == "Ranger"
    assert "ranger" in classes.SELECTABLE                 # validator will accept it
    assert "wanderer" not in classes.SELECTABLE           # fallback stays hidden
    # Edit an existing class's spell list live.
    content.upsert("classes", "mage", {**classes.get_class("mage"), "spells": ["firebolt"]})
    assert classes.spell_ids_for("mage") == ["firebolt"]
    content.delete("classes", "mage")
    assert "frost_blast" in classes.spell_ids_for("mage")  # reverted to default


def test_race_overlay(db_session):
    content.upsert("races", "tiefling", {"name": "Tiefling", "abilities": {"cha": 2, "intel": 1}})
    assert races.get_race("tiefling")["name"] == "Tiefling"
    assert "tiefling" in races.SELECTABLE
    content.reset()
    assert races.is_valid("tiefling") is False


def test_class_validation_requires_name(db_session):
    import pytest
    with pytest.raises(ValueError):
        content.upsert("classes", "bad", {"glyph": "x"})           # no name
    with pytest.raises(ValueError):
        content.upsert("classes", "bad2", {"name": "X", "spells": "nope"})  # spells not a list


def test_new_class_is_selectable_at_creation(client, admin_headers):
    """A class added via the content API is accepted by the character-creation
    validator (which reads classes.SELECTABLE)."""
    r = client.put("/admin/content/classes/ranger",
                   json={"data": {"name": "Ranger", "glyph": "🏹", "max_mana": 12,
                                  "mana_regen": 1, "abilities": {"dex": 15}, "spells": []}},
                   headers=admin_headers)
    assert r.status_code == 200
    import auth_schemas
    cc = auth_schemas.CharacterCreate(name="Robin", char_class="ranger", race="elf")
    assert cc.char_class == "ranger"


def test_classes_races_gate_endpoints(client, admin_headers):
    base = {c["id"] for c in client.get("/classes").json()["classes"]}
    assert {"warrior", "mage", "cleric", "rogue"} <= base and "wanderer" not in base
    client.put("/admin/content/classes/ranger",
               json={"data": {"name": "Ranger", "glyph": "🏹", "spells": []}},
               headers=admin_headers)
    assert "ranger" in {c["id"] for c in client.get("/classes").json()["classes"]}
    assert {"human", "elf"} <= {r["id"] for r in client.get("/races").json()["races"]}
