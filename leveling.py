#!/usr/bin/env python3
"""
Experience & levels.

A simple triangular XP curve: to *reach* level L you need a cumulative
``XP_BASE * (L-1)*L/2`` experience — so each level costs ``XP_BASE`` more than
the one before (L2=100, L3=300, L4=600, L5=1000, …). Killing a mob grants XP
scaled by its toughness; on a level-up a character gains HP (and mana, for
casters) and is healed to full. See services.PlayerService.award_xp.
"""
XP_BASE = 100          # extra XP each successive level costs
HP_PER_LEVEL = 4       # max-HP gained per level, BEFORE the CON modifier
MANA_PER_LEVEL = 3     # max-MP gained per level (casters only)


def xp_to_reach(level: int) -> int:
    """Cumulative XP required to BE at `level` (level 1 = 0)."""
    if level <= 1:
        return 0
    return XP_BASE * (level - 1) * level // 2


def level_for_xp(xp: int) -> int:
    """The level a given total XP corresponds to."""
    xp = max(0, int(xp or 0))
    level = 1
    while xp >= xp_to_reach(level + 1):
        level += 1
    return level


def progress(xp: int):
    """(level, xp_into_this_level, xp_needed_for_next) — for a progress bar."""
    level = level_for_xp(xp)
    base = xp_to_reach(level)
    nxt = xp_to_reach(level + 1)
    return level, max(0, int(xp or 0)) - base, nxt - base


def xp_for_kill(npc_max_health: int) -> int:
    """XP awarded for slaying a mob — scales with its max HP (Rat 8hp → 16)."""
    return max(5, int((npc_max_health or 8) * 2))
