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
import random
import time
from typing import Optional, Set

from database import SessionLocal
import services
import combat
import classes
import features
import smack_talk
from websocket_manager import manager
from world import world
from config import (COMBAT_TICK_SECONDS, MOB_MOVE_COOLDOWN_SECONDS,
                    MOB_ATTACK_COOLDOWN_SECONDS, MOB_WANDER_COOLDOWN_SECONDS,
                    MOB_WANDER_LEASH, SPAWNER_TICK_SECONDS)

TICK_SECONDS = 15
NPC_REGEN_PER_TICK = 1

_task: Optional[asyncio.Task] = None
_combat_task: Optional[asyncio.Task] = None
# Mobs currently chasing a player — so "aggro acquired" chatter fires once on
# acquisition, not every tick.
_aggroed: Set[int] = set()
# Per-mob action clocks (monotonic). The tick fires fast; a mob only steps or
# strikes once its own cooldown has elapsed — this is the mob's "speed", kept
# independent of the tick rate. A missing entry means "ready now".
_last_move_at: dict[int, float] = {}
_last_attack_at: dict[int, float] = {}
# Per-mob idle-wander clock (handoff-09 §4).
_last_wander_at: dict[int, float] = {}
# Per-spawner clock (handoff-09 §3) + spawner -> set of live child npc ids.
_last_spawn_at: dict[int, float] = {}
_spawner_children: dict[int, set] = {}


def _ready(table: dict, npc_id: int, cooldown: float, now: float) -> bool:
    last = table.get(npc_id)
    return last is None or (now - last) >= cooldown


async def _tick_once() -> None:
    """One world tick: regenerate damaged, living, in-room NPCs, and restore
    online players' mana per their class's regen rate (Phase 4)."""
    db = SessionLocal()
    mana_updates = []   # (player_id, mana, max_mana) to broadcast after commit
    try:
        npc_ids = {npc_id for room in world.rooms.values() for npc_id in room.npc_ids}
        changed = False
        for npc_id in npc_ids:
            npc = services.NpcService.get_npc(db, npc_id)
            if npc and 0 < npc.health < npc.max_health:
                npc.health = min(npc.max_health, npc.health + NPC_REGEN_PER_TICK)
                changed = True
        for player_id in world.online_players():
            player = services.PlayerService.get_player(db, player_id)
            if player is None or player.health <= 0 or player.mana >= player.max_mana:
                continue
            regen = classes.get_class(player.char_class).get("mana_regen", 0)
            if regen and player.restore_mana(regen):
                changed = True
                mana_updates.append((player_id, player.mana, player.max_mana))
        if changed:
            db.commit()
    finally:
        db.close()
    for player_id, mana, max_mana in mana_updates:
        await manager.send_personal_message(
            player_id, {"event": "stats", "player_id": player_id,
                        "mana": mana, "max_mana": max_mana})


