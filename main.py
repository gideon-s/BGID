"""
Main FastAPI application for the RPG Game API
"""
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio
import json
import os
import models
import schemas
from database import engine, get_db, SessionLocal
from websocket_manager import manager
from chat_system import chat_manager, ChatType
from world import world
from npc_turns import run_npc_turn, build_llm_npc, build_context
from combat import resolve_player_attack, resolve_pvp_attack
from casting import resolve_cast
import classes
import races
import currency
import shops
import leveling
import potions
import effects
import gear_effects
import features
import spells as spellbook
import skills as skillbook
import services
import game_loop
import time
from config import MOVE_COOLDOWN_SECONDS, DOOR_UNLOCK_SECONDS
from chat_schemas import ChatMessageRequest, ChatHistoryRequest, NPCChatRequest
from llm_npcs import BaseLLMNPC, NPCContext, NPCDisposition, NPCStats, NPCRole
from deepseek_integration import initialize_deepseek_npcs, cleanup_deepseek_npcs
from novita_integration import initialize_novita, cleanup_novita, portrait_manager
import portraits
from services import PlayerService, RoomService, ItemService, NpcService, GameActionService, NpcReactionService, RoomExitService
from dependencies import get_current_user, get_current_admin, authenticate_ws
import auth_api
import auth_service
import rate_limit
from config import HOST, PORT, DEBUG
from utils import log_action
from datetime import datetime
from chat_schemas import ChatMessageResponse

# Create database tables
models.Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(
    title="RPG Game API", 
    description="A FastAPI-based RPG game with SQLite database and WebSocket multiplayer",
    version="1.0.0",
    debug=DEBUG
)

# Auth + character-management routes (/auth/*, /characters/*)
app.include_router(auth_api.router)

# ---------- Startup/Shutdown Events ----------
@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    # Load the authoritative in-memory world from the DB
    try:
        world.load()
        print(f"🌍 World loaded: {len(world.rooms)} rooms")
    except Exception as e:
        print(f"⚠️  Warning: Could not load world state: {e}")

    try:
        await initialize_deepseek_npcs()
        print("🚀 DeepSeek NPC system initialized successfully!")
    except Exception as e:
        print(f"⚠️  Warning: Could not initialize DeepSeek NPC system: {e}")
        print("   NPCs will use rule-based responses instead.")

    # Portrait generation (Phase 5). Dark by default until NOVITA_API_KEY is set;
    # a missing key just leaves the manager disabled (callers fall back to glyphs).
    portraits.ensure_portrait_dir()
    try:
        await initialize_novita()
    except Exception as e:
        print(f"⚠️  Warning: Could not initialize Novita portraits: {e}")
        print("   Portraits will fall back to emoji glyphs.")

    # Start the background tick loops (slow regen + fast mob-AI combat tick)
    game_loop.start()
    print(f"⏱️  Game loops started (regen {game_loop.TICK_SECONDS}s, "
          f"combat {game_loop.COMBAT_TICK_SECONDS}s)")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up services on shutdown"""
    game_loop.stop()
    try:
        await cleanup_deepseek_npcs()
        print("🧹 DeepSeek NPC system cleaned up successfully!")
    except Exception as e:
        print(f"⚠️  Warning: Error cleaning up DeepSeek NPC system: {e}")
    try:
        await cleanup_novita()
    except Exception as e:
        print(f"⚠️  Warning: Error cleaning up Novita portraits: {e}")

# ---------- Web Client + Root ----------
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
@app.get("/play", include_in_schema=False)
async def root():
    """Serve the browser game client (falls back to API info if absent).

    In production nginx serves the Black Goat Society landing at `/` and proxies
    everything else here, so players reach the game at `/play`."""
    index = os.path.join(_STATIC_DIR, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return JSONResponse({"message": "BGID API", "docs": "/docs"})

@app.get("/api", tags=["Root"])
async def api_info():
    """API information."""
    return {
        "message": "Welcome to the RPG Game API!",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "register": "/auth/register",
            "login": "/auth/login",
            "me": "/auth/me",
            "characters": "/characters",
            "players": "/players/",
            "rooms": "/rooms/",
            "items": "/items/",
            "npcs": "/npcs/",
            "actions": "/action",
            "chat": "/chat/",
            "state": "/state/{player_id}",
            "websocket": "/ws/{player_id}?token=<access_token>",
        },
    }

# ---------- WebSocket Endpoint ----------
# Per-player movement cooldown (monotonic timestamp of last accepted step).
# Single worker, in-memory — same authority model as WorldState.
_last_move: dict[int, float] = {}
# The only legal move deltas: one tile at a time, orthogonal OR diagonal (the 8
# neighbours). Diagonals only require the destination tile to be open — corner
# cutting past a wall is allowed (lenient roguelike movement).
_STEPS = {(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - {(0, 0)}


def _player_spawn_fields(player_id: int, room_id: int) -> dict:
    """glyph + portrait + (x, y) for a player's entity_spawned event."""
    pos = world.position_of("player", room_id, player_id) or world.rooms[room_id].spawn
    db = SessionLocal()
    try:
        player = PlayerService.get_player(db, player_id)
        glyph = (player.glyph if player else None) or "🧙"
        portrait_url = player.portrait_url if player else None
        token_url = player.token_url if player else None
    finally:
        db.close()
    return {"glyph": glyph, "portrait_url": portrait_url, "token_url": token_url,
            "x": pos[0], "y": pos[1]}


def _kick_portraits(room_id: int, player_id: Optional[int] = None) -> None:
    """Fire-and-forget portrait generation for the viewer + NPCs in a room.

    No-op when portraits are disabled (NOVITA_API_KEY unset), so the common
    case never touches the DB. ensure_portrait itself is generate-once + cached,
    so repeated calls are cheap and idempotent.
    """
    if not portrait_manager.is_enabled():
        return
    if player_id is not None:
        portraits.ensure_portrait("player", player_id, room_id)
    node = world.rooms.get(room_id)
    if node:
        for nid in list(node.npc_ids):
            portraits.ensure_portrait("npc", nid, room_id)


