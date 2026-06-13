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
from combat import run_combat_round
import game_loop
from chat_schemas import ChatMessageRequest, ChatHistoryRequest, NPCChatRequest
from llm_npcs import BaseLLMNPC, NPCContext, NPCDisposition, NPCStats, NPCRole
from deepseek_integration import initialize_deepseek_npcs, cleanup_deepseek_npcs
from services import PlayerService, RoomService, ItemService, NpcService, GameActionService, NpcReactionService, RoomExitService
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

    # Start the background tick loop
    game_loop.start()
    print(f"⏱️  Game loop started (tick every {game_loop.TICK_SECONDS}s)")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up services on shutdown"""
    game_loop.stop()
    try:
        await cleanup_deepseek_npcs()
        print("🧹 DeepSeek NPC system cleaned up successfully!")
    except Exception as e:
        print(f"⚠️  Warning: Error cleaning up DeepSeek NPC system: {e}")

# ---------- Web Client + Root ----------
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
async def root():
    """Serve the browser game client (falls back to API info if absent)."""
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
            "join": "/join",
            "players": "/players/",
            "rooms": "/rooms/",
            "items": "/items/",
            "npcs": "/npcs/",
            "actions": "/action",
            "chat": "/chat/",
            "state": "/state/{player_id}",
            "websocket": "/ws/{player_id}",
        },
    }

@app.post("/join", tags=["Players"])
def join(req: schemas.JoinRequest, db: Session = Depends(get_db)):
    """Join by name — returns the player (creates one in the starting room if new)."""
    player = PlayerService.get_or_create_by_name(db, req.name)
    return {"id": player.id, "name": player.name, "room_id": player.room_id}

# ---------- WebSocket Endpoint ----------
@app.websocket("/ws/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: int):
    """Realtime gameplay channel.

    On connect: place the player in the world, subscribe to their room, send a
    room_state snapshot, and announce them to the room. Then dispatch inbound
    commands (look/move/say). See ARCHITECTURE.md for the message protocol.
    """
    # Verify the player exists (capture the name before closing the session)
    db = next(get_db())
    player = PlayerService.get_player(db, player_id)
    player_name = player.name if player else None
    db.close()
    if not player_name:
        await websocket.close(code=4004, reason="Player not found")
        return

    await manager.connect(websocket, player_id)

    # Place the player into the authoritative world
    room_id = world.enter_world(player_id)
    if room_id is None:
        await manager.send_personal_message(
            player_id, {"event": "error", "detail": "Could not place you in the world"}
        )
        manager.disconnect(player_id)
        await websocket.close(code=4000, reason="No room")
        return

    manager.subscribe_to_room(player_id, room_id)
    # Initial snapshot to the joining player
    await manager.send_personal_message(
        player_id, {"event": "room_state", **world.room_snapshot(room_id)}
    )
    # Announce to everyone else in the room
    await manager.broadcast_to_room(
        room_id,
        {"event": "player_entered", "player_id": player_id, "name": player_name},
        exclude_player=player_id,
    )

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_ws_command(player_id, player_name, raw)
    except WebSocketDisconnect:
        left_room = world.leave_world(player_id)
        if left_room is not None:
            await manager.broadcast_to_room(
                left_room,
                {"event": "player_left", "player_id": player_id, "name": player_name},
            )
        manager.disconnect(player_id)


async def _handle_ws_command(player_id: int, player_name: str, raw: str):
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
            player_id, {"event": "room_state", **world.room_snapshot(room_id)}
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
        # Preferred: move by direction (follows an exit, enforces locks).
        # Fallback: explicit room_id teleport.
        direction = msg.get("dir")
        if direction is not None:
            ex = world.exit_in_direction(room_id, direction)
            if ex is None:
                await manager.send_personal_message(
                    player_id, {"event": "error", "detail": f"You can't go {direction} from here."}
                )
                return
            if ex["is_locked"]:
                db = SessionLocal()
                try:
                    has_key = ItemService.is_held_by(db, ex["key_item_id"], player_id)
                finally:
                    db.close()
                if not has_key:
                    await manager.send_personal_message(
                        player_id, {"event": "error", "detail": f"The way {direction} is locked."}
                    )
                    return
            target = ex["to_room_id"]
        else:
            target = msg.get("room_id")
            if target is None:
                await manager.send_personal_message(
                    player_id, {"event": "error", "detail": "move requires 'dir' (or 'room_id')"}
                )
                return
        old_room = room_id
        if not world.move_player(player_id, int(target)):
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"No such room: {target}"}
            )
            return
        new_room = world.room_of(player_id)
        # Move the player's room subscription
        manager.unsubscribe_from_room(player_id, old_room)
        manager.subscribe_to_room(player_id, new_room)
        # Notify both rooms
        await manager.broadcast_to_room(
            old_room, {"event": "player_left", "player_id": player_id, "name": player_name}
        )
        await manager.broadcast_to_room(
            new_room,
            {"event": "player_entered", "player_id": player_id, "name": player_name},
            exclude_player=player_id,
        )
        # Snapshot of the new room to the mover
        await manager.send_personal_message(
            player_id, {"event": "room_state", **world.room_snapshot(new_room)}
        )

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
        # Show the room what was asked, then run the NPC's turn without blocking
        await manager.broadcast_to_room(
            room_id,
            {"event": "chat", "from": player_name, "player_id": player_id,
             "text": text, "to_npc": int(npc_id)},
        )
        asyncio.create_task(run_npc_turn(player_id, room_id, int(npc_id), text))

    elif cmd == "attack":
        npc_id = msg.get("npc_id")
        if npc_id is None:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": "attack requires 'npc_id'"}
            )
            return
        node = world.rooms.get(room_id)
        if node is None or int(npc_id) not in node.npc_ids:
            await manager.send_personal_message(
                player_id, {"event": "error", "detail": f"No NPC {npc_id} in this room"}
            )
            return
        await run_combat_round(player_id, room_id, int(npc_id))

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
def create_player(player: schemas.PlayerCreate, db: Session = Depends(get_db)):
    """Create a new player"""
    return PlayerService.create_player(db, player)

@app.put("/players/{player_id}", response_model=schemas.PlayerOut, tags=["Players"])
def update_player(player_id: int, player_update: schemas.PlayerUpdate, db: Session = Depends(get_db)):
    """Update an existing player"""
    return PlayerService.update_player(db, player_id, player_update)

@app.delete("/players/{player_id}", tags=["Players"])
def delete_player(player_id: int, db: Session = Depends(get_db)):
    """Delete a player"""
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
def create_room(room: schemas.RoomCreate, db: Session = Depends(get_db)):
    """Create a new room"""
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
def create_room_exit(room_id: int, data: schemas.RoomExitCreate, db: Session = Depends(get_db)):
    """Create an exit out of a room (auto-creates the reverse exit unless
    bidirectional=false). Refreshes the live world map."""
    exit_row = RoomExitService.create_exit(db, room_id, data)
    world.reload()
    return exit_row

@app.delete("/rooms/{room_id}/exits/{direction}", tags=["Rooms"])
def delete_room_exit(room_id: int, direction: str, bidirectional: bool = False,
                     db: Session = Depends(get_db)):
    """Delete an exit (optionally its reverse too). Refreshes the live world map."""
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
def create_item(item: schemas.ItemCreate, db: Session = Depends(get_db)):
    """Create a new item"""
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
def create_npc(npc: schemas.NpcCreate, db: Session = Depends(get_db)):
    """Create a new NPC"""
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
def update_npc_reaction(npc_id: int, player_id: int, data: schemas.NpcReactionUpdate, db: Session = Depends(get_db)):
    """Update an NPC's reaction values toward a player (creates the row if absent)."""
    return NpcReactionService.update_reaction(db, npc_id, player_id, data)

# ---------- Game Action Endpoints ----------
@app.post("/action", response_model=schemas.ActionResponse, tags=["Game Actions"])
def perform_action(action_request: schemas.ActionRequest, db: Session = Depends(get_db)):
    """Perform a game action"""
    return GameActionService.perform_action(db, action_request)

# ---------- Chat Endpoints ----------
@app.post("/chat/send", response_model=ChatMessageResponse, tags=["Chat"])
def send_chat_message(message: ChatMessageRequest, db: Session = Depends(get_db)):
    """Send a chat message"""

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
async def chat_with_npc(request: NPCChatRequest, db: Session = Depends(get_db)):
    """Chat with an NPC using LLM (DeepSeek) integration.

    Falls back to rule-based responses automatically if DeepSeek is not
    configured/available (handled inside BaseLLMNPC.generate_response).
    """

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
