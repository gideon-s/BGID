#!/usr/bin/env python3
"""
Spell casting (Phase 4 graphical overhaul) — Layer 1, deterministic, no LLM.

`resolve_cast` is the single entry point the WS `cast` command calls. It mirrors
the melee resolvers in combat.py: validate, mutate authoritative state, broadcast.
Spells auto-hit; range + line-of-sight is the counterplay (see spells.py). Damage
reuses the shared `combat.damage_npc` / `combat.damage_player` paths so death,
respawn, and the combat log behave exactly as melee.

Targeting by shape:
  self  -> the caster's own tile (heals, buffs)
  bolt  -> the single entity on the target tile (range + LOS required)
  blast -> every entity within the spell's radius of the target tile (AoE)

Mana is spent only on a *successful* cast; cooldown is per (player, spell).
"""
import time
from typing import Dict, Optional, Tuple

from database import SessionLocal
import services
import classes
import spells
import combat
import effects
import debuffs
from websocket_manager import manager
from world import world

# Per-(player_id, spell_id) cooldown clock: monotonic time the spell is ready
# again. A missing entry means "ready now". Mirrors combat/game_loop clocks.
_cooldowns: Dict[Tuple[int, str], float] = {}


def reset() -> None:
    """Clear all cast cooldowns (test isolation)."""
    _cooldowns.clear()


async def _err(player_id: int, detail: str, **extra) -> None:
    await manager.send_personal_message(
        player_id, {"event": "error", "detail": detail, **extra})


async def resolve_cast(player_id: int, room_id: int, spell_id: str,
                       tx: Optional[int], ty: Optional[int]) -> None:
    """Validate and resolve one spell cast for a player."""
    spell = spells.get_spell(spell_id)
    if spell is None:
        await _err(player_id, "You don't know that spell.")
        return

    now = time.monotonic()
    db = SessionLocal()
    try:
        player = services.PlayerService.get_player(db, player_id)
        if player is None or player.health <= 0:
            await _err(player_id, "You can't cast right now.")
            return
        if spell_id not in classes.spell_ids_for(player.char_class):
            await _err(player_id, f"Your class can't cast {spell['name']}.")
            return
        if player.mana < spell["cost"]:
            await _err(player_id, f"Not enough mana for {spell['name']}.")
            return
        ready = _cooldowns.get((player_id, spell_id), 0.0)
        if now < ready:
            await _err(player_id, f"{spell['name']} is recharging.",
                       retry_after=round(ready - now, 1))
            return

        cpos = world.position_of("player", room_id, player_id)
        if cpos is None:
            await _err(player_id, "You aren't anywhere castable.")
            return

        shape = spell["shape"]
        if shape == "self":
            tx, ty = cpos
        else:
            if tx is None or ty is None:
                await _err(player_id, "Pick a target.")
                return
            if world.chebyshev(cpos, (tx, ty)) > spell["range"]:
                await _err(player_id, f"{spell['name']} is out of range.")
                return
            if not world.line_of_sight(room_id, cpos, (tx, ty)):
                await _err(player_id, "No line of sight to that tile.")
                return

        # Gather targets; for a bolt, require something on the tile BEFORE we
        # spend mana (don't burn a cast on empty air).
        targets = []   # list of (kind, id)
        if shape == "bolt":
            occ = world.occupant_at(room_id, tx, ty)
            if occ is None:
                await _err(player_id, "Nothing there to hit.")
                return
            targets = [occ]
        elif shape == "blast":
            for (x, y) in world.tiles_in_radius(room_id, (tx, ty), spell.get("radius", 1)):
                occ = world.occupant_at(room_id, x, y)
                if occ is not None:
                    targets.append(occ)

        eff_kind = spell["effect"]["kind"]
        # Roll magnitudes while we hold the caster (its ability mods feed roll).
        dmg = [spells.roll_effect(player, spell) for _ in targets] if eff_kind == "damage" else []

        # Spend mana now that the cast is committed.
        player.mana = max(0, player.mana - spell["cost"])
        heal_fields = None
        if eff_kind == "heal":
            player.heal(spells.roll_effect(player, spell))
            heal_fields = {"hp": player.health, "max_hp": player.max_health}
        db.commit()
        caster_name = player.name
        mana_now, max_mana = player.mana, player.max_mana
    finally:
        db.close()

    _cooldowns[(player_id, spell_id)] = now + spell["cooldown"]

    # VFX for everyone in the zone (a streaking bolt / expanding ring / glow).
    await manager.broadcast_to_room(room_id, {
        "event": "spell_cast", "caster_id": player_id, "spell": spell_id,
        "name": spell["name"], "glyph": spell["glyph"], "fx": shape,
        "x0": cpos[0], "y0": cpos[1], "x": tx, "y": ty,
        "radius": spell.get("radius", 0)})

    # Apply damage via the shared combat paths (broadcast combat/death/respawn).
    if eff_kind == "damage":
        for (kind, tid), amount in zip(targets, dmg):
            if kind == "npc":
                await combat.damage_npc(room_id, tid, amount, caster_name, player_id, "player")
            elif kind == "player" and tid != player_id:
                await combat.damage_player(room_id, tid, amount, caster_name, player_id, "player")

    # Buff (self) / debuff (each surviving npc target) application (handoff-08 §5).
    eff = spell["effect"]
    if eff_kind == "buff":
        pkey = effects.eid("player", player_id)
        effects.apply_effect(
            pkey, eff.get("name", spell["name"]), eff.get("glyph", spell["glyph"]),
            eff.get("duration", 30), atk=eff.get("atk", 0), dmg=eff.get("dmg", 0),
            defn=eff.get("defn", 0), haste=eff.get("haste", 1.0))
        await manager.send_personal_message(
            player_id, {"event": "effects", "effects": effects.snapshot(pkey)})
    debuff_name = eff.get("debuff")
    if debuff_name:
        for (kind, tid) in targets:
            # Skip a target the damage already killed (removed from the world).
            if kind != "npc" or world.position_of("npc", room_id, tid) is None:
                continue
            nkey = effects.eid("npc", tid)
            debuffs.apply_to(nkey, debuff_name, source_name=caster_name,
                             source_id=player_id, source_type="player")
            await manager.broadcast_to_room(
                room_id, {"event": "entity_effects", "id": tid,
                          "effects": effects.snapshot(nkey)})

    # Refresh the caster's bars (mana always; hp too if they healed).
    stats = {"event": "stats", "player_id": player_id,
             "mana": mana_now, "max_mana": max_mana}
    if heal_fields:
        stats.update(heal_fields)
    await manager.send_personal_message(player_id, stats)
