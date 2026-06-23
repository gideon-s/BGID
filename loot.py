#!/usr/bin/env python3
"""
Loot tables — what a slain mob drops on its tile.

Keyed by `npc_type`. A drop becomes a ground item (coins collect into the wallet
on pickup; gems are valued carried items). Values are in COPPER (see currency.py).
Deliberately modest — this is a trickle, not a jackpot.
"""
import random
from typing import Dict, List

# npc_type -> {coins: (min,max) copper, gem_chance: 0..1, gems: [(name, glyph, value)]}
_GEMS = [("Garnet", "🔴", 50), ("Amethyst", "🟣", 90), ("Sapphire", "🔷", 250)]
LOOT: Dict[str, dict] = {
    "combat_mob": {"coins": (1, 12), "gem_chance": 0.12, "gems": _GEMS},
    # Bestiary (classic fantasy mobs — see add_labyrinth/populate). Coins +
    # gem-chance scale roughly with the monster's danger.
    "giant_rat": {"coins": (1, 5),  "gem_chance": 0.03, "gems": _GEMS},
    "kobold":    {"coins": (1, 6),  "gem_chance": 0.05, "gems": _GEMS},
    "goblin":    {"coins": (2, 10), "gem_chance": 0.08, "gems": _GEMS},
    "slime":     {"coins": (1, 8),  "gem_chance": 0.06, "gems": _GEMS},
    "spider":    {"coins": (2, 9),  "gem_chance": 0.08, "gems": _GEMS},
    "skeleton":  {"coins": (3, 12), "gem_chance": 0.10, "gems": _GEMS},
    "zombie":    {"coins": (3, 12), "gem_chance": 0.08, "gems": _GEMS},
    "gnoll":     {"coins": (4, 16), "gem_chance": 0.10, "gems": _GEMS},
    "orc":       {"coins": (6, 22), "gem_chance": 0.14, "gems": _GEMS},
    "ogre":      {"coins": (15, 40), "gem_chance": 0.30, "gems": _GEMS},
}

_DEFAULT = {"coins": (0, 4), "gem_chance": 0.0, "gems": []}


def roll(npc_type: str, rng: random.Random = random) -> List[dict]:
    """Roll a mob's drops → a list of {name, glyph, item_type, value} dicts.

    Coins are item_type 'coins' (collect into the wallet); gems are 'gem'.
    """
    table = LOOT.get(npc_type, _DEFAULT)
    drops: List[dict] = []
    lo, hi = table.get("coins", (0, 0))
    amount = rng.randint(lo, hi)
    if amount > 0:
        drops.append({"name": "Coins", "glyph": "🪙", "item_type": "coins", "value": amount})
    gems = table.get("gems") or []
    if gems and rng.random() < table.get("gem_chance", 0.0):
        name, glyph, value = rng.choice(gems)
        drops.append({"name": name, "glyph": glyph, "item_type": "gem", "value": value})
    return drops
