#!/usr/bin/env python3
"""
Base-10 coin currency.

A wallet is a single integer count of **copper** (the base unit); the higher
denominations are exact powers of ten, so conversion is pure arithmetic:

    1 platinum = 10 gold = 100 silver = 1000 copper

Players hold `Player.coins` (copper). Gems are NOT currency — they're valued
items (`item_type == "gem"`, worth `Item.value` copper) you carry and, later,
sell. A coin pickup (`item_type == "coins"`) adds its `value` straight to the
wallet.
"""
from typing import Dict, List, Tuple

# name, short tag, value in copper — highest first.
DENOMINATIONS: List[Tuple[str, str, int]] = [
    ("platinum", "pp", 1000),
    ("gold", "gp", 100),
    ("silver", "sp", 10),
    ("copper", "cp", 1),
]


def breakdown(copper: int) -> Dict[str, int]:
    """Split a copper total into {platinum, gold, silver, copper}."""
    copper = max(0, int(copper or 0))
    out: Dict[str, int] = {}
    for name, _tag, unit in DENOMINATIONS:
        out[name], copper = divmod(copper, unit)
    return out


def short(copper: int) -> str:
    """Compact wallet string, highest non-zero denominations first.

    e.g. 1234 -> "1pp 2gp 3sp 4cp"; 50 -> "5sp"; 0 -> "0cp".
    """
    copper = max(0, int(copper or 0))
    if copper == 0:
        return "0cp"
    parts = []
    for name, tag, unit in DENOMINATIONS:
        q, copper = divmod(copper, unit)
        if q:
            parts.append(f"{q}{tag}")
    return " ".join(parts)