def _return_held_exit_keys(player_id: int) -> list:
    """Return any shared door-keys this player carries to their home floor, so a
    key can't be hoarded across a logout. Returns [(room_id, item_dropped_ev)]."""
    key_ids = world.exit_key_ids()
    if not key_ids:
        return []
    events = []
    db = SessionLocal()
    try:
        held = (db.query(models.Item)
                .filter(models.Item.player_id == player_id, models.Item.id.in_(key_ids))
                .all())
        for item in held:
            home = world.key_home.get(item.id)
            if home is None:
                continue
            rid, hx, hy = home
            item.player_id = None
            item.room_id, item.tile_x, item.tile_y, item.equipped = rid, hx, hy, False
            db.commit()
            glyph = item.glyph or "🔑"
            world.add_ground_item(rid, item.id, hx, hy, item.name, glyph, item.item_type)
            events.append((rid, {"event": "item_dropped", "id": item.id, "name": item.name,
                                 "glyph": glyph, "token_url": item.token_url, "x": hx, "y": hy}))
    finally:
        db.close()
    return events


def _kick_tokens(room_id: int, player_id: Optional[int] = None) -> None:
    """Fire-and-forget overhead-token generation for everything on the map in a
    room: the viewer, every NPC, and every ground item. No-op when disabled."""
    if not portrait_manager.is_enabled():
        return
    if player_id is not None:
        portraits.ensure_token("player", player_id, room_id)
    node = world.rooms.get(room_id)
    if node:
        for nid in list(node.npc_ids):
            portraits.ensure_token("npc", nid, room_id)
        for iid in list(node.item_ids):
            portraits.ensure_token("item", iid, room_id)


def _inventory_payload(player_id: int) -> dict:
    """The player's carried items as an `inventory` event payload (Phase 3)."""
    db = SessionLocal()
    try:
        items = [
            {"id": i.id, "name": i.name, "glyph": i.glyph or "📦",
             "type": i.item_type, "equip_slot": i.equip_slot, "equipped": i.equipped,
             "value": i.value or 0,
             "attack_bonus": i.attack_bonus, "defense_bonus": i.defense_bonus,
             "damage_bonus": i.damage_bonus}
            for i in ItemService.inventory_of(db, player_id)
        ]
    finally:
        db.close()
    return {"event": "inventory", "items": items}


async def _send_inventory(player_id: int) -> None:
    await manager.send_personal_message(player_id, _inventory_payload(player_id))


def _shop_payload(player_id: int, vendor_id: int, vendor_name: str, npc_type: str) -> dict:
    """A vendor's stock + the player's sellable items + their coin balance."""
    db = SessionLocal()
    try:
        player = PlayerService.get_player(db, player_id)
        coins = (player.coins or 0) if player else 0
        sell = [{"id": it.id, "name": it.name, "glyph": it.glyph or "📦",
                 "type": it.item_type, "price": it.value}
                for it in ItemService.inventory_of(db, player_id)
                if not it.equipped and (it.value or 0) > 0
                and it.item_type not in ("coins", "chest")]
    finally:
        db.close()
    buy = [{"sku": g["sku"], "name": g["name"], "glyph": g.get("glyph", "📦"),
            "type": g["item_type"], "slot": g.get("equip_slot"), "price": g["price"]}
           for g in shops.stock_for(npc_type)]
    return {"event": "shop", "vendor_id": vendor_id, "vendor": vendor_name,
            "coins": coins, "buy": buy, "sell": sell}


def _vendor_in_room(room_id: int, npc_id):
    """Return (npc_row-fields) if npc_id is a vendor NPC in the room, else None.
    Yields a tiny dict {id, name, type} so callers don't hold a DB row."""
    node = world.rooms.get(room_id)
    if node is None or npc_id is None or int(npc_id) not in node.npc_ids:
        return None
    db = SessionLocal()
    try:
        npc = NpcService.get_npc(db, int(npc_id))
        if npc is None or not shops.is_vendor(npc.npc_type):
            return None
        return {"id": npc.id, "name": npc.name, "type": npc.npc_type}
    finally:
        db.close()


def _spellbook_payload(player_id: int) -> dict:
    """The player's known spells (from their class) as a `spellbook` event."""
    db = SessionLocal()
    try:
        player = PlayerService.get_player(db, player_id)
        class_id = player.char_class if player else classes.DEFAULT_CLASS
    finally:
        db.close()
    known = [spellbook.spell_summary(sid) for sid in classes.spell_ids_for(class_id)]
    return {"event": "spellbook", "char_class": class_id,
            "spells": [s for s in known if s]}


def _sheet_payload(player_id: int) -> dict:
    """Full character-sheet snapshot (abilities, skills, class/gender/level,
    bars, and worn equipment by slot) as a `character_sheet` event."""
    db = SessionLocal()
    try:
        p = PlayerService.get_player(db, player_id)
        if p is None:
            return {"event": "character_sheet"}
        cdef = classes.get_class(p.char_class)
        try:
            stored_skills = json.loads(p.skills or "{}")
        except (json.JSONDecodeError, TypeError):
            stored_skills = {}
        abilities = {a: getattr(p, a if a != "int" else "intel")
                     for a in ("str", "dex", "con", "intel", "wis", "cha")}
        mods = {a: p.ability_mod(a) for a in abilities}
        # Worn gear keyed by slot (body-part paperdoll + weapon/ring/amulet).
        equipment = {}
        for it in ItemService.inventory_of(db, player_id):
            if it.equipped and it.equip_slot:
                equipment.setdefault(it.equip_slot, []).append(
                    {"id": it.id, "name": it.name, "glyph": it.glyph or "📦"})
        return {
            "event": "character_sheet",
            "name": p.name, "char_class": p.char_class,
            "portrait_url": p.portrait_url,
            "class_name": cdef.get("name", p.char_class.title()),
            "race": p.race or "human",
            "race_name": races.get_race(p.race).get("name", (p.race or "human").title()),
            "gender": p.gender or "none", "appearance": p.appearance or "",
            "coins": p.coins or 0,
            "level": p.level, "experience": p.experience,
            "xp_into": leveling.progress(p.experience)[1],
            "xp_needed": leveling.progress(p.experience)[2],
            "hp": p.health, "max_hp": p.max_health, "mana": p.mana, "max_mana": p.max_mana,
            "abilities": abilities, "modifiers": mods,
            "skills": skillbook.normalize(stored_skills),
            "equipment": equipment, "slots": services.BODY_SLOTS,
        }
    finally:
        db.close()