async def _combat_tick_once() -> None:
    """One fast tick of mob AI across all occupied rooms (DB-free movement).

    The tick is frequent, but each mob only acts when its own move/attack
    cooldown has elapsed — so mobs advance at a steady ``MOB_MOVE_COOLDOWN``
    pace and strike at most every ``MOB_ATTACK_COOLDOWN``, regardless of how
    often the tick fires."""
    now = time.monotonic()
    # Drain damage-over-time effects (poison) before AI so a lethal DoT removes
    # the mob this tick.
    await _apply_dots()
    # Monster spawners repopulate their area up to a cap on a timer (§3).
    await _spawn_tick(now)
    # Respawn any mobs whose timer elapsed, then run AI.
    for npc_id in world.due_respawns():
        res = world.respawn_npc(npc_id)
        if res:
            _aggroed.discard(npc_id)
            _last_move_at.pop(npc_id, None)
            _last_attack_at.pop(npc_id, None)
            await manager.broadcast_to_room(
                res["room_id"], {"event": "entity_spawned", **res["entity"]})
    for room_id, node in list(world.rooms.items()):
        if not node.player_pos:          # no online players standing in this zone
            continue
        # Sanctuaries (handoff-09 §5) suppress mob aggro entirely.
        sanctuary = node.is_safe
        for npc_id in list(node.npc_ids):
            mpos = world.position_of("npc", room_id, npc_id)
            if mpos is None:
                continue
            meta = node.npc_meta.get(npc_id, {})
            radius = meta.get("aggro_radius", 6)
            target = None
            if meta.get("hostile") and radius and not sanctuary:
                target = world.nearest_player_within(room_id, mpos, radius)
            if target is None:
                _aggroed.discard(npc_id)
                # Idle: amble around home if this mob wanders (handoff-09 §4).
                if meta.get("wanders") and _ready(_last_wander_at, npc_id,
                                                  MOB_WANDER_COOLDOWN_SECONDS, now):
                    cands = world.wander_candidates(room_id, npc_id, MOB_WANDER_LEASH)
                    if cands:
                        res = world.try_step("npc", npc_id, room_id, *random.choice(cands))
                        if res.kind == "MOVED":
                            _last_wander_at[npc_id] = now
                            await manager.broadcast_to_room(
                                room_id, {"event": "entity_moved", "id": npc_id,
                                          "x": res.x, "y": res.y})
                            await features.on_enter(room_id, "npc", npc_id, res.x, res.y)
                continue
            pid, ppos = target
            if npc_id not in _aggroed:    # just acquired this player
                _aggroed.add(npc_id)
                asyncio.create_task(smack_talk.maybe_smack(
                    npc_id, room_id, meta.get("name", "?"), "aggro", glyph=meta.get("glyph")))

            if world.chebyshev(mpos, ppos) <= 1:
                # In melee range: strike on the attack cooldown, then hold.
                if _ready(_last_attack_at, npc_id, MOB_ATTACK_COOLDOWN_SECONDS, now):
                    _last_attack_at[npc_id] = now
                    await combat.resolve_mob_attack(npc_id, room_id, pid)
                continue
            # Out of reach: advance one tile on the movement cooldown.
            if not _ready(_last_move_at, npc_id, MOB_MOVE_COOLDOWN_SECONDS, now):
                continue
            for delta in world.step_candidates(mpos, ppos):
                res = world.try_step("npc", npc_id, room_id, *delta)
                if res.kind == "MOVED":
                    _last_move_at[npc_id] = now
                    await manager.broadcast_to_room(
                        room_id, {"event": "entity_moved", "id": npc_id, "x": res.x, "y": res.y})
                    await features.on_enter(room_id, "npc", npc_id, res.x, res.y)
                    break
                if res.kind == "ATTACK" and res.target_id == pid:
                    # Reached the player mid-step — resolve as an attack.
                    if _ready(_last_attack_at, npc_id, MOB_ATTACK_COOLDOWN_SECONDS, now):
                        _last_attack_at[npc_id] = now
                        await combat.resolve_mob_attack(npc_id, room_id, pid)
                    break


async def _relock_doors() -> None:
    """Re-lock any door whose shared open window has elapsed, respawning its key
    at its home tile (it 'reforms on the floor'). Runs on the slow tick."""
    due = world.due_door_relocks()
    if not due:
        return
    events = []   # (room_id, item_dropped_event, info_text)
    db = SessionLocal()
    try:
        for from_room, direction in due:
            world.relock_door(from_room, direction)
            node = world.rooms.get(from_room)
            ex = node.exits.get(direction) if node else None
            kid = ex.get("key_item_id") if ex else None
            if not kid:
                continue
            # Respawn at the recorded home, or fall back to the door's room spawn
            # (covers a key that was held — never floored — when the server loaded).
            home = world.key_home.get(kid)
            if home is None and node is not None:
                home = (from_room, node.spawn[0], node.spawn[1])
            if home is None:
                continue
            rid, hx, hy = home
            item = services.ItemService.get_item(db, kid)
            if item is None:
                continue
            item.room_id, item.tile_x, item.tile_y, item.player_id = rid, hx, hy, None
            item.equipped = False
            db.commit()
            glyph = item.glyph or "🔑"
            world.add_ground_item(rid, kid, hx, hy, item.name, glyph, item.item_type)
            events.append((rid,
                {"event": "item_dropped", "id": kid, "name": item.name, "glyph": glyph,
                 "token_url": item.token_url, "x": hx, "y": hy},
                f"With a heavy clunk the {direction} door locks itself again — "
                f"the {item.name.lower()} reforms on the floor."))
    finally:
        db.close()
    for rid, drop_ev, info in events:
        await manager.broadcast_to_room(rid, drop_ev)
        await manager.broadcast_to_room(rid, {"event": "info", "detail": info})


