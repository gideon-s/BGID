#!/usr/bin/env python3
"""
Vendor stock — what an NPC sells, and the buy/sell rules.

Keyed by `npc_type`: an NPC of a listed type is a vendor. Each good is a template
(like classes.starting_gear) with a `price` in COPPER (see currency.py). Stock is
effectively infinite. Players SELL gems / valued carried items back for their
`value`. No haggling — fixed prices.
"""
from typing import Dict, List, Optional

# npc_type -> goods. Each: sku, name, glyph, item_type, price(copper), and optional
# equip_slot + *_bonus for equippable wares.
STOCK: Dict[str, List[dict]] = {
    "innkeeper": [
        {"sku": "ration", "name": "Trail Ration", "glyph": "🍖", "item_type": "food", "price": 3},
        {"sku": "torch", "name": "Torch", "glyph": "🔦", "item_type": "tool", "price": 5},
        {"sku": "potion", "name": "Healing Draught", "glyph": "🧪", "item_type": "potion", "price": 40},
        {"sku": "greaterheal", "name": "Greater Healing", "glyph": "🧪", "item_type": "potion", "price": 110},
        {"sku": "manapot", "name": "Mana Potion", "glyph": "🔵", "item_type": "potion", "price": 45},
        {"sku": "strtonic", "name": "Strength Tonic", "glyph": "💪", "item_type": "potion", "price": 70},
        {"sku": "stoneskin", "name": "Stoneskin Brew", "glyph": "🪨", "item_type": "potion", "price": 70},
        {"sku": "haste", "name": "Draught of Haste", "glyph": "⚡", "item_type": "potion", "price": 85},
        {"sku": "dagger", "name": "Iron Dagger", "glyph": "🗡️", "item_type": "weapon",
         "equip_slot": "weapon", "attack_bonus": 1, "damage_bonus": 1, "price": 60},
        {"sku": "buckler", "name": "Buckler", "glyph": "🛡️", "item_type": "armor",
         "equip_slot": "left_hand", "defense_bonus": 1, "price": 45},
        {"sku": "cloak", "name": "Wool Cloak", "glyph": "🧥", "item_type": "armor",
         "equip_slot": "torso", "defense_bonus": 1, "price": 30},
    ],
}


def is_vendor(npc_type: str) -> bool:
    return npc_type in STOCK


def stock_for(npc_type: str) -> List[dict]:
    return STOCK.get(npc_type, [])


def good(npc_type: str, sku: str) -> Optional[dict]:
    return next((g for g in stock_for(npc_type) if g["sku"] == sku), None)
