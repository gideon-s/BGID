#!/usr/bin/env python3
"""
Debuffs — harmful status effects (handoff-08 §2).

A debuff is just an ``effects.py`` effect with negative combat deltas and/or a
``dot`` (damage-over-time), flagged ``harm=True`` so the client tints it red.
Authored here as a small registry; spells (``spells.py``) and venomous mobs
(``VENOM_BY_TYPE`` below, applied in ``combat.resolve_mob_attack``) reference
these templates by name.
"""
from typing import Dict, Optional

# name -> effect params. `harm=True` is implied for everything here.
DEBUFFS: Dict[str, dict] = {
    "Weaken": {"glyph": "🥀", "duration": 30, "atk": -2, "dmg": -2},
    "Poison": {"glyph": "🤢", "duration": 18, "dot": 2, "dot_interval": 3.0},
    "Slow":   {"glyph": "🐌", "duration": 15, "haste": 2.0},   # haste>1 = slower
}

# npc_type -> the debuff a mob of that type inflicts on a player it hits.
VENOM_BY_TYPE: Dict[str, str] = {
    "spider": "Poison",
}


def get(name: str) -> Optional[dict]:
    return DEBUFFS.get(name)


def venom_for(npc_type: str) -> Optional[str]:
    """The debuff name a mob of this type applies on a landing hit, or None."""
    return VENOM_BY_TYPE.get(npc_type)


def apply_to(key: str, name: str, source_name: str = None,
             source_id: int = None, source_type: str = None) -> bool:
    """Apply a named debuff (from ``DEBUFFS``) to an entity key, attributing it to
    the source so a DoT kill awards loot/XP correctly. Returns False if unknown."""
    import effects
    spec = DEBUFFS.get(name)
    if spec is None:
        return False
    effects.apply_effect(
        key, name, spec.get("glyph", "❓"), spec.get("duration", 15),
        atk=spec.get("atk", 0), dmg=spec.get("dmg", 0), defn=spec.get("defn", 0),
        haste=spec.get("haste", 1.0), dot=spec.get("dot", 0),
        dot_interval=spec.get("dot_interval", 3.0), harm=True,
        source_name=source_name, source_id=source_id, source_type=source_type)
    return True


# ---------- config layer (handoff-10 §1) ----------
import content as _content

def _apply_debuffs(merged):
    global DEBUFFS
    DEBUFFS = merged

_content.register("debuffs", dict(DEBUFFS), _apply_debuffs)
