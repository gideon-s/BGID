#!/usr/bin/env python3
"""
Character skills (data-driven, authored — like classes.py / spells.py).

A small fixed set of proficiencies shown on the character sheet. Each class
starts with ranks in its signature skills; everything else starts at 0. Ranks
are stored per-character as a JSON dict on ``Player.skills`` so they can grow
later (skill use / leveling is out of scope for now — this phase displays them).
"""
from typing import Dict, List

# The canonical skill list (display order).
SKILLS: List[str] = ["Melee", "Ranged", "Arcana", "Stealth", "Persuasion", "Survival"]

# Starting ranks by class. Unlisted skills start at 0.
CLASS_SKILLS: Dict[str, Dict[str, int]] = {
    "warrior": {"Melee": 3, "Survival": 2, "Persuasion": 1},
    "mage":    {"Arcana": 3, "Ranged": 1, "Persuasion": 1},
    "cleric":  {"Persuasion": 3, "Arcana": 2, "Survival": 1},
    "rogue":   {"Stealth": 3, "Ranged": 2, "Melee": 1},
    "wanderer": {"Survival": 1},
}


def starting_skills(class_id: str) -> Dict[str, int]:
    """A full skill dict (every skill present) seeded from the class."""
    base = CLASS_SKILLS.get(class_id, {})
    return {skill: base.get(skill, 0) for skill in SKILLS}


def normalize(skills: Dict[str, int] | None) -> Dict[str, int]:
    """Coerce a (possibly partial/None) stored skill dict to the full list."""
    skills = skills or {}
    return {skill: int(skills.get(skill, 0)) for skill in SKILLS}
