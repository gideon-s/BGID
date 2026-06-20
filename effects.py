#!/usr/bin/env python3
"""
Timed status effects — buffs *and* debuffs, on players *and* NPCs.

In-memory, keyed by an **entity key** ``"player:{id}"`` / ``"npc:{id}"`` (build it
with :func:`eid`) — like ``world.door_unlocks``: a single worker holds the state,
it survives reconnects within a session, and a restart clears it. Each effect
carries flat combat deltas (atk/dmg/defn), a movement ``haste`` factor, and an
optional **damage-over-time** (``dot`` every ``dot_interval`` seconds), plus an
expiry (monotonic — or ``INFINITE`` for non-expiring **gear** effects).

``bonuses``/``haste_factor`` read the LIVE set (filtered by time) so combat is
always accurate to the second; the slow tick ``sweep``s for the "effect faded"
notification + pruning, and the fast tick drains ``due_dots`` for poison etc.
"""
import time
from typing import Dict, List, Tuple

# Non-expiring sentinel for gear effects (active while worn, removed on unequip).
INFINITE = float("inf")

# entity_key ("player:7" / "npc:3") -> list of
#   {name, glyph, until, atk, dmg, defn, haste, dot, dot_interval, _next,
#    harm, gear, source_name, source_id, source_type}
_active: Dict[str, List[dict]] = {}


def eid(kind: str, entity_id: int) -> str:
    """Stable effect key for an entity: ``eid('player', 7) == 'player:7'``."""
    return f"{kind}:{entity_id}"


def split_eid(key: str) -> Tuple[str, int]:
    """Inverse of :func:`eid`: ``'npc:3' -> ('npc', 3)``."""
    kind, _, sid = key.partition(":")
    return kind, int(sid)


def apply_effect(key: str, name: str, glyph: str, duration: float,
                 atk: int = 0, dmg: int = 0, defn: int = 0, haste: float = 1.0,
                 dot: int = 0, dot_interval: float = 3.0,
                 harm: bool = False, gear: bool = False,
                 source_name: str = None, source_id: int = None,
                 source_type: str = None) -> None:
    """Apply (or refresh, if same-named) a status effect on an entity.

    ``gear=True`` makes the effect non-expiring (until explicitly ``remove``d);
    ``dot>0`` drains ``dot`` damage every ``dot_interval`` seconds (see
    ``due_dots``), attributed to ``source_*`` so a DoT kill awards XP/loot to its
    applier. ``harm=True`` marks a debuff (the client tints it red)."""
    now = time.monotonic()
    until = INFINITE if gear else now + duration
    rest = [e for e in _active.get(key, []) if e["name"] != name]
    rest.append({"name": name, "glyph": glyph, "until": until,
                 "atk": atk, "dmg": dmg, "defn": defn, "haste": haste,
                 "dot": dot, "dot_interval": dot_interval, "_next": now + dot_interval,
                 "harm": harm, "gear": gear,
                 "source_name": source_name, "source_id": source_id,
                 "source_type": source_type})
    _active[key] = rest


def remove(key: str, name: str) -> bool:
    """Remove a named effect from an entity (e.g. a gear effect on unequip).
    Returns True if something was removed."""
    cur = _active.get(key)
    if not cur:
        return False
    rest = [e for e in cur if e["name"] != name]
    if len(rest) == len(cur):
        return False
    if rest:
        _active[key] = rest
    else:
        _active.pop(key, None)
    return True


def active(key: str) -> List[dict]:
    """Currently-active (non-expired) effects on an entity."""
    now = time.monotonic()
    return [e for e in _active.get(key, []) if e["until"] > now]


def bonuses(key: str) -> Dict[str, int]:
    """Summed combat deltas from active effects: {attack, damage, defense}.
    Debuffs contribute negative values."""
    a = d = f = 0
    for e in active(key):
        a += e["atk"]; d += e["dmg"]; f += e["defn"]
    return {"attack": a, "damage": d, "defense": f}


def haste_factor(key: str) -> float:
    """Move-cooldown multiplier from active haste (the strongest wins). 1.0 = none."""
    fac = 1.0
    for e in active(key):
        fac = min(fac, e["haste"])
    return fac


def snapshot(key: str) -> List[dict]:
    """Serializable active effects for the client:
    [{name, glyph, remaining, harm, gear}]. Gear effects have ``remaining=None``
    (shown without a countdown)."""
    now = time.monotonic()
    return [{"name": e["name"], "glyph": e["glyph"], "harm": e["harm"], "gear": e["gear"],
             "remaining": None if e["gear"] else max(0, int(e["until"] - now))}
            for e in active(key)]


def clear(key: str) -> None:
    _active.pop(key, None)


def clear_expirable(key: str) -> None:
    """Drop all non-gear effects on an entity (buffs + debuffs + DoTs), keeping
    gear-granted ones — used on death/respawn so a poison doesn't follow a
    respawned player and a Ring of Haste isn't lost while still worn."""
    cur = _active.get(key)
    if not cur:
        return
    kept = [e for e in cur if e["gear"]]
    if kept:
        _active[key] = kept
    else:
        _active.pop(key, None)


def due_dots() -> List[Tuple[str, int, str, int, str]]:
    """Drain damage-over-time: for each active DoT effect whose interval elapsed,
    advance its clock and yield ``(key, dot_amount, source_name, source_id,
    source_type)``. The caller applies each via the shared combat death paths."""
    now = time.monotonic()
    out: List[Tuple[str, int, str, int, str]] = []
    for key, lst in _active.items():
        for e in lst:
            if e["dot"] > 0 and e["until"] > now and e["_next"] <= now:
                e["_next"] = now + e["dot_interval"]
                out.append((key, e["dot"], e.get("source_name"),
                            e.get("source_id"), e.get("source_type")))
    return out


def sweep() -> Dict[str, List[str]]:
    """Prune expired (non-gear) effects; return {entity_key: [expired names]}."""
    now = time.monotonic()
    expired: Dict[str, List[str]] = {}
    for key in list(_active.keys()):
        gone = [e["name"] for e in _active[key] if not e["gear"] and e["until"] <= now]
        kept = [e for e in _active[key] if e["gear"] or e["until"] > now]
        if gone:
            expired[key] = gone
        if kept:
            _active[key] = kept
        else:
            _active.pop(key, None)
    return expired