async def _try_transition(player_id: int, player_name: str, from_room: int, ex: dict) -> None:
    """Move a player to an adjacent zone via a door/stairs (Phase 2). Enforces
    locks, re-places at the destination's arrival tile, and fixes up presence."""
    direction = ex["direction"]
    # A locked door is passable while its shared open window is active; otherwise
    # the player must hold the key — and using it CONSUMES the key and opens the
    # door for everyone for DOOR_UNLOCK_SECONDS (it re-locks + respawns on a tick).
    if ex["is_locked"] and not world.door_is_open(from_room, direction):
        key_id = ex["key_item_id"]
        db = SessionLocal()
        try:
            has_key = ItemService.is_held_by(db, key_id, player_id)
            if has_key:
                ItemService.destroy(db, key_id)          # the key crumbles to dust
        finally:
            db.close()
        if not has_key:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"The way {direction} is locked."})
            return
        world.remove_ground_item(key_id)                 # belt-and-suspenders
        world.open_door(from_room, direction, DOOR_UNLOCK_SECONDS)
        await manager.broadcast_to_room(
            from_room, {"event": "info",
                        "detail": "The Rusty Key crumbles to dust as the lock gives "
                                  "way — the door stands open."})
        await _send_inventory(player_id)                 # the key left their pack
    to_room = ex["to_room_id"]
    if not world.move_player(player_id, to_room):     # room-graph + DB write-through
        await manager.send_personal_message(
            player_id, {"event": "error", "detail": "That way leads nowhere."})
        return
    world.place_player(player_id, to_room, at=world.arrival_tile(to_room, direction))
    manager.unsubscribe_from_room(player_id, from_room)
    manager.subscribe_to_room(player_id, to_room)
    await manager.broadcast_to_room(
        from_room, {"event": "entity_left", "id": player_id, "name": player_name})
    await manager.broadcast_to_room(
        to_room,
        {"event": "entity_spawned", "id": player_id, "kind": "player", "name": player_name,
         **_player_spawn_fields(player_id, to_room)},
        exclude_player=player_id,
    )
    await manager.send_personal_message(
        player_id, {"event": "zone_state", **world.zone_snapshot(to_room, player_id)})
    # Generate portraits + overhead tokens for the destination zone (player,
    # NPCs, ground items) — generate-once + cached, so this is cheap/idempotent.
    _kick_portraits(to_room, player_id)
    _kick_tokens(to_room, player_id)


@app.websocket("/ws/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: int,
                             token: Optional[str] = Query(default=None)):
    """Realtime gameplay channel (authenticated).

    The browser passes its access token as `?token=` (the WS handshake can't
    carry an Authorization header). We resolve the user from the token and
    require that `player_id` is one of *their* characters — otherwise the
    socket is rejected, so nobody can puppet a character they don't own.

    On connect: place the player in the world, subscribe to their room, send a
    room_state snapshot, and announce them to the room. Then dispatch inbound
    commands (look/move/say). See ARCHITECTURE.md for the message protocol.
    """
    # Authenticate the connection and verify character ownership in one session.
    db = next(get_db())
    try:
        user = authenticate_ws(db, token)
        if user is None:
            await websocket.close(code=4401, reason="Authentication required")
            return
        player = PlayerService.get_player(db, player_id)
        if player is None:
            await websocket.close(code=4004, reason="Character not found")
            return
        if player.user_id != user.id:
            await websocket.close(code=4403, reason="Not your character")
            return
        player_name = player.name
        user_id = user.id  # owning account — used to rate-limit LLM `talk`
    finally:
        db.close()

    await manager.connect(websocket, player_id)

    # Place the player into the authoritative world (room membership + DB) and
    # onto the zone's spawn tile (the live tile layer).
    room_id = world.enter_world(player_id)
    if room_id is None:
        await manager.send_personal_message(
            player_id, {"event": "error", "detail": "Could not place you in the world"}
        )
        manager.disconnect(player_id)
        await websocket.close(code=4000, reason="No room")
        return
    world.place_player(player_id, room_id)

    manager.subscribe_to_room(player_id, room_id)
    # Initial tiled-zone snapshot to the joining player (the overview map is
    # fetched lazily via the `map` command when the player opens it).
    await manager.send_personal_message(
        player_id, {"event": "zone_state", **world.zone_snapshot(room_id, player_id)}
    )
    # Re-sync gear effects from worn equipment, then push any active effects
    # (buffs/debuffs surviving a reconnect, plus the just-synced gear) so the UI
    # is in sync.
    pkey = effects.eid("player", player_id)
    gear_effects.sync(player_id)
    if effects.active(pkey):
        await manager.send_personal_message(
            player_id, {"event": "effects", "effects": effects.snapshot(pkey)})
    # The inventory is fetched lazily by the client (an `inventory` command on
    # connect), mirroring `world_map` — so the server-side connect sequence stays
    # stable for tests and reconnection logic.
    # Announce the new arrival to everyone else in the zone (with their tile)
    await manager.broadcast_to_room(
        room_id,
        {"event": "entity_spawned", "id": player_id, "kind": "player",
         "name": player_name, **_player_spawn_fields(player_id, room_id)},
        exclude_player=player_id,
    )
    # Phase 5/6: kick off portrait + overhead-token generation for this player,
    # the NPCs they can see, and the ground items — so art is ready by the time
    # they look. Generate-once + cached; no-op without a key.
    _kick_portraits(room_id, player_id)
    _kick_tokens(room_id, player_id)

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_ws_command(player_id, player_name, user_id, raw)
    except WebSocketDisconnect:
        # A shared door-key returns to its floor so it can't be hoarded offline.
        for rid, drop_ev in _return_held_exit_keys(player_id):
            await manager.broadcast_to_room(rid, drop_ev)
        left_room = world.leave_world(player_id)
        _last_move.pop(player_id, None)
        if left_room is not None:
            await manager.broadcast_to_room(
                left_room,
                {"event": "entity_left", "id": player_id, "name": player_name},
            )
        manager.disconnect(player_id)


