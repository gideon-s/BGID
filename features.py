#!/usr/bin/env python3
"""
Tile-feature interactions (handoff-09 §1/§2): traps, hazards, and AoE objects.

Features live in ``world`` (loaded from the ``room_features`` table into
``RoomNode.features``); this module resolves what happens when an entity steps on
one (traps/hazards — telegraphed for MVP) or triggers one (a powder keg's AoE
blast). Damage routes through the shared ``combat`` death paths, and effects
through ``effects``/``debuffs``, so loot/XP/respawn/DoT all behave as elsewhere.

Config (JSON on the row) per kind:
  trap/hazard : {name, damage:int, radius:int(0=tile), debuff:str?, one_shot:bool}
  keg         : {name, damage:int, radius:int, debuff:str?}
A ``radius>0`` makes any of them **area-of-effect** (reuses ``tiles_in_radius``).
"""
from typing import List, Tuple

import combat
import debuffs
import effects
import models
from database import SessionLocal
from websocket_manager import manager
from world import world

# One-shot traps that have already fired (in-memory; cleared on restart).
_sprung: set = set()


def reset() -> None:
    """Test isolation: forget which one-shot traps have fired."""
    _sprung.clear()


def _affected(room_id: int, cx: int, cy: int, radius: int) -> List[Tuple[str, int]]:
    """Entities occupying the trigger tile (radius 0) or every tile within a
    Chebyshev radius (AoE)."""
    tiles = (world.tiles_in_radius(room_id, (cx, cy), radius)
             if radius > 0 else [(cx, cy)])
    victims = []
    for (tx, ty) in tiles:
        occ = world.occupant_at(room_id, tx, ty)
        if occ is not None:
            victims.append(occ)
    return victims


async def _hit(room_id: int, kind: str, ent_id: int, cfg: dict, name: str) -> None:
    """Apply a feature's damage (+ optional debuff) to one entity, attributing it
    to the feature (no XP — by_type 'trap')."""
    dmg = int(cfg.get("damage", 0))
    debuff = cfg.get("debuff")
    if kind == "player":
        dead = False
        if dmg > 0:
            dead = await combat.damage_player(room_id, ent_id, dmg, name, 0, "trap")
        if debuff and not dead:
            pkey = effects.eid("player", ent_id)
            debuffs.apply_to(pkey, debuff, source_name=name, source_type="trap")
            await manager.send_personal_message(
                ent_id, {"event": "effects", "effects": effects.snapshot(pkey)})
    elif kind == "npc":
        if dmg > 0:
            await combat.damage_npc(room_id, ent_id, dmg, name, 0, "trap")
        if debuff and world.position_of("npc", room_id, ent_id) is not None:
            nkey = effects.eid("npc", ent_id)
            debuffs.apply_to(nkey, debuff, source_name=name, source_type="trap")
            await manager.broadcast_to_room(
                room_id, {"event": "entity_effects", "id": ent_id,
                          "effects": effects.snapshot(nkey)})


async def _detonate(room_id: int, feat: dict) -> None:
    """Resolve a feature's effect on everyone in its area + broadcast the FX."""
    cfg = feat["config"]
    radius = int(cfg.get("radius", 0))
    name = cfg.get("name", feat["kind"])
    for (kind, ent_id) in _affected(room_id, feat["x"], feat["y"], radius):
        await _hit(room_id, kind, ent_id, cfg, name)
    await manager.broadcast_to_room(room_id, {
        "event": "feature_triggered", "id": feat["id"], "kind": feat["kind"],
        "x": feat["x"], "y": feat["y"], "radius": radius,
        "glyph": feat["glyph"], "name": name})


async def on_enter(room_id: int, kind: str, ent_id: int, x: int, y: int) -> None:
    """An entity stepped onto (x, y): fire a trap/hazard there, if any. Called
    from the player move handler and the mob AI step (symmetry)."""
    feat = world.feature_at(room_id, x, y)
    if feat is None or feat["kind"] not in ("trap", "hazard"):
        return
    if feat["config"].get("one_shot"):
        if feat["id"] in _sprung:
            return
        _sprung.add(feat["id"])
    await _detonate(room_id, feat)


async def trigger_keg(room_id: int, feat: dict) -> None:
    """Ignite a powder keg (an AoE object): blast its radius, then consume it."""
    await _detonate(room_id, feat)
    world.remove_feature(room_id, feat["id"])
    db = SessionLocal()
    try:
        row = db.get(models.RoomFeature, feat["id"])
        if row is not None:
            db.delete(row); db.commit()
    finally:
        db.close()
    await manager.broadcast_to_room(
        room_id, {"event": "feature_removed", "id": feat["id"]})
