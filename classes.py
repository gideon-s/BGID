#!/usr/bin/env python3
"""
Character classes (Phase 4 graphical overhaul) — a small, authored, data-driven
registry, in the same spirit as the hand-made world and the spell list
(``spells.py``). A class bundles: a display name + map glyph, starting ability
emphasis, a mana pool + per-regen-tick regen rate, and the spell ids it knows.

Add a class here (and reference real spell ids from ``spells.py``) to extend the
roster — no other code changes needed; character creation and the regen tick
read from this table.
"""
from typing import Dict, List

# class id -> definition. `abilities` overrides the default 10 for the listed
# scores at creation (others stay at DEFAULT_ABILITY_SCORE). `mana_regen` is mana
# restored per slow regen tick (game_loop.TICK_SECONDS). `spells` are spell ids.
CLASSES: Dict[str, dict] = {
    "warrior": {
        "name": "Warrior", "glyph": "🛡️", "max_mana": 10, "mana_regen": 1,
        "abilities": {"str": 15, "con": 14, "dex": 11},
        "spells": ["power_strike"],
        "starting_gear": [
            {"name": "Soldier's Sword", "glyph": "⚔️", "item_type": "weapon",
             "equip_slot": "weapon", "attack_bonus": 1, "damage_bonus": 2,
             "description": "A reliable arming sword."},
            {"name": "Studded Jerkin", "glyph": "🛡️", "item_type": "armor",
             "equip_slot": "torso", "defense_bonus": 2,
             "description": "Boiled leather sewn with iron studs."},
            {"name": "Iron Helm", "glyph": "⛑️", "item_type": "armor",
             "equip_slot": "head", "defense_bonus": 1, "description": "A dented but honest pot helm."},
        ],
    },
    "mage": {
        "name": "Mage", "glyph": "🧙", "max_mana": 30, "mana_regen": 3,
        "abilities": {"intel": 15, "dex": 12, "con": 10},
        "spells": ["firebolt", "frost_blast", "fireball", "slow", "venom_bolt"],
        "starting_gear": [
            {"name": "Apprentice Staff", "glyph": "🪄", "item_type": "weapon",
             "equip_slot": "weapon", "attack_bonus": 0, "damage_bonus": 1,
             "description": "A worn oak staff, faintly humming."},
            {"name": "Cloth Robe", "glyph": "🧥", "item_type": "armor",
             "equip_slot": "torso", "defense_bonus": 1, "description": "Plain spun robes."},
            {"name": "Ring of Focus", "glyph": "💍", "item_type": "ring",
             "equip_slot": "ring", "defense_bonus": 1, "description": "Steadies a casting hand."},
        ],
    },
    "cleric": {
        "name": "Cleric", "glyph": "⛪", "max_mana": 24, "mana_regen": 2,
        "abilities": {"wis": 15, "con": 12, "str": 11},
        "spells": ["heal", "smite", "bless"],
        "starting_gear": [
            {"name": "Oak Mace", "glyph": "🔨", "item_type": "weapon",
             "equip_slot": "weapon", "attack_bonus": 1, "damage_bonus": 1,
             "description": "A blunt, faithful cudgel."},
            {"name": "Chain Shirt", "glyph": "🛡️", "item_type": "armor",
             "equip_slot": "torso", "defense_bonus": 2, "description": "Riveted links over a gambeson."},
            {"name": "Holy Symbol", "glyph": "📿", "item_type": "amulet",
             "equip_slot": "amulet", "defense_bonus": 1, "description": "A worn prayer-bead amulet."},
        ],
    },
    "rogue": {
        "name": "Rogue", "glyph": "🗡️", "max_mana": 16, "mana_regen": 2,
        "abilities": {"dex": 15, "str": 12, "con": 11},
        "spells": ["backstab", "throw_dagger"],
        "starting_gear": [
            {"name": "Fine Dagger", "glyph": "🗡️", "item_type": "weapon",
             "equip_slot": "weapon", "attack_bonus": 1, "damage_bonus": 1,
             "description": "A slim, wickedly sharp blade."},
            {"name": "Leather Vest", "glyph": "🦺", "item_type": "armor",
             "equip_slot": "torso", "defense_bonus": 1, "description": "Supple, quiet, dark."},
            {"name": "Ring of Vigor", "glyph": "💍", "item_type": "ring",
             "equip_slot": "ring", "attack_bonus": 1, "description": "A warm band that steadies the hand."},
        ],
    },
    # The ability-neutral fallback stamped onto pre-Phase-4 characters by the
    # migration: melee only, no mana, no spells. Not offered at the gate.
    "wanderer": {
        "name": "Wanderer", "glyph": "🧝", "max_mana": 0, "mana_regen": 0,
        "abilities": {}, "spells": [],
        "starting_gear": [
            {"name": "Worn Knife", "glyph": "🔪", "item_type": "weapon",
             "equip_slot": "weapon", "damage_bonus": 1, "description": "It has seen better days."},
            {"name": "Tattered Cloak", "glyph": "🧥", "item_type": "armor",
             "equip_slot": "torso", "defense_bonus": 1, "description": "Frayed, but it keeps the wind off."},
        ],
    },
}

# Classes a new character may pick (everything but the migration fallback).
SELECTABLE = [cid for cid in CLASSES if cid != "wanderer"]
DEFAULT_CLASS = "wanderer"


def get_class(class_id: str) -> dict:
    """The class def for an id, or the wanderer fallback for an unknown id."""
    return CLASSES.get(class_id, CLASSES[DEFAULT_CLASS])


def is_valid(class_id: str) -> bool:
    return class_id in CLASSES


def spell_ids_for(class_id: str) -> List[str]:
    return list(get_class(class_id).get("spells", []))


def starting_gear(class_id: str) -> List[dict]:
    """The class's starting equipment templates (granted once by the chest)."""
    return [dict(g) for g in get_class(class_id).get("starting_gear", [])]