async def _handle_ws_command(player_id: int, player_name: str, user_id: int, raw: str):
    """Parse and dispatch a single inbound WebSocket command."""
    try:
        msg = json.loads(raw)
        if not isinstance(msg, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError, TypeError):
        await manager.send_personal_message(
            player_id, {"event": "error", "detail": "Expected a JSON object"}
        )
        return

    cmd = msg.get("cmd")
    room_id = world.room_of(player_id)
    if room_id is None:
        await manager.send_personal_message(
            player_id, {"event": "error", "detail": "You are not in the world"}
        )
        return

    if cmd == "look":
        await manager.send_personal_message(
            player_id, {"event": "zone_state", **world.zone_snapshot(room_id, player_id)}
        )

    elif cmd == "map":
        # Zone-graph for the overview map (fetched when the player opens it).
        await manager.send_personal_message(
            player_id, {"event": "world_map", **world.world_map()}
        )

    elif cmd == "say":
        text = (msg.get("text") or "").strip()
        if not text:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "say requires non-empty 'text'"}
            )
            return
        await manager.broadcast_to_room(
            room_id,
            {"event": "chat", "from": player_name, "player_id": player_id, "text": text},
        )

    elif cmd == "move":
        # Tile movement: one step (orthogonal or diagonal). Server validates via
        # try_step (walls, occupancy, bump-to-attack) + a per-player cooldown.
        try:
            dx, dy = int(msg.get("dx", 0)), int(msg.get("dy", 0))
        except (TypeError, ValueError):
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "move requires integer 'dx'/'dy'"})
            return
        if (dx, dy) not in _STEPS:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "move must be one tile step (dx/dy = -1, 0, or 1)"})
            return
        now = time.monotonic()
        cooldown = MOVE_COOLDOWN_SECONDS * effects.haste_factor(
            effects.eid("player", player_id))   # Haste = faster
        if now - _last_move.get(player_id, 0.0) < cooldown:
            return  # moving too fast — silently drop (client will retry on next keypress)
        _last_move[player_id] = now

        res = world.try_step("player", player_id, room_id, dx, dy)
        if res.kind == "MOVED":
            await manager.broadcast_to_room(
                room_id, {"event": "entity_moved", "id": player_id, "x": res.x, "y": res.y})
            # Stepping onto a door/stairs with an exit moves the player to the
            # adjacent zone (Phase 2).
            ex = world.transition_for_tile(room_id, res.x, res.y)
            if ex:
                await _try_transition(player_id, player_name, room_id, ex)
            else:
                # Stepping onto a trap/hazard tile triggers it (handoff-09 §1).
                await features.on_enter(room_id, "player", player_id, res.x, res.y)
        elif res.kind == "ATTACK" and res.target_kind == "npc":
            await resolve_player_attack(player_id, room_id, res.target_id)
        # PvP is not bump-triggered (intentional only) — see the `attack` command.
        # BLOCKED: walls/occupied — no-op (the wall is its own feedback).

    elif cmd == "talk":
        npc_id = msg.get("npc_id")
        text = (msg.get("text") or "").strip()
        if npc_id is None or not text:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "talk requires 'npc_id' and non-empty 'text'"}
            )
            return
        node = world.rooms.get(room_id)
        if node is None or int(npc_id) not in node.npc_ids:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"No NPC {npc_id} in this room"}
            )
            return
        # Rate-limit LLM conversation per account (DeepSeek cost). Checked before
        # the broadcast so a throttled message neither echoes nor spawns a turn.
        allowed, retry = rate_limit.check_talk(user_id)
        if not allowed:
            wait = int(retry) + 1
            await manager.send_personal_message(
                player_id,
                {"event": "error", "detail": f"You're conversing too quickly — wait {wait}s.",
                 "retry_after": wait},
            )
            return
        # Ensure this NPC has a portrait on the way (generate-once; no-op if
        # disabled or already cached) so the Dialogue window can show it.
        portraits.ensure_portrait("npc", int(npc_id), room_id)
        # Show the room what was asked, then run the NPC's turn without blocking
        await manager.broadcast_to_room(
            room_id,
            {"event": "chat", "from": player_name, "player_id": player_id,
             "text": text, "to_npc": int(npc_id)},
        )
        asyncio.create_task(run_npc_turn(player_id, room_id, int(npc_id), text))

    elif cmd == "attack":
        # Explicit melee on an adjacent target (NPC or another player).
        target_id = msg.get("target_id", msg.get("npc_id"))
        if target_id is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "attack requires 'target_id'"}
            )
            return
        node = world.rooms.get(room_id)
        tid = int(target_id)
        if node is not None and tid in node.npc_ids:
            await resolve_player_attack(player_id, room_id, tid)
        elif node is not None and tid in node.player_pos and tid != player_id:
            await resolve_pvp_attack(player_id, room_id, tid)        # PvP
        else:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"No target {target_id} in this room"}
            )

    elif cmd == "inventory":
        await _send_inventory(player_id)

    elif cmd == "open":
        # Open a chest on/adjacent to the player. Grants the player's class
        # starting gear — once per character (see ItemService.open_chest).
        pos = world.position_of("player", room_id, player_id)
        chest_id = world.chest_near(room_id, *pos) if pos else None
        if chest_id is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "There's no chest within reach."})
            return
        db = SessionLocal()
        try:
            player = PlayerService.get_player(db, player_id)
            chest = ItemService.get_item(db, int(chest_id))
            if player is None or chest is None:
                granted, already = [], False
            else:
                granted, already = ItemService.open_chest(db, player, chest)
            names = [g.name for g in granted]
        finally:
            db.close()
        if already:
            await manager.send_personal_message(
                player_id, {"event": "info", "detail": "The chest is bare — you've already taken your kit."})
        elif names:
            await manager.send_personal_message(
                player_id, {"event": "info",
                            "detail": "You open the Old Chest and find gear meant for you: "
                                      + ", ".join(names) + " — donned and ready."})
            await _send_inventory(player_id)
        else:
            await manager.send_personal_message(
                player_id, {"event": "info", "detail": "The chest is empty."})

    elif cmd == "read":
        # Read a sign on/adjacent to the player (handoff-09 §2).
        pos = world.position_of("player", room_id, player_id)
        feat = world.feature_near(room_id, *pos, kind="sign") if pos else None
        if feat is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "There's nothing to read here."})
            return
        cfg = feat["config"]
        await manager.send_personal_message(player_id, {
            "event": "sign", "id": feat["id"], "x": feat["x"], "y": feat["y"],
            "title": cfg.get("title", "A sign"), "text": cfg.get("text", "")})

    elif cmd == "trigger":
        # Ignite a powder keg (an AoE object) on/adjacent to the player.
        pos = world.position_of("player", room_id, player_id)
        feat = world.feature_near(room_id, *pos, kind="keg") if pos else None
        if feat is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "There's nothing to set off here."})
            return
        await features.trigger_keg(room_id, feat)

    elif cmd == "rest":
        # Recover HP/mana in a tavern, out of combat (handoff-09 §5).
        if world.room_type(room_id) != "tavern":
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "You can only rest in a tavern."})
            return
        if world.living_hostiles(room_id):
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "It's not safe to rest — enemies are near."})
            return
        db = SessionLocal()
        try:
            player = PlayerService.get_player(db, player_id)
            if player is None or player.health <= 0:
                hp = mp = 0
            else:
                hp = player.heal(player.max_health)
                mp = player.restore_mana(player.max_mana)
                vals = (player.health, player.max_health, player.mana, player.max_mana)
        finally:
            db.close()
        if hp == 0 and mp == 0:
            await manager.send_personal_message(
                player_id, {"event": "info", "detail": "You rest a while, already hale and rested."})
            return
        await manager.send_personal_message(player_id, {
            "event": "stats", "player_id": player_id,
            "hp": vals[0], "max_hp": vals[1], "mana": vals[2], "max_mana": vals[3]})
        gained = [f"+{hp} HP"] if hp else []
        if mp:
            gained.append(f"+{mp} MP")
        await manager.send_personal_message(player_id, {
            "event": "info", "detail": f"You rest by the hearth and recover ({', '.join(gained)})."})

    elif cmd == "shop":
        vendor = _vendor_in_room(room_id, msg.get("npc_id"))
        if vendor is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "There's no merchant here."})
            return
        await manager.send_personal_message(
            player_id, _shop_payload(player_id, vendor["id"], vendor["name"], vendor["type"]))

    elif cmd == "buy":
        vendor = _vendor_in_room(room_id, msg.get("npc_id"))
        if vendor is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "There's no merchant here."})
            return
        g = shops.good(vendor["type"], str(msg.get("sku")))
        if g is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "They don't sell that."})
            return
        db = SessionLocal()
        try:
            player = PlayerService.get_player(db, player_id)
            if player is None:
                return
            if (player.coins or 0) < g["price"]:
                await manager.send_personal_message(
                    player_id, {"event": "error",
                                "detail": f"You can't afford the {g['name']} ({currency.short(g['price'])})."})
                return
            balance = ItemService.add_coins(db, player_id, -g["price"])
            item = models.Item(
                name=g["name"], item_type=g["item_type"], glyph=g.get("glyph", "📦"),
                value=g["price"], player_id=player_id, is_movable=True,
                is_equippable=bool(g.get("equip_slot")), equip_slot=g.get("equip_slot"),
                attack_bonus=g.get("attack_bonus", 0), defense_bonus=g.get("defense_bonus", 0),
                damage_bonus=g.get("damage_bonus", 0))
            db.add(item)
            db.commit()
        finally:
            db.close()
        await _send_inventory(player_id)
        await manager.send_personal_message(player_id, {"event": "wallet", "coins": balance})
        await manager.send_personal_message(
            player_id, {"event": "info", "detail": f"You buy the {g['name']} for {currency.short(g['price'])}."})
        await manager.send_personal_message(
            player_id, _shop_payload(player_id, vendor["id"], vendor["name"], vendor["type"]))

    elif cmd == "sell":
        vendor = _vendor_in_room(room_id, msg.get("npc_id"))
        if vendor is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "There's no merchant here."})
            return
        item_id = msg.get("item_id")
        db = SessionLocal()
        try:
            item = ItemService.get_item(db, int(item_id)) if item_id is not None else None
            if (item is None or item.player_id != player_id or item.equipped
                    or (item.value or 0) <= 0 or item.item_type in ("coins", "chest")):
                await manager.send_personal_message(
                    player_id, {"event": "error", "detail": "You can't sell that."})
                return
            price, iname = item.value, item.name
            balance = ItemService.add_coins(db, player_id, price)
            db.delete(item)
            db.commit()
        finally:
            db.close()
        await _send_inventory(player_id)
        await manager.send_personal_message(player_id, {"event": "wallet", "coins": balance})
        await manager.send_personal_message(
            player_id, {"event": "info", "detail": f"You sell the {iname} for {currency.short(price)}."})
        await manager.send_personal_message(
            player_id, _shop_payload(player_id, vendor["id"], vendor["name"], vendor["type"]))

    elif cmd == "pickup":
        # Pick up the named item, or (default) whatever lies on the player's tile.
        item_id = msg.get("item_id")
        if item_id is None:
            pos = world.position_of("player", room_id, player_id)
            item_id = world.grabbable_at(room_id, *pos) if pos else None   # skip a chest
        if item_id is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "Nothing here to pick up."})
            return
        # A coin pile collects straight into the wallet (not the pack).
        db = SessionLocal()
        try:
            peek = ItemService.get_item(db, int(item_id))
            is_coins = peek is not None and peek.item_type == "coins"
        finally:
            db.close()
        if is_coins:
            db = SessionLocal()
            try:
                coin = ItemService.get_item(db, int(item_id))
                amount, cname = coin.value, coin.name
                balance = ItemService.add_coins(db, player_id, amount)
                db.delete(coin)              # the pile is spent into the wallet
                db.commit()
            finally:
                db.close()
            world.remove_ground_item(int(item_id))
            await manager.broadcast_to_room(
                room_id, {"event": "item_taken", "id": int(item_id), "by": player_name})
            await manager.send_personal_message(player_id, {"event": "wallet", "coins": balance})
            await manager.send_personal_message(
                player_id, {"event": "info", "detail": f"You gather {currency.short(amount)}."})
            return
        db = SessionLocal()
        try:
            item = ItemService.pickup(db, player_id, int(item_id))
            name = item.name
        except HTTPException as exc:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": exc.detail})
            return
        finally:
            db.close()
        world.remove_ground_item(int(item_id))
        await manager.broadcast_to_room(
            room_id, {"event": "item_taken", "id": int(item_id), "by": player_name})
        await _send_inventory(player_id)
        await manager.send_personal_message(
            player_id, {"event": "info", "detail": f"You pick up the {name}."})

    elif cmd == "drop":
        item_id = msg.get("item_id")
        if item_id is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "drop requires 'item_id'"})
            return
        pos = world.position_of("player", room_id, player_id)
        if pos is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "You have nowhere to drop it."})
            return
        db = SessionLocal()
        try:
            item = ItemService.drop(db, player_id, int(item_id), pos[0], pos[1])
            name, glyph, itype = item.name, item.glyph or "📦", item.item_type
        except HTTPException as exc:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": exc.detail})
            return
        finally:
            db.close()
        world.add_ground_item(room_id, int(item_id), pos[0], pos[1], name, glyph, itype)
        token_url = portraits.ensure_token("item", int(item_id), room_id)   # generate-once
        await manager.broadcast_to_room(
            room_id, {"event": "item_dropped", "id": int(item_id), "name": name,
                      "glyph": glyph, "token_url": token_url, "x": pos[0], "y": pos[1]})
        await _send_inventory(player_id)

    elif cmd in ("equip", "unequip"):
        item_id = msg.get("item_id")
        if item_id is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"{cmd} requires 'item_id'"})
            return
        db = SessionLocal()
        try:
            fn = ItemService.equip if cmd == "equip" else ItemService.unequip
            fn(db, player_id, int(item_id))
        except HTTPException as exc:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": exc.detail})
            return
        finally:
            db.close()
        # Re-sync gear-granted effects (e.g. Ring of Haste) from the worn set.
        gear_effects.sync(player_id)
        await manager.send_personal_message(
            player_id, {"event": "effects",
                        "effects": effects.snapshot(effects.eid("player", player_id))})
        await _send_inventory(player_id)

    elif cmd == "use":
        # Drink a potion: apply its effect (potions.py) and consume it.
        item_id = msg.get("item_id")
        if item_id is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "use requires 'item_id'"})
            return
        db = SessionLocal()
        err, result = None, None
        try:
            item = ItemService.get_item(db, int(item_id))
            if item is None or item.player_id != player_id:
                err = "You aren't carrying that."
            elif item.item_type != "potion":
                err = "You can't drink that."
            else:
                effect = potions.effect_for(item.name)
                if effect is None:
                    err = "Nothing happens — the draught is inert."
                elif effect["kind"] == "buff":
                    effects.apply_effect(
                        effects.eid("player", player_id),
                        effect["effect"], effect.get("glyph", "✨"),
                        effect.get("duration", 60), atk=effect.get("atk", 0),
                        dmg=effect.get("dmg", 0), defn=effect.get("defn", 0),
                        haste=effect.get("haste", 1.0))
                    iname = item.name
                    db.delete(item)
                    db.commit()
                    result = {"name": iname, "flavor": effect.get("flavor", ""), "buff": True}
                else:
                    player = PlayerService.get_player(db, player_id)
                    res = potions.apply(player, effect)
                    iname = item.name
                    db.delete(item)
                    db.commit()
                    result = {"name": iname, "flavor": effect.get("flavor", ""), "buff": False, **res,
                              "hp": player.health, "max_hp": player.max_health,
                              "mana": player.mana, "max_mana": player.max_mana}
        finally:
            db.close()
        if err:
            await manager.send_personal_message(player_id, {"event": "error", "detail": err})
            return
        await _send_inventory(player_id)
        if result["buff"]:
            await manager.send_personal_message(
                player_id, {"event": "effects",
                            "effects": effects.snapshot(effects.eid("player", player_id))})
            await manager.send_personal_message(
                player_id, {"event": "info", "detail": f"You drink the {result['name']}. {result['flavor']}"})
        else:
            await manager.send_personal_message(player_id, {
                "event": "stats", "player_id": player_id, "hp": result["hp"],
                "max_hp": result["max_hp"], "mana": result["mana"], "max_mana": result["max_mana"]})
            gained = [f"+{result['hp_restored']} HP"] if result["hp_restored"] else []
            if result["mana_restored"]:
                gained.append(f"+{result['mana_restored']} MP")
            tail = f" ({', '.join(gained)})" if gained else ""
            await manager.send_personal_message(player_id, {
                "event": "info", "detail": f"You drink the {result['name']}. {result['flavor']}{tail}"})

    elif cmd == "spells":
        await manager.send_personal_message(player_id, _spellbook_payload(player_id))

    elif cmd == "sheet":
        # First sheet open for a player without art kicks off generation.
        portraits.ensure_portrait("player", player_id, room_id)
        await manager.send_personal_message(player_id, _sheet_payload(player_id))

    elif cmd == "set_appearance":
        # Edit the free-form appearance from the character sheet. On a real
        # change this clears the cached portrait so a fresh one regenerates from
        # the new description; we kick that generation and resend the sheet.
        text = msg.get("text", "")
        if not isinstance(text, str):
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "appearance must be text"})
            return
        db = SessionLocal()
        try:
            changed = auth_service.CharacterService.set_appearance(db, player_id, text)
        finally:
            db.close()
        if changed:
            portraits.ensure_portrait("player", player_id, room_id)
        await manager.send_personal_message(player_id, _sheet_payload(player_id))

    elif cmd == "cast":
        spell_id = msg.get("spell_id")
        if not spell_id:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "cast requires 'spell_id'"})
            return
        tx, ty = msg.get("x"), msg.get("y")
        try:
            tx = int(tx) if tx is not None else None
            ty = int(ty) if ty is not None else None
        except (TypeError, ValueError):
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "cast target x/y must be integers"})
            return
        await resolve_cast(player_id, room_id, str(spell_id), tx, ty)

    else:
        await manager.send_personal_message(
            player_id, {"event": "error", "detail": f"Unknown or unsupported command: {cmd!r}"}
        )

