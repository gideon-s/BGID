#!/usr/bin/env python3
"""
Timed status effects (buffs).

In-memory, keyed by ``player_id`` — like ``world.door_unlocks``: a single worker
holds the state, it survives reconnects within a session, and a restart clears
it. Each effect carries flat combat deltas (atk/dmg/defn) and a movement ``haste``
factor, plus an expiry (monotonic). ``bonuses``/``haste_factor`` read the LIVE
set (filtered by time) so combat is always accurate to the second; the slow tick
just ``sweep``s for the "buff faded" notification + pruning.
"""
import time
from typing import Dict, List

# player_id -> list of {name, glyph, until, atk, dmg, defn, haste}
_active: Dict[int, List[dict]] = {}


def apply_effect(player_id: int, name: str, glyph: str, duration: float,
                 atk: int = 0, dmg: int = 0, defn: int = 0, haste: float = 1.0) -> None:
    """Apply (or refresh, if same-named) a timed effect on a player."""
    rest = [e for e in _active.get(player_id, []) if e["name"] != name]
    rest.append({"name": name, "glyph": glyph, "until": time.monotonic() + duration,
                 "atk": atk, "dmg": dmg, "defn": defn, "haste": haste})
    _active[player_id] = rest


def active(player_id: int) -> List[dict]:
    """Currently-active (non-expired) effects on a player."""
    now = time.monotonic()
    return [e for e in _active.get(player_id, []) if e["until"] > now]


def bonuses(player_id: int) -> Dict[str, int]:
    """Summed combat bonuses from active buffs: {attack, damage, defense}."""
    a = d = f = 0
    for e in active(player_id):
        a += e["atk"]; d += e["dmg"]; f += e["defn"]
    return {"attack": a, "damage": d, "defense": f}


def haste_factor(player_id: int) -> float:
    """Move-cooldown multiplier from active haste (the strongest wins). 1.0 = none."""
    fac = 1.0
    for e in active(player_id):
        fac = min(fac, e["haste"])
    return fac


def snapshot(player_id: int) -> List[dict]:
    """Serializable active effects for the client: [{name, glyph, remaining}]."""
    now = time.monotonic()
    return [{"name": e["name"], "glyph": e["glyph"], "remaining": max(0, int(e["until"] - now))}
            for e in active(player_id)]


def clear(player_id: int) -> None:
    _active.pop(player_id, None)


def sweep() -> Dict[int, List[str]]:
    """Prune expired effects; return {player_id: [expired effect names]}."""
    now = time.monotonic()
    expired: Dict[int, List[str]] = {}
    for pid in list(_active.keys()):
        gone = [e["name"] for e in _active[pid] if e["until"] <= now]
        kept = [e for e in _active[pid] if e["until"] > now]
        if gone:
            expired[pid] = gone
        if kept:
            _active[pid] = kept
        else:
            _active.pop(pid, None)
    return expired
