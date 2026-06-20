#!/usr/bin/env python3
"""
Spells (Phase 4 graphical overhaul) — a data-driven registry plus a tiny effect
resolver. Authored and reviewable, like the world and the class table
(``classes.py``).

Each spell:
  name      display name
  glyph     emoji shown on the quickslot + as the cast VFX
  cost      mana spent on a successful cast
  cooldown  seconds before the same caster may recast it (per player+spell)
  range     max Chebyshev distance to the target tile (0 = self)
  shape     'self'  -> target is the caster's tile
            'bolt'  -> the single entity on the target tile (needs range + LOS)
            'blast' -> every entity within `radius` of the target tile (AoE)
  radius    blast radius in tiles (Chebyshev); ignored for self/bolt
  effect    {kind: 'damage'|'heal', dice: (n, d), mod: ability_name, bonus: int}

Spells **auto-hit** (range + line-of-sight is the counterplay) — there is no
melee-style to-hit roll here. `roll_effect` rolls `n`d`d` + the caster's class
ability modifier + a flat bonus.
"""
import random
from typing import Dict, Optional

SPELLS: Dict[str, dict] = {
    "firebolt": {
        "name": "Firebolt", "glyph": "🔥", "cost": 3, "cooldown": 1.0,
        "range": 6, "shape": "bolt",
        "effect": {"kind": "damage", "dice": (2, 6), "mod": "intel"},
    },
    "frost_blast": {
        "name": "Frost Blast", "glyph": "❄️", "cost": 7, "cooldown": 5.0,
        "range": 6, "radius": 1, "shape": "blast",
        "effect": {"kind": "damage", "dice": (2, 4), "mod": "intel"},
    },
    "fireball": {
        "name": "Fireball", "glyph": "🔥", "cost": 10, "cooldown": 6.0,
        "range": 7, "radius": 2, "shape": "blast",   # a wider, harder-hitting AoE
        "effect": {"kind": "damage", "dice": (3, 6), "mod": "intel"},
    },
    "heal": {
        "name": "Heal", "glyph": "✨", "cost": 5, "cooldown": 3.0,
        "range": 0, "shape": "self",
        "effect": {"kind": "heal", "dice": (2, 6), "mod": "wis"},
    },
    "smite": {
        "name": "Smite", "glyph": "⚡", "cost": 4, "cooldown": 1.5,
        "range": 5, "shape": "bolt",
        "effect": {"kind": "damage", "dice": (1, 8), "mod": "wis"},
    },
    "power_strike": {
        "name": "Power Strike", "glyph": "💥", "cost": 4, "cooldown": 2.0,
        "range": 1, "shape": "bolt",
        "effect": {"kind": "damage", "dice": (1, 6), "mod": "str", "bonus": 4},
    },
    # Rogue: a melee burst (range 1) + a cheap thrown ranged poke.
    "backstab": {
        "name": "Backstab", "glyph": "🗡️", "cost": 4, "cooldown": 2.0,
        "range": 1, "shape": "bolt",
        "effect": {"kind": "damage", "dice": (2, 6), "mod": "dex", "bonus": 2},
    },
    "throw_dagger": {
        "name": "Throw Dagger", "glyph": "🔪", "cost": 2, "cooldown": 1.0,
        "range": 5, "shape": "bolt",
        "effect": {"kind": "damage", "dice": (1, 6), "mod": "dex"},
    },
    # Buff/debuff spells (handoff-08 §5). `kind: buff` carries inline effect
    # params applied to the caster (self shape); `kind: debuff` (or any spell with
    # a `debuff` key) applies a named template from debuffs.py to each npc target;
    # Venom Bolt both damages AND poisons.
    "bless": {
        "name": "Bless", "glyph": "🙏", "cost": 4, "cooldown": 8.0,
        "range": 0, "shape": "self",
        "effect": {"kind": "buff", "name": "Bless", "glyph": "🙏",
                   "duration": 30, "atk": 2, "defn": 2},
    },
    "slow": {
        "name": "Slow", "glyph": "🐌", "cost": 4, "cooldown": 6.0,
        "range": 6, "shape": "bolt",
        "effect": {"kind": "debuff", "debuff": "Slow"},
    },
    "venom_bolt": {
        "name": "Venom Bolt", "glyph": "🟢", "cost": 5, "cooldown": 2.0,
        "range": 6, "shape": "bolt",
        "effect": {"kind": "damage", "dice": (1, 6), "mod": "intel", "debuff": "Poison"},
    },
}


def get_spell(spell_id: str) -> Optional[dict]:
    return SPELLS.get(spell_id)


def roll_effect(caster, spell: dict) -> int:
    """Roll a spell's magnitude: `n`d`d` + caster ability mod + flat bonus.
    Returns a non-negative integer (damage or healing amount)."""
    eff = spell["effect"]
    n, d = eff["dice"]
    total = sum(random.randint(1, d) for _ in range(n))
    mod_name = eff.get("mod")
    if mod_name:
        total += caster.ability_mod(mod_name)
    total += eff.get("bonus", 0)
    return max(1, total)


def spell_summary(spell_id: str) -> Optional[dict]:
    """Client-facing spell descriptor for the quickslot bar."""
    sp = SPELLS.get(spell_id)
    if sp is None:
        return None
    return {"id": spell_id, "name": sp["name"], "glyph": sp["glyph"],
            "cost": sp["cost"], "cooldown": sp["cooldown"], "range": sp["range"],
            "shape": sp["shape"], "radius": sp.get("radius", 0)}