async def _spawn_tick(now: float) -> None:
    """Each spawner feature repopulates its radius up to ``max_active`` on its
    ``interval`` (handoff-09 §3). Spawned mobs use the normal hostile AI + loot/XP;
    dead children free a slot and their DB row is reaped here."""
    for room_id, node in list(world.rooms.items()):
        if not node.player_pos:              # only repopulate where players are
            continue
        for feat in list(node.features.values()):
            if feat["kind"] != "spawner":
                continue
            sid, cfg = feat["id"], feat["config"]
            children = _spawner_children.setdefault(sid, set())
            alive = {cid for cid in children if world.room_of_npc(cid) is not None}
            for dead in children - alive:    # reap rows of children that died
                world.delete_npc(dead)
            _spawner_children[sid] = alive
            max_active = int(cfg.get("max_active", 3))
            interval = float(cfg.get("interval", SPAWNER_TICK_SECONDS))
            if len(alive) >= max_active or not _ready(_last_spawn_at, sid, interval, now):
                continue
            template = cfg.get("template") or {}
            radius = int(cfg.get("radius", 2))
            res = world.spawn_npc_from_template(room_id, template, (feat["x"], feat["y"]), radius)
            if res:
                _last_spawn_at[sid] = now
                alive.add(res["id"])
                await manager.broadcast_to_room(
                    room_id, {"event": "entity_spawned", **res["entity"]})


async def _apply_dots() -> None:
    """Drain damage-over-time effects (poison, etc.) on the fast tick, routing each
    through the shared combat death paths so a lethal tick drops loot + awards XP
    to the effect's source. The DoT cadence is gated by each effect's own clock
    (``effects.due_dots``), so calling this every fast tick is correct."""
    import effects
    for key, amount, sname, sid, stype in effects.due_dots():
        kind, ent_id = effects.split_eid(key)
        by_name = sname or "poison"
        by_id = sid if sid is not None else 0
        by_type = stype or "npc"
        if kind == "npc":
            room_id = world.room_of_npc(ent_id)
            if room_id is not None:
                await combat.damage_npc(room_id, ent_id, amount, by_name, by_id, by_type)
        elif kind == "player":
            room_id = world.room_of(ent_id)
            if room_id is not None:
                await combat.damage_player(room_id, ent_id, amount, by_name, by_id, by_type)


async def _expire_effects() -> None:
    """Drop expired timed effects and tell each affected entity (effects.py).
    Player keys get a personal `effects` refresh + a '… fades' line; NPC keys
    broadcast `entity_effects` to their zone so on-token icons clear."""
    import effects
    expired = effects.sweep()
    for key, names in expired.items():
        kind, ent_id = effects.split_eid(key)
        if kind == "player":
            await manager.send_personal_message(
                ent_id, {"event": "effects", "effects": effects.snapshot(key)})
            await manager.send_personal_message(
                ent_id, {"event": "info", "detail": f"{', '.join(names)} fades."})
        elif kind == "npc":
            room_id = world.room_of_npc(ent_id)
            if room_id is not None:
                await manager.broadcast_to_room(
                    room_id, {"event": "entity_effects", "id": ent_id,
                              "effects": effects.snapshot(key)})


async def _loop() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            await _tick_once()
            await _relock_doors()
            await _expire_effects()
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
    _last_move_at.clear()
    _last_attack_at.clear()
    _last_wander_at.clear()
    _last_spawn_at.clear()
    _spawner_children.clear()