# ---------- Player Endpoints ----------
@app.get("/players/", response_model=schemas.PlayersListResponse, tags=["Players"])
def get_players(
    skip: int = Query(0, ge=0, description="Number of players to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of players to return"),
    db: Session = Depends(get_db),
):
    """Get list of all players with pagination"""
    players = PlayerService.get_players(db, skip=skip, limit=limit)
    
    return schemas.PlayersListResponse(
        items=players,
        total_count=len(players),
        page=skip // limit + 1,
        page_size=limit
    )

@app.get("/players/{player_id}", response_model=schemas.PlayerOut, tags=["Players"])
def get_player(player_id: int, db: Session = Depends(get_db)):
    """Get a specific player by ID"""
    player = PlayerService.get_player(db, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return player

@app.post("/players/", response_model=schemas.PlayerOut, tags=["Players"])
def create_player(player: schemas.PlayerCreate, db: Session = Depends(get_db),
                  _admin: models.User = Depends(get_current_admin)):
    """Create a new player (admin). Players normally use POST /characters."""
    return PlayerService.create_player(db, player)

@app.put("/players/{player_id}", response_model=schemas.PlayerOut, tags=["Players"])
def update_player(player_id: int, player_update: schemas.PlayerUpdate, db: Session = Depends(get_db),
                  _admin: models.User = Depends(get_current_admin)):
    """Update an existing player (admin)."""
    return PlayerService.update_player(db, player_id, player_update)

@app.delete("/players/{player_id}", tags=["Players"])
def delete_player(player_id: int, db: Session = Depends(get_db),
                  _admin: models.User = Depends(get_current_admin)):
    """Delete a player (admin). Players delete their own via DELETE /characters/{id}."""
    PlayerService.delete_player(db, player_id)
    return {"message": "Player deleted successfully"}

@app.get("/players/{player_id}/sheet", response_model=schemas.PlayerSheet, tags=["Players"])
def get_player_sheet(player_id: int, db: Session = Depends(get_db)):
    """Get comprehensive player character sheet"""
    return PlayerService.get_player_sheet(db, player_id)

@app.get("/state/{player_id}", tags=["Players"])
def get_player_state(player_id: int, db: Session = Depends(get_db)):
    """Player-centric world state (current room, who/what is here, inventory)."""
    return PlayerService.get_player_state(db, player_id)

# ---------- Room Endpoints ----------
@app.get("/rooms/", response_model=schemas.RoomsListResponse, tags=["Rooms"])
def get_rooms(
    skip: int = Query(0, ge=0, description="Number of rooms to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of rooms to return"),
    db: Session = Depends(get_db),
):
    """Get list of all rooms with pagination"""
    rooms = RoomService.get_rooms(db, skip=skip, limit=limit)
    
    return schemas.RoomsListResponse(
        items=rooms,
        total_count=len(rooms),
        page=skip // limit + 1,
        page_size=limit
    )

@app.get("/rooms/{room_id}", response_model=schemas.RoomOut, tags=["Rooms"])
def get_room(room_id: int, db: Session = Depends(get_db)):
    """Get a specific room by ID"""
    room = RoomService.get_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room

@app.post("/rooms/", response_model=schemas.RoomOut, tags=["Rooms"])
def create_room(room: schemas.RoomCreate, db: Session = Depends(get_db),
                _admin: models.User = Depends(get_current_admin)):
    """Create a new room (admin)."""
    return RoomService.create_room(db, room)

@app.get("/rooms/{room_id}/state", tags=["Rooms"])
def get_room_state(room_id: int, db: Session = Depends(get_db)):
    """Get complete room state including players, NPCs, and items"""
    return RoomService.get_room_state(db, room_id)

@app.get("/rooms/{room_id}/exits", response_model=List[schemas.RoomExitOut], tags=["Rooms"])
def get_room_exits(room_id: int, db: Session = Depends(get_db)):
    """List the exits leading out of a room."""
    return RoomExitService.get_exits(db, room_id)

@app.post("/rooms/{room_id}/exits", response_model=schemas.RoomExitOut, tags=["Rooms"])
def create_room_exit(room_id: int, data: schemas.RoomExitCreate, db: Session = Depends(get_db),
                     _admin: models.User = Depends(get_current_admin)):
    """Create an exit out of a room (admin). Auto-creates the reverse exit
    unless bidirectional=false. Refreshes the live world map."""
    exit_row = RoomExitService.create_exit(db, room_id, data)
    world.reload()
    return exit_row

@app.delete("/rooms/{room_id}/exits/{direction}", tags=["Rooms"])
def delete_room_exit(room_id: int, direction: str, bidirectional: bool = False,
                     db: Session = Depends(get_db),
                     _admin: models.User = Depends(get_current_admin)):
    """Delete an exit (admin; optionally its reverse too). Refreshes the live world map."""
    RoomExitService.delete_exit(db, room_id, direction, bidirectional=bidirectional)
    world.reload()
    return {"message": f"Exit '{direction}' removed from room {room_id}"}

# ---------- Item Endpoints ----------
@app.get("/items/", response_model=schemas.ItemsListResponse, tags=["Items"])
def get_items(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return"),
    db: Session = Depends(get_db),
):
    """Get list of all items with pagination"""
    items = ItemService.get_items(db, skip=skip, limit=limit)
    
    return schemas.ItemsListResponse(
        items=items,
        total_count=len(items),
        page=skip // limit + 1,
        page_size=limit
    )

@app.get("/items/{item_id}", response_model=schemas.ItemOut, tags=["Items"])
def get_item(item_id: int, db: Session = Depends(get_db)):
    """Get a specific item by ID"""
    item = ItemService.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.post("/items/", response_model=schemas.ItemOut, tags=["Items"])
def create_item(item: schemas.ItemCreate, db: Session = Depends(get_db),
                _admin: models.User = Depends(get_current_admin)):
    """Create a new item (admin)."""
    return ItemService.create_item(db, item)

# ---------- NPC Endpoints ----------
@app.get("/npcs/", response_model=schemas.NpcsListResponse, tags=["NPCs"])
def get_npcs(
    skip: int = Query(0, ge=0, description="Number of NPCs to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of NPCs to return"),
    db: Session = Depends(get_db),
):
    """Get list of all NPCs with pagination"""
    npcs = NpcService.get_npcs(db, skip=skip, limit=limit)
    
    return schemas.NpcsListResponse(
        items=npcs,
        total_count=len(npcs),
        page=skip // limit + 1,
        page_size=limit
    )

@app.get("/npcs/{npc_id}", response_model=schemas.NpcOut, tags=["NPCs"])
def get_npc(npc_id: int, db: Session = Depends(get_db)):
    """Get a specific NPC by ID"""
    npc = NpcService.get_npc(db, npc_id)
    if not npc:
        raise HTTPException(status_code=404, detail="NPC not found")
    return npc

@app.post("/npcs/", response_model=schemas.NpcOut, tags=["NPCs"])
def create_npc(npc: schemas.NpcCreate, db: Session = Depends(get_db),
               _admin: models.User = Depends(get_current_admin)):
    """Create a new NPC (admin)."""
    return NpcService.create_npc(db, npc)

@app.get("/npcs/{npc_id}/sheet", response_model=schemas.NpcSheet, tags=["NPCs"])
def get_npc_sheet(npc_id: int, db: Session = Depends(get_db)):
    """Get comprehensive NPC character sheet"""
    return NpcService.get_npc_sheet(db, npc_id)

@app.get("/npcs/{npc_id}/reaction/{player_id}", response_model=schemas.NpcReactionOut, tags=["NPCs"])
def get_npc_reaction(npc_id: int, player_id: int, db: Session = Depends(get_db)):
    """Get an NPC's reaction toward a player (neutral/zero if none recorded yet)."""
    return NpcReactionService.get_or_create_reaction(db, npc_id, player_id)

@app.put("/npcs/{npc_id}/reaction/{player_id}", response_model=schemas.NpcReactionOut, tags=["NPCs"])
def update_npc_reaction(npc_id: int, player_id: int, data: schemas.NpcReactionUpdate, db: Session = Depends(get_db),
                        _admin: models.User = Depends(get_current_admin)):
    """Update an NPC's reaction values toward a player (admin; creates the row if absent)."""
    return NpcReactionService.update_reaction(db, npc_id, player_id, data)

# ---------- Game Action Endpoints ----------
@app.post("/action", response_model=schemas.ActionResponse, tags=["Game Actions"])
def perform_action(action_request: schemas.ActionRequest, db: Session = Depends(get_db),
                   current_user: models.User = Depends(get_current_user)):
    """Perform a game action as one of your own characters."""
    auth_service.CharacterService.owned_or_404(db, current_user, action_request.player_id)
    return GameActionService.perform_action(db, action_request)

# ---------- Chat Endpoints ----------
@app.post("/chat/send", response_model=ChatMessageResponse, tags=["Chat"])
def send_chat_message(message: ChatMessageRequest, db: Session = Depends(get_db),
                      current_user: models.User = Depends(get_current_user)):
    """Send a chat message as one of your own characters."""
    auth_service.CharacterService.owned_or_404(db, current_user, message.sender_id)

    # Resolve the sender's display name from the DB (request only carries sender_id)
    sender = PlayerService.get_player(db, message.sender_id)
    sender_name = sender.name if sender else f"Player {message.sender_id}"

    # Create the chat message via the in-memory ChatManager
    message_obj = chat_manager.create_message(
        sender_id=message.sender_id,
        sender_name=sender_name,
        message_type=message.message_type,
        content=message.content,
        target_id=message.target_id,
    )

    # Convert to response format
    return ChatMessageResponse(
        id=message_obj.id,
        sender_id=message_obj.sender_id,
        sender_name=message_obj.sender_name,
        message_type=message_obj.message_type,
        content=message_obj.content,
        timestamp=message_obj.timestamp,
        target_id=message_obj.target_id,
        metadata=message_obj.metadata,
    )

@app.get("/chat/history/{chat_type}", tags=["Chat"])
def get_chat_history(
    chat_type: ChatType,
    target_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=1000)
):
    """Get chat history for a specific chat type"""
    # Dispatch to the appropriate in-memory store by chat type
    if chat_type == ChatType.GLOBAL:
        messages = chat_manager.get_global_messages(limit)
    elif chat_type == ChatType.ROOM:
        if target_id is None:
            raise HTTPException(status_code=400, detail="target_id (room_id) is required for room history")
        messages = chat_manager.get_room_messages(target_id, limit)
    elif chat_type == ChatType.PRIVATE:
        if target_id is None:
            raise HTTPException(status_code=400, detail="target_id (player_id) is required for private history")
        messages = chat_manager.get_private_messages(target_id, limit)
    else:
        messages = []

    # Convert messages to response format
    response_messages = [
        ChatMessageResponse(
            id=msg.id,
            sender_id=msg.sender_id,
            sender_name=msg.sender_name,
            message_type=msg.message_type,
            content=msg.content,
            timestamp=msg.timestamp,
            target_id=msg.target_id,
            metadata=msg.metadata,
        )
        for msg in messages
    ]

    return {
        "messages": response_messages,
        "total_count": len(response_messages),
        "chat_type": chat_type,
        "target_id": target_id,
    }

