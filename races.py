#!/usr/bin/env python3
"""
Character races (data-driven, authored — like classes.py / spells.py / skills.py).

A race is identity plus a small ability nudge applied *on top of* the class's
starting scores at creation (so an Elf Mage is a bit nimbler than a Human Mage).
Add a race here to extend the roster — character creation reads this table.
"""
from typing import Dict, List

# race id -> {name, abilities: {score: delta}}. Deltas are added to the class-
# stamped ability scores at creation (clamped to MIN/MAX elsewhere if needed).
RACES: Dict[str, dict] = {
    "human":    {"name": "Human",    "abilities": {"str": 1, "dex": 1, "con": 1}},
    "elf":      {"name": "Elf",      "abilities": {"dex": 2, "intel": 1}},
    "dwarf":    {"name": "Dwarf",    "abilities": {"con": 2, "str": 1}},
    "halfling": {"name": "Halfling", "abilities": {"dex": 2, "cha": 1}},
    "half-orc": {"name": "Half-Orc", "abilities": {"str": 2, "con": 1}},
    "gnome":    {"name": "Gnome",    "abilities": {"intel": 2, "wis": 1}},
}

SELECTABLE = list(RACES)
DEFAULT_RACE = "human"


def get_race(race_id: str) -> dict:
    return RACES.get(race_id, RACES[DEFAULT_RACE])


def is_valid(race_id: str) -> bool:
    return race_id in RACES
