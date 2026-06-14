#!/usr/bin/env python3
"""
Background game loops (ticks).

Two asyncio tasks run side by side:

- **Regen tick** (`TICK_SECONDS`, slow): out-of-combat HP regeneration for
  living, in-room NPCs. The original, leisurely world tick.
- **Combat tick** (`COMBAT_TICK_SECONDS`, fast): real-time mob AI. For each room
  holding at least one online player, every hostile mob acquires the nearest
  player within its aggro radius, steps toward them, and melees when adjacent —
  emitting throttled smack-talk along the way.

The combat tick is the hot path: it operates on **in-memory tile positions only**
(no DB reads for movement/aggro) and is wrapped so one raised tick can never
stall the loop. Player input is handled on the WS coroutine, not here.

See ARCHITECTURE.md and docs/handoff-02-phase1-tiled-combat-slice.md §5.
"""
import asyncio
from typing import Optional, Set

from database import SessionLocal
import services
import combat
import smack_talk
from websocket_manager import manager
from world import world
from config import COMBAT_TICK_SECONDS

TICK_SECONDS = 15
NPC_REGEN_PER_TICK = 1

_task: Optional[asyncio.Task] = None
_combat_task: Optional[asyncio.Task] = None
# Mobs currently chasing a player — so "aggro acquired" chatter fires once on
# acquisition, not every tick.
_aggroed: Set[int] = set()


async def _tick_once() -> None:
    """One world tick: regenerate damaged, living, in-room NPCs."""
    db = SessionLocal()
    try:
        npc_ids = {npc_id for room in world.rooms.values() for npc_id in room.npc_ids}
        changed = False
        for npc_id in npc_ids:
            npc = services.NpcService.get_npc(db, npc_id)
            if npc and 0 < npc.health < npc.max_health:
                npc.health = min(npc.max_health, npc.health + NPC_REGEN_PER_TICK)
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


async def _combat_tick_once() -> None:
    """One fast tick of mob AI across all occupied rooms (DB-free movement)."""
    for room_id, node in list(world.rooms.items()):
        if not node.player_pos:          # no online players standing in this zone
            continue
        for npc_id in world.hostile_mobs(room_id):
            mpos = world.position_of("npc", room_id, npc_id)
            if mpos is None:
                continue
            meta = node.npc_meta.get(npc_id, {})
            radius = meta.get("aggro_radius", 6)
            target = world.nearest_player_within(room_id, mpos, radius) if radius else None
            if target is None:
                _aggroed.discard(npc_id)
                continue
            pid, ppos = target
            if npc_id not in _aggroed:    # just acquired this player
                _aggroed.add(npc_id)
                asyncio.create_task(smack_talk.maybe_smack(
                    npc_id, room_id, meta.get("name", "?"), "aggro", glyph=meta.get("glyph")))

            if world.chebyshev(mpos, ppos) <= 1:
                await combat.resolve_mob_attack(npc_id, room_id, pid)
                continue
            # Step toward the player; bump = attack. Try the greedy axis, then
            # fall back to the other if blocked.
            for delta in world.step_candidates(mpos, ppos):
                res = world.try_step("npc", npc_id, room_id, *delta)
                if res.kind == "ATTACK" and res.target_id == pid:
                    await combat.resolve_mob_attack(npc_id, room_id, pid)
                    break
                if res.kind == "MOVED":
                    await manager.broadcast_to_room(
                        room_id, {"event": "entity_moved", "id": npc_id, "x": res.x, "y": res.y})
                    break


async def _loop() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            await _tick_once()
        except Exception as e:  # never let the loop die on a transient error
            print(f"game tick error: {e}")


async def _combat_loop() -> None:
    while True:
        await asyncio.sleep(COMBAT_TICK_SECONDS)
        try:
            await _combat_tick_once()
        except Exception as e:  # one bad tick must not stall mob AI
            print(f"combat tick error: {e}")


def start() -> None:
    """Start the background ticks (idempotent)."""
    global _task, _combat_task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
    if _combat_task is None or _combat_task.done():
        _combat_task = asyncio.create_task(_combat_loop())


def stop() -> None:
    """Stop the background ticks."""
    global _task, _combat_task
    for t in (_task, _combat_task):
        if t is not None:
            t.cancel()
    _task = None
    _combat_task = None
    _aggroed.clear()
