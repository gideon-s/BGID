#!/usr/bin/env python3
"""
Tile registry (handoff-11 Slice A) — a tile is a *record*, not just a char.

Authoring stays a terse, reviewable glyph grid (`Room.tiles`), but each glyph
**resolves through this data-driven registry** into a full tile def, mirroring
`classes.py`/`spells.py`. Walkability / sight / zone-transition are read from here
(see `world.py`), so a new tile type is **data, not code** — add a glyph here and
the engine + client (via the `tiledefs` snapshot field) pick it up with no
predicate or render changes.

Each def: `name`, `walkable` (movement), `transparent` (line of sight), and
`transition` (None | "door" | "up" | "down" — drives `transition_for_tile`).
An **unknown** glyph resolves to `DEFAULT` (a solid, opaque wall) so a typo fails
safe rather than opening a hole in the map.
"""
from typing import Dict, Optional

TILES: Dict[str, dict] = {
    "#": {"name": "wall",        "walkable": False, "transparent": False, "transition": None},
    ".": {"name": "floor",       "walkable": True,  "transparent": True,  "transition": None},
    "+": {"name": "door",        "walkable": True,  "transparent": True,  "transition": "door"},
    "o": {"name": "pillar",      "walkable": False, "transparent": False, "transition": None},
    "~": {"name": "water",       "walkable": False, "transparent": True,  "transition": None},
    ":": {"name": "rubble",      "walkable": True,  "transparent": True,  "transition": None},
    ">": {"name": "stairs_down", "walkable": True,  "transparent": True,  "transition": "down"},
    "<": {"name": "stairs_up",   "walkable": True,  "transparent": True,  "transition": "up"},
    # Headroom — new tile types are now data, not code:
    ";": {"name": "tall_grass",  "walkable": True,  "transparent": False, "transition": None},
    "^": {"name": "rough",       "walkable": True,  "transparent": True,  "transition": None},
}

# Unknown glyph → fail safe as a solid, opaque, non-transition wall.
DEFAULT = {"name": "unknown", "walkable": False, "transparent": False, "transition": None}


def get(glyph: str) -> dict:
    return TILES.get(glyph, DEFAULT)


def known(glyph: str) -> bool:
    return glyph in TILES


def walkable(glyph: str) -> bool:
    return get(glyph)["walkable"]


def transparent(glyph: str) -> bool:
    return get(glyph)["transparent"]


def transition(glyph: str) -> Optional[str]:
    """The zone-transition kind for a glyph (None / "door" / "up" / "down")."""
    return get(glyph)["transition"]


def tiledef(glyph: str) -> dict:
    """Client-facing render/behavior hints for one glyph."""
    d = get(glyph)
    return {"name": d["name"], "walkable": d["walkable"], "transparent": d["transparent"]}


def tiledefs_for(glyphs) -> Dict[str, dict]:
    """A compact map of the distinct glyphs present → their tiledefs, for the
    `zone_state.tiledefs` snapshot field (so the client derives its rules)."""
    return {g: tiledef(g) for g in set(glyphs)}
