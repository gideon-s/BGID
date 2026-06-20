#!/usr/bin/env python3
"""
Effect-granting equipment (handoff-08 §3).

Worn gear can grant a **non-expiring** status effect (see ``effects.py``,
``gear=True``) while equipped. A registry maps an item NAME to effect params;
``sync`` rebuilds a player's gear effects from their currently-worn set, so
equip / unequip / connect all funnel through one idempotent call. The effect's
name is the item name, so unequipping removes exactly the right effect.
"""
from typing import Dict, List, Optional

import effects
import models
from database import SessionLocal

# item name -> effect params (atk/dmg/defn/haste); `glyph` shows in the UI chip.
GEAR_EFFECTS: Dict[str, dict] = {
    "Ring of Haste": {"glyph": "⚡", "haste": 0.5},
    "Band of Might": {"glyph": "💪", "atk": 1, "dmg": 1},
}


def for_item(name: str) -> Optional[dict]:
    return GEAR_EFFECTS.get(name)


def sync(player_id: int) -> List[dict]:
    """Rebuild a player's gear effects from their worn equipment (idempotent):
    drop the current gear effects, then apply one per worn effect-granting item.
    Returns the post-sync snapshot of ALL the player's effects."""
    key = effects.eid("player", player_id)
    for e in list(effects.active(key)):
        if e.get("gear"):
            effects.remove(key, e["name"])
    db = SessionLocal()
    try:
        worn = (db.query(models.Item)
                .filter_by(player_id=player_id, equipped=True).all())
        names = [it.name for it in worn]
    finally:
        db.close()
    for name in names:
        spec = GEAR_EFFECTS.get(name)
        if spec is None:
            continue
        effects.apply_effect(
            key, name, spec.get("glyph", "◆"), duration=0.0, gear=True,
            atk=spec.get("atk", 0), dmg=spec.get("dmg", 0),
            defn=spec.get("defn", 0), haste=spec.get("haste", 1.0),
            source_type="gear")
    return effects.snapshot(key)


# ---------- config layer (handoff-10 §1) ----------
import content as _content

def _apply_gear(merged):
    global GEAR_EFFECTS
    GEAR_EFFECTS = merged

_content.register("gear", dict(GEAR_EFFECTS), _apply_gear)
