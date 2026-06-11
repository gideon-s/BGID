#!/usr/bin/env python3
"""
NPC turn handling — the async LLM-NPC mechanic.

A "turn" runs the (slow, 2-5s) DeepSeek call as a fire-and-forget asyncio task
so it never blocks the asking player's socket or anyone else's. The room is
told the NPC is "thinking", then broadcast the reply when it lands — so every
player present sees the NPC's response, not just the asker.

This module is also the single source of truth for mapping a stored Npc row
onto an LLM-capable BaseLLMNPC (reused by the REST /chat/npc endpoint).

See ARCHITECTURE.md (step 3).
"""
from database import SessionLocal
import services
from llm_npcs import BaseLLMNPC, NPCContext, NPCDisposition, NPCRole, NPCStats
from websocket_manager import manager
from world import world

# Map stored npc_type strings to NPC roles for the LLM prompt
_NPC_TYPE_TO_ROLE = {
    "merchant": NPCRole.MERCHANT,
    "quest_giver": NPCRole.QUEST_GIVER,
    "combat_mob": NPCRole.COMBAT_MOB,
    "informant": NPCRole.INFORMANT,
    "companion": NPCRole.COMPANION,
    "boss": NPCRole.BOSS,
}


def build_llm_npc(npc) -> BaseLLMNPC:
    """Build an LLM-capable NPC from a stored Npc row.

    Reads ORM attributes eagerly, so the returned object is safe to use after
    the DB session closes.
    """
    role = _NPC_TYPE_TO_ROLE.get(npc.npc_type, NPCRole.INFORMANT)
    disposition = NPCDisposition.FRIENDLY if npc.is_friendly else NPCDisposition.NEUTRAL
    stats = NPCStats(health=npc.health, max_health=npc.max_health)
    return BaseLLMNPC(
        npc_id=npc.id,
        name=npc.name,
        description=npc.description,
        disposition=disposition,
        role=role,
        stats=stats,
    )


def build_context(player) -> NPCContext:
    """Build interaction context from a stored Player row.

    Reputation/gold are not modeled yet, so they default to 0.
    """
    return NPCContext(
        player_level=player.level,
        player_reputation=0,
        player_health=player.health,
        player_gold=0,
        room_id=player.room_id,
    )


async def run_npc_turn(player_id: int, room_id: int, npc_id: int, message: str) -> None:
    """Run one NPC turn: announce "thinking", call the LLM, broadcast the reply.

    Designed to be launched with asyncio.create_task() so it doesn't block the
    caller. The DB session is closed before the slow LLM call.
    """
    # Load + snapshot the ORM data, then release the session before the await
    db = SessionLocal()
    try:
        npc = services.NpcService.get_npc(db, npc_id)
        player = services.PlayerService.get_player(db, player_id)
        if npc is None or player is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "NPC or player not found"}
            )
            return
        llm_npc = build_llm_npc(npc)
        context = build_context(player)
        npc_name = npc.name
    finally:
        db.close()

    # Tell the room the NPC is composing a response
    await manager.broadcast_to_room(
        room_id, {"event": "npc_thinking", "npc_id": npc_id, "name": npc_name}
    )

    # Slow LLM call — other players keep acting while this awaits.
    # BaseLLMNPC.generate_response already falls back to rule-based on error.
    try:
        text = await llm_npc.generate_response(message, context)
    except Exception as e:  # defensive: never let a turn crash the socket loop
        print(f"NPC turn failed for npc {npc_id}: {e}")
        text = f"{npc_name} seems lost in thought and doesn't respond."

    # Broadcast the reply to everyone in the room
    await manager.broadcast_to_room(
        room_id,
        {"event": "npc_said", "npc_id": npc_id, "name": npc_name, "text": text},
    )
