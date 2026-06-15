#!/usr/bin/env python3
"""
Tile-based, real-time melee for the MUD (Phase 1 graphical overhaul).

Combat is now resolved one strike at a time, gated on tile adjacency:

- The *player* strikes via bump-to-attack (stepping into a combatant's tile)
  or an explicit ``attack {target_id}``. One command = one strike.
- The *mob* strikes back on the combat tick when it is adjacent to a player
  (see game_loop.py). It is no longer a single bundled "round" — retaliation is
  driven by real time, so a faster player can get extra hits in.

Mechanics are the same D20-style rolls derived from ability scores. Health
changes write through to the DB. A defeated NPC is removed from the zone; a
defeated player respawns at the starting room with full health.

Layer-1 combat events also fan out to Layer-2 smack-talk (see smack_talk.py).

See ARCHITECTURE.md and docs/handoff-02-phase1-tiled-combat-slice.md.
"""
import asyncio
import random
import time
from typing import Dict, Optional

from database import SessionLocal
import services
from websocket_manager import manager
from world import world
import smack_talk
from config import STARTING_ROOM_ID, RESPAWN_GRACE_SECONDS

_DAMAGE_DIE = 6        # 1dN base weapon damage
_LOW_HP_FRACTION = 0.3  # threshold for "wounded" smack-talk
# Player respawn invulnerability: player_id -> monotonic time the grace ends.
_respawn_grace: Dict[int, float] = {}


def _attack_roll(attacker, defender) -> Dict:
    """Resolve one attack: d20 + STR mod vs AC (10 + DEX mod). On hit, deal
    1d6 + STR mod damage (minimum 1)."""
    to_hit = random.randint(1, 20) + attacker.ability_mod("str")
    armor_class = 10 + defender.ability_mod("dex")
    if to_hit < armor_class:
        return {"hit": False, "damage": 0}
    damage = max(1, random.randint(1, _DAMAGE_DIE) + attacker.ability_mod("str"))
    return {"hit": True, "damage": damage}


def _combat_event(attacker_name, attacker_id, attacker_type,
                  target_name, target_id, target_type, roll, target_hp, target_max) -> Dict:
    return {
        "event": "combat",
        "attacker": attacker_name, "attacker_id": attacker_id, "attacker_type": attacker_type,
        "target": target_name, "target_id": target_id, "target_type": target_type,
        "hit": roll["hit"], "damage": roll["damage"],
        "target_hp": target_hp, "target_max_hp": target_max,
    }


def _adjacent(room_id: int, player_id: int, npc_id: int) -> bool:
    """True if the player and NPC are within melee reach (Chebyshev distance 1)."""
    p = world.position_of("player", room_id, player_id)
    n = world.position_of("npc", room_id, npc_id)
    if p is None or n is None:
        return False
    return world.chebyshev(p, n) <= 1


async def resolve_player_attack(player_id: int, room_id: int, npc_id: int) -> None:
    """Player strikes an adjacent NPC once (bump-to-attack or explicit attack)."""
    db = SessionLocal()
    try:
        player = services.PlayerService.get_player(db, player_id)
        npc = services.NpcService.get_npc(db, npc_id)
        if player is None or npc is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "NPC or player not found"})
            return
        if not npc.combat_enabled:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"{npc.name} cannot be fought"})
            return
        if npc.health <= 0:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"{npc.name} is already defeated"})
            return
        if not _adjacent(room_id, player_id, npc_id):
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"{npc.name} is out of reach"})
            return

        player_name, npc_name = player.name, npc.name
        npc_max = npc.max_health
        roll = _attack_roll(player, npc)
        npc.health = max(0, npc.health - roll["damage"])
        db.commit()
        npc_hp = npc.health
        npc_dead = npc_hp <= 0
        npc_glyph = npc.glyph
    finally:
        db.close()

    await manager.broadcast_to_room(room_id, _combat_event(
        player_name, player_id, "player", npc_name, npc_id, "npc", roll, npc_hp, npc_max))

    if npc_dead:
        world.kill_npc(room_id, npc_id)  # removes from map; schedules respawn if hostile
        await manager.broadcast_to_room(
            room_id, {"event": "entity_died", "id": npc_id, "kind": "npc",
                      "name": npc_name, "by": player_name})
        return

    # Layer-1 -> Layer-2: the mob reacts to being hit / being wounded.
    if roll["hit"]:
        event = "wounded" if npc_hp <= npc_max * _LOW_HP_FRACTION else "took_hit"
        asyncio.create_task(smack_talk.maybe_smack(npc_id, room_id, npc_name, event,
                                                   glyph=npc_glyph))


