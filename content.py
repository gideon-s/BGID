#!/usr/bin/env python3
"""
Content config layer (handoff-10 §1) — code registries become editable data.

Each registry module (spells, potions, debuffs, gear) keeps its authored Python
dict as the **defaults** and `register()`s here with an *applier* that installs a
merged dict back onto the module global. The live registry is always
``{**defaults, **overrides}`` where overrides are JSON rows in the ``content``
table (keyed by ``kind``/``key``). So:

- an empty store = pure code defaults (safe, additive — wipe anytime);
- editing an entry writes one row and **hot-reloads** that registry (no restart);
- deleting an override reverts that key to its code default (or removes an
  addition). Validation runs on write so a bad doc can't reach the live game.

Reassigning the module global is safe because every registry reads its dict via a
module-level accessor (e.g. ``spells.get_spell`` reads ``SPELLS``) at call time.
"""
import json
from typing import Callable, Dict

import models
from database import SessionLocal

# kind -> {"defaults": dict, "apply": callable(merged_dict)}
_registries: Dict[str, dict] = {}


def register(kind: str, defaults: dict, apply: Callable[[dict], None]) -> None:
    """A registry registers its authored defaults + an applier. Starts from the
    pure defaults (no DB touch at import); call ``reload`` to overlay the store."""
    _registries[kind] = {"defaults": dict(defaults), "apply": apply}
    apply(dict(defaults))


def kinds():
    return sorted(_registries)


def _overlay(db, kind: str) -> dict:
    out = {}
    for row in db.query(models.Content).filter_by(kind=kind).all():
        try:
            out[row.key] = json.loads(row.data)
        except (ValueError, TypeError):
            pass
    return out


def reload(kind: str) -> dict:
    """Rebuild one registry = defaults + DB overrides, install it, return it."""
    reg = _registries.get(kind)
    if reg is None:
        return {}
    db = SessionLocal()
    try:
        merged = {**reg["defaults"], **_overlay(db, kind)}
    finally:
        db.close()
    reg["apply"](merged)
    return merged


def reload_all() -> None:
    for kind in _registries:
        reload(kind)


def reset() -> None:
    """Test isolation: reapply pure defaults, ignoring the store."""
    for reg in _registries.values():
        reg["apply"](dict(reg["defaults"]))


def defaults(kind: str) -> dict:
    reg = _registries.get(kind)
    return dict(reg["defaults"]) if reg else {}


def current(kind: str) -> dict:
    """Merged live view (defaults + overrides) — for the editor."""
    return reload(kind)


def is_default(kind: str, key: str) -> bool:
    reg = _registries.get(kind)
    return bool(reg and key in reg["defaults"])


def upsert(kind: str, key: str, data: dict) -> dict:
    """Validate + write one override, then hot-reload. Returns the merged view."""
    if kind not in _registries:
        raise ValueError(f"unknown content kind: {kind!r}")
    validate(kind, key, data)
    db = SessionLocal()
    try:
        row = db.query(models.Content).filter_by(kind=kind, key=key).first()
        if row is None:
            db.add(models.Content(kind=kind, key=key, data=json.dumps(data)))
        else:
            row.data = json.dumps(data)
        db.commit()
    finally:
        db.close()
    return reload(kind)


def delete(kind: str, key: str) -> dict:
    """Remove an override (reverts to the code default if the key has one)."""
    db = SessionLocal()
    try:
        row = db.query(models.Content).filter_by(kind=kind, key=key).first()
        if row is not None:
            db.delete(row); db.commit()
    finally:
        db.close()
    return reload(kind)


# ---------- per-kind validation (keep a bad doc out of the live game) ----------
def validate(kind: str, key: str, data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("entry must be a JSON object")
    if not key:
        raise ValueError("entry key is required")
    checks = _VALIDATORS.get(kind)
    if checks:
        checks(data)


def _req(data, fields):
    missing = [f for f in fields if f not in data]
    if missing:
        raise ValueError(f"missing field(s): {', '.join(missing)}")


def _v_spell(d):
    _req(d, ["name", "cost", "shape", "effect"])
    if d["shape"] not in ("self", "bolt", "blast"):
        raise ValueError("shape must be self|bolt|blast")
    if not isinstance(d.get("effect"), dict) or "kind" not in d["effect"]:
        raise ValueError("effect must be an object with a 'kind'")


def _v_potion(d):
    _req(d, ["kind"])
    if d["kind"] not in ("heal", "mana", "restore", "buff"):
        raise ValueError("potion kind must be heal|mana|restore|buff")


def _v_debuff(d):
    if not any(k in d for k in ("atk", "dmg", "defn", "haste", "dot")):
        raise ValueError("a debuff needs at least one of atk/dmg/defn/haste/dot")


def _v_gear(d):
    if not any(k in d for k in ("atk", "dmg", "defn", "haste")):
        raise ValueError("a gear effect needs at least one of atk/dmg/defn/haste")


def _v_class(d):
    _req(d, ["name"])
    if "spells" in d and not isinstance(d["spells"], list):
        raise ValueError("'spells' must be a list of spell ids")
    if "abilities" in d and not isinstance(d["abilities"], dict):
        raise ValueError("'abilities' must be an object")
    if "starting_gear" in d and not isinstance(d["starting_gear"], list):
        raise ValueError("'starting_gear' must be a list")


def _v_race(d):
    _req(d, ["name"])
    if "abilities" in d and not isinstance(d["abilities"], dict):
        raise ValueError("'abilities' must be an object")


_VALIDATORS = {"spells": _v_spell, "potions": _v_potion,
               "debuffs": _v_debuff, "gear": _v_gear,
               "classes": _v_class, "races": _v_race}
