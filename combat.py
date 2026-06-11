#!/usr/bin/env python3
"""
Turn-based combat for the MUD.

One `attack` command resolves a single round: the player strikes the NPC, then
the NPC strikes back if it survives and is a combatant. Mechanics are D20-style,
derived from the ability scores already on the models. Health changes write
through to the DB. A defeated NPC is removed from its room; a defeated player
respawns at the starting room with full health.

See ARCHITECTURE.md (step 4).
"""
import random
from typing import Dict

from database import SessionLocal
import services
from websocket_manager import manager
from world import world

STARTING_ROOM_ID = 1   # where defeated players respawn
_DAMAGE_DIE = 6        # 1dN base weapon damage


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
                  target_name, target_id, target_type, roll, target_health, target_max) -> Dict:
    return {
        "event": "combat",
        "attacker": attacker_name, "attacker_id": attacker_id, "attacker_type": attacker_type,
        "target": target_name, "target_id": target_id, "target_type": target_type,
        "hit": roll["hit"], "damage": roll["damage"],
        "target_health": target_health, "target_max_health": target_max,
    }


async def run_combat_round(player_id: int, room_id: int, npc_id: int) -> None:
    """Resolve one round of combat between a player and an NPC in a room."""
    # ---- DB phase: validate, roll, apply damage, commit (no awaits/broadcasts) ----
    db = SessionLocal()
    try:
        player = services.PlayerService.get_player(db, player_id)
        npc = services.NpcService.get_npc(db, npc_id)
        if player is None or npc is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "NPC or player not found"}
            )
            return
        if not npc.combat_enabled:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"{npc.name} cannot be fought"}
            )
            return
        if npc.health <= 0:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"{npc.name} is already defeated"}
            )
            return

        player_name, npc_name = player.name, npc.name
        npc_max, player_max = npc.max_health, player.max_health

        # Round: player strikes the NPC
        r1 = _attack_roll(player, npc)
        npc.health = max(0, npc.health - r1["damage"])
        db.commit()
        npc_health = npc.health
        npc_dead = npc_health <= 0

        # NPC retaliates only if it survived
        r2 = None
        player_health = player.health
        player_dead = False
        if not npc_dead:
            r2 = _attack_roll(npc, player)
            player.health = max(0, player.health - r2["damage"])
            db.commit()
            player_health = player.health
            player_dead = player_health <= 0
            if player_dead:
                # Heal on respawn; the room move happens below via world.move_player
                player.health = player.max_health
                db.commit()
    finally:
        db.close()

    # ---- Messaging + world-state phase (no DB session held) ----
    # Player -> NPC
    await manager.broadcast_to_room(room_id, _combat_event(
        player_name, player_id, "player", npc_name, npc_id, "npc", r1, npc_health, npc_max))

    if npc_dead:
        if room_id in world.rooms:
            world.rooms[room_id].npc_ids.discard(npc_id)
        await manager.broadcast_to_room(
            room_id, {"event": "npc_defeated", "npc_id": npc_id, "name": npc_name, "by": player_name})
        return

    # NPC -> player
    await manager.broadcast_to_room(room_id, _combat_event(
        npc_name, npc_id, "npc", player_name, player_id, "player", r2, player_health, player_max))

    if player_dead:
        await manager.broadcast_to_room(
            room_id, {"event": "player_defeated", "player_id": player_id, "name": player_name, "by": npc_name})
        # Respawn: move to the starting room (in-memory + DB) and resubscribe
        world.move_player(player_id, STARTING_ROOM_ID)
        if room_id != STARTING_ROOM_ID:
            manager.unsubscribe_from_room(player_id, room_id)
            manager.subscribe_to_room(player_id, STARTING_ROOM_ID)
            await manager.broadcast_to_room(
                STARTING_ROOM_ID,
                {"event": "player_entered", "player_id": player_id, "name": player_name},
                exclude_player=player_id,
            )
        await manager.send_personal_message(
            player_id, {"event": "respawn", "room_id": STARTING_ROOM_ID, "health": player_max})
        await manager.send_personal_message(
            player_id, {"event": "room_state", **world.room_snapshot(STARTING_ROOM_ID)})
