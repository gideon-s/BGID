#!/usr/bin/env python3
"""
Background game loop (tick).

A single asyncio task that fires every TICK_SECONDS. Currently it does slow
out-of-combat regeneration for living, in-room NPCs — a small, safe demonstration
of the loop. Defeated NPCs (removed from their room) are not regenerated.

Extend `_tick_once` with NPC wandering, aggro, timed events, etc.
See ARCHITECTURE.md (step 4).
"""
import asyncio
from typing import Optional

from database import SessionLocal
import services
from world import world

TICK_SECONDS = 15
NPC_REGEN_PER_TICK = 1

_task: Optional[asyncio.Task] = None


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


async def _loop() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            await _tick_once()
        except Exception as e:  # never let the loop die on a transient error
            print(f"game tick error: {e}")


def start() -> None:
    """Start the background tick (idempotent)."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop() -> None:
    """Stop the background tick."""
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