@app.post("/chat/npc", tags=["Chat"])
async def chat_with_npc(request: NPCChatRequest, db: Session = Depends(get_db),
                        current_user: models.User = Depends(get_current_user)):
    """Chat with an NPC (DeepSeek-backed) as one of your own characters.

    Falls back to rule-based responses automatically if DeepSeek is not
    configured/available (handled inside BaseLLMNPC.generate_response).
    """
    auth_service.CharacterService.owned_or_404(db, current_user, request.player_id)

    # Rate-limit LLM conversation per account (shared budget with WS `talk`).
    allowed, retry = rate_limit.check_talk(current_user.id)
    if not allowed:
        wait = int(retry) + 1
        raise HTTPException(status_code=429,
                            detail=f"You're conversing too quickly — wait {wait}s.",
                            headers={"Retry-After": str(wait)})

    # Get NPC and player
    npc = NpcService.get_npc(db, request.npc_id)
    if not npc:
        raise HTTPException(status_code=404, detail="NPC not found")

    player = PlayerService.get_player(db, request.player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    # Generate NPC response
    try:
        # Build an LLM-capable NPC + context from the stored records
        # (shared with the realtime talk path — see npc_turns.py)
        llm_npc = build_llm_npc(npc)
        context = build_context(player)

        response = await llm_npc.generate_response(request.message, context)

        return {
            "npc_id": npc.id,
            "npc_name": npc.name,
            "response": response,
            "disposition": llm_npc.get_disposition_towards_player(context).value,
            "should_attack": llm_npc.should_attack_player(context),
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating NPC response: {str(e)}")

# ---------- Health Check Endpoint ----------
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": "connected",
            "websocket_manager": "active",
            "chat_system": "active"
        }
    }

# ---------- Error Handlers ----------
def _error_response(status_code: int, error: str, details: str) -> JSONResponse:
    """Build a JSONResponse from the standard ErrorResponse schema.

    Exception handlers must return a Response, not a bare Pydantic model
    (returning the model raised 'ErrorResponse object is not callable' and
    masked every underlying error).
    """
    return JSONResponse(
        status_code=status_code,
        content=schemas.ErrorResponse(error=error, details=details).model_dump(mode="json"),
    )

@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors"""
    return _error_response(
        404, "Not Found",
        f"The requested resource was not found: {request.url.path}",
    )

@app.exception_handler(422)
async def validation_error_handler(request, exc):
    """Handle validation errors"""
    return _error_response(
        422, "Validation Error",
        "The request data is invalid. Please check your input.",
    )

@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Handle internal server errors"""
    return _error_response(
        500, "Internal Server Error",
        "An unexpected error occurred. Please try again later.",
    )
