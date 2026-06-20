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
