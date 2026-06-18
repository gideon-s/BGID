#!/usr/bin/env python3
"""
Consumable potions.

A potion is an `item_type == "potion"` item; drinking it (the `use` command)
applies an instant effect and consumes the item. Effects are authored here,
keyed by item name (shop/loot potions have stable names). Kinds:

    heal       -> restore `amount` HP (clamped to max)
    mana       -> restore `amount` mana (clamped to max)
    restore    -> heal HP *and* mana to full

`flavor` is shown to the drinker. Unknown potions do nothing (a dud).
"""
from typing import Dict, Optional

POTIONS: Dict[str, dict] = {
    "Healing Draught": {"kind": "heal", "amount": 12,
                        "flavor": "Warmth floods your limbs."},
    "Greater Healing": {"kind": "heal", "amount": 30,
                        "flavor": "Your wounds knit shut in moments."},
    "Mana Potion": {"kind": "mana", "amount": 20,
                    "flavor": "A cold clarity sharpens your mind."},
    "Elixir of Vigor": {"kind": "restore", "amount": 0,
                        "flavor": "You feel utterly renewed."},
}


def effect_for(name: str) -> Optional[dict]:
    return POTIONS.get(name)


def apply(player, effect: dict) -> dict:
    """Apply a potion effect to a (session-attached) player. Returns
    {hp_restored, mana_restored} (the actual amounts after clamping)."""
    kind = effect.get("kind")
    hp = mana = 0
    if kind == "heal":
        hp = player.heal(effect.get("amount", 0))
    elif kind == "mana":
        mana = player.restore_mana(effect.get("amount", 0))
    elif kind == "restore":
        hp = player.heal(player.max_health)
        mana = player.restore_mana(player.max_mana)
    return {"hp_restored": hp, "mana_restored": mana}