async def resolve_mob_attack(npc_id: int, room_id: int, player_id: int) -> None:
    """A hostile mob strikes an adjacent player once (driven by the combat tick)."""
    if time.monotonic() < _respawn_grace.get(player_id, 0.0):
        return  # post-respawn grace — mobs can't land a hit yet (escape window)
    db = SessionLocal()
    try:
        player = services.PlayerService.get_player(db, player_id)
        npc = services.NpcService.get_npc(db, npc_id)
        if player is None or npc is None or npc.health <= 0 or player.health <= 0:
            return
        player_name, npc_name = player.name, npc.name
        player_max = player.max_health
        npc_glyph = npc.glyph
        roll = _attack_roll(npc, player)
        player.health = max(0, player.health - roll["damage"])
        db.commit()
        player_hp = player.health
        player_dead = player_hp <= 0
        if player_dead:
            player.health = player.max_health  # heal on respawn
            db.commit()
    finally:
        db.close()

    await manager.broadcast_to_room(room_id, _combat_event(
        npc_name, npc_id, "npc", player_name, player_id, "player", roll, player_hp, player_max))

    if roll["hit"] and not player_dead:
        event = "player_wounded" if player_hp <= player_max * _LOW_HP_FRACTION else "landed_hit"
        asyncio.create_task(smack_talk.maybe_smack(npc_id, room_id, npc_name, event,
                                                   glyph=npc_glyph))

    if player_dead:
        await manager.broadcast_to_room(
            room_id, {"event": "player_defeated", "player_id": player_id,
                      "name": player_name, "by": npc_name})
        await _respawn(player_id, room_id, player_name, player_max)


async def _respawn(player_id: int, from_room: int, player_name: str, player_max: int) -> None:
    """Move a defeated player to the starting room, re-place on its spawn tile,
    and send them a fresh zone snapshot."""
    world.move_player(player_id, STARTING_ROOM_ID)
    pos = world.place_player(player_id, STARTING_ROOM_ID)
    _respawn_grace[player_id] = time.monotonic() + RESPAWN_GRACE_SECONDS  # escape window
    if from_room != STARTING_ROOM_ID:
        manager.unsubscribe_from_room(player_id, from_room)
        manager.subscribe_to_room(player_id, STARTING_ROOM_ID)
        await manager.broadcast_to_room(
            STARTING_ROOM_ID,
            {"event": "entity_spawned", "id": player_id, "kind": "player", "name": player_name,
             **_spawn_fields(player_id, STARTING_ROOM_ID)},
            exclude_player=player_id,
        )
    elif pos is not None:
        # Respawned in the same room — tell others they snapped back to spawn.
        await manager.broadcast_to_room(
            STARTING_ROOM_ID, {"event": "entity_moved", "id": player_id, "x": pos[0], "y": pos[1]},
            exclude_player=player_id,
        )
    await manager.send_personal_message(
        player_id, {"event": "respawn", "room_id": STARTING_ROOM_ID, "health": player_max})
    await manager.send_personal_message(
        player_id, {"event": "zone_state", **world.zone_snapshot(STARTING_ROOM_ID, player_id)})


def _spawn_fields(player_id: int, room_id: int) -> dict:
    """glyph + (x,y) for an entity_spawned event."""
    pos = world.position_of("player", room_id, player_id) or world.rooms[room_id].spawn
    db = SessionLocal()
    try:
        player = services.PlayerService.get_player(db, player_id)
        glyph = (player.glyph if player else None) or "🧙"
    finally:
        db.close()
    return {"glyph": glyph, "x": pos[0], "y": pos[1]}
