#!/usr/bin/env python3
"""
Canonical movement directions and their reverses.

Used to validate exit directions and to auto-create the paired return exit
when a two-way connection is built.
"""

# direction -> its opposite
REVERSE = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "northeast": "southwest",
    "southwest": "northeast",
    "northwest": "southeast",
    "southeast": "northwest",
    "up": "down",
    "down": "up",
    "in": "out",
    "out": "in",
}

# Common shorthands accepted from clients
ALIASES = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "u": "up", "d": "down",
}

DIRECTIONS = set(REVERSE)


def normalize(direction: str) -> str:
    """Lower-case and expand shorthands (e.g. 'N' -> 'north'). Returns the
    input lower-cased if it's not a known alias (callers validate with is_valid)."""
    if direction is None:
        return ""
    d = direction.strip().lower()
    return ALIASES.get(d, d)


def is_valid(direction: str) -> bool:
    return normalize(direction) in DIRECTIONS


def reverse(direction: str) -> str:
    """Opposite of a (already-normalized) direction, or '' if unknown."""
    return REVERSE.get(normalize(direction), "")
