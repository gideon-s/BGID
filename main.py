"""
Main FastAPI application for the RPG Game API
"""
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio
import models
import schemas
from database import engine, get_db
from websocket_manager import manager
from chat_system import chat_manager, ChatType
from chat_schemas import ChatMessageRequest, ChatHistoryRequest, NPCChatRequest
from llm_npcs import BaseLLMNPC, NPCContext, NPCDisposition, NPCStats, NPCRole
from deepseek_integration import initialize_deepseek_npcs, cleanup_deepseek_npcs
from services import PlayerService, RoomService, ItemService, NpcService, GameActionService
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
    try:
        await initialize_deepseek_npcs()
        print("🚀 DeepSeek NPC system initialized successfully!")
    except Exception as e:
        print(f"⚠️  Warning: Could not initialize DeepSeek NPC system: {e}")
        print("   NPCs will use rule-based responses instead.")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up services on shutdown"""
    try:
        await cleanup_deepseek_npcs()
        print("🧹 DeepSeek NPC system cleaned up successfully!")
    except Exception as e:
        print(f"⚠️  Warning: Error cleaning up DeepSeek NPC system: {e}")

# ---------- Root Endpoint ----------
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Welcome to the RPG Game API!",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "players": "/players/",
            "rooms": "/rooms/",
            "items": "/items/",
            "npcs": "/npcs/",
            "actions": "/action",
            "chat": "/chat/",
            "websocket": "/ws/{player_id}"
        }
    }

# ---------- WebSocket Endpoint ----------
@app.websocket("/ws/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: int):
    """WebSocket endpoint for real-time multiplayer communication"""
    # Verify player exists
    db = next(get_db())
    player = PlayerService.get_player(db, player_id)
    if not player:
        await websocket.close(code=4004, reason="Player not found")
        return
    
    # Connect the player
    await manager.connect(websocket, player_id)
    
    # Subscribe to their current room
    if player.room_id:
        manager.subscribe_to_room(player_id, player.room_id)
        
        # Notify others that player joined
        player_info = {
            "id": player.id,
            "name": player.name,
            "level": player.level
        }
        await manager.broadcast_player_joined(player_id, player.room_id, player_info)
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            
            # For now, just echo back (we can expand this later)
            await manager.send_personal_message(player_id, {
                "type": "echo",
                "message": f"Received: {data}"
            })
            
    except WebSocketDisconnect:
        # Player disconnected
        if player.room_id:
            # Notify others that player left
            player_info = {
                "id": player.id,
                "name": player.name,
                "level": player.level
            }
            await manager.broadcast_player_left(player_id, player.room_id, player_info)
        
        manager.disconnect(player_id)
        db.close()

# ---------- Player Endpoints ----------
@app.get("/players/", response_model=schemas.PlayersListResponse, tags=["Players"])
def get_players(
    skip: int = Query(0, ge=0, description="Number of players to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of players to return")
):
    """Get list of all players with pagination"""
    db = next(get_db())
    players = PlayerService.get_players(db, skip=skip, limit=limit)
    
    return schemas.PlayersListResponse(
        items=players,
        total_count=len(players),
        page=skip // limit + 1,
        page_size=limit
    )

@app.get("/players/{player_id}", response_model=schemas.PlayerOut, tags=["Players"])
def get_player(player_id: int):
    """Get a specific player by ID"""
    db = next(get_db())
    player = PlayerService.get_player(db, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return player

@app.post("/players/", response_model=schemas.PlayerOut, tags=["Players"])
def create_player(player: schemas.PlayerCreate):
    """Create a new player"""
    db = next(get_db())
    return PlayerService.create_player(db, player)

@app.put("/players/{player_id}", response_model=schemas.PlayerOut, tags=["Players"])
def update_player(player_id: int, player_update: schemas.PlayerUpdate):
    """Update an existing player"""
    db = next(get_db())
    return PlayerService.update_player(db, player_id, player_update)

@app.delete("/players/{player_id}", tags=["Players"])
def delete_player(player_id: int):
    """Delete a player"""
    db = next(get_db())
    PlayerService.delete_player(db, player_id)
    return {"message": "Player deleted successfully"}

@app.get("/players/{player_id}/sheet", response_model=schemas.PlayerSheet, tags=["Players"])
def get_player_sheet(player_id: int):
    """Get comprehensive player character sheet"""
    db = next(get_db())
    return PlayerService.get_player_sheet(db, player_id)

# ---------- Room Endpoints ----------
@app.get("/rooms/", response_model=schemas.RoomsListResponse, tags=["Rooms"])
def get_rooms(
    skip: int = Query(0, ge=0, description="Number of rooms to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of rooms to return")
):
    """Get list of all rooms with pagination"""
    db = next(get_db())
    rooms = RoomService.get_rooms(db, skip=skip, limit=limit)
    
    return schemas.RoomsListResponse(
        items=rooms,
        total_count=len(rooms),
        page=skip // limit + 1,
        page_size=limit
    )

@app.get("/rooms/{room_id}", response_model=schemas.RoomOut, tags=["Rooms"])
def get_room(room_id: int):
    """Get a specific room by ID"""
    db = next(get_db())
    room = RoomService.get_room(db, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room

@app.post("/rooms/", response_model=schemas.RoomOut, tags=["Rooms"])
def create_room(room: schemas.RoomCreate):
    """Create a new room"""
    db = next(get_db())
    return RoomService.create_room(db, room)

@app.get("/rooms/{room_id}/state", tags=["Rooms"])
def get_room_state(room_id: int):
    """Get complete room state including players, NPCs, and items"""
    db = next(get_db())
    return RoomService.get_room_state(db, room_id)

# ---------- Item Endpoints ----------
@app.get("/items/", response_model=schemas.ItemsListResponse, tags=["Items"])
def get_items(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return")
):
    """Get list of all items with pagination"""
    db = next(get_db())
    items = ItemService.get_items(db, skip=skip, limit=limit)
    
    return schemas.ItemsListResponse(
        items=items,
        total_count=len(items),
        page=skip // limit + 1,
        page_size=limit
    )

@app.get("/items/{item_id}", response_model=schemas.ItemOut, tags=["Items"])
def get_item(item_id: int):
    """Get a specific item by ID"""
    db = next(get_db())
    item = ItemService.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.post("/items/", response_model=schemas.ItemOut, tags=["Items"])
def create_item(item: schemas.ItemCreate):
    """Create a new item"""
    db = next(get_db())
    return ItemService.create_item(db, item)

# ---------- NPC Endpoints ----------
@app.get("/npcs/", response_model=schemas.NpcsListResponse, tags=["NPCs"])
def get_npcs(
    skip: int = Query(0, ge=0, description="Number of NPCs to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of NPCs to return")
):
    """Get list of all NPCs with pagination"""
    db = next(get_db())
    npcs = NpcService.get_npcs(db, skip=skip, limit=limit)
    
    return schemas.NpcsListResponse(
        items=npcs,
        total_count=len(npcs),
        page=skip // limit + 1,
        page_size=limit
    )

@app.get("/npcs/{npc_id}", response_model=schemas.NpcOut, tags=["NPCs"])
def get_npc(npc_id: int):
    """Get a specific NPC by ID"""
    db = next(get_db())
    npc = NpcService.get_npc(db, npc_id)
    if not npc:
        raise HTTPException(status_code=404, detail="NPC not found")
    return npc

@app.post("/npcs/", response_model=schemas.NpcOut, tags=["NPCs"])
def create_npc(npc: schemas.NpcCreate):
    """Create a new NPC"""
    db = next(get_db())
    return NpcService.create_npc(db, npc)

@app.get("/npcs/{npc_id}/sheet", response_model=schemas.NpcSheet, tags=["NPCs"])
def get_npc_sheet(npc_id: int):
    """Get comprehensive NPC character sheet"""
    db = next(get_db())
    return NpcService.get_npc_sheet(db, npc_id)

# ---------- Game Action Endpoints ----------
@app.post("/action", response_model=schemas.ActionResponse, tags=["Game Actions"])
def perform_action(action_request: schemas.ActionRequest):
    """Perform a game action"""
    db = next(get_db())
    return GameActionService.perform_action(db, action_request)

# ---------- Chat Endpoints ----------
@app.post("/chat/send", response_model=ChatMessageResponse, tags=["Chat"])
def send_chat_message(message: ChatMessageRequest):
    """Send a chat message"""
    db = next(get_db())
    
    # Create the chat message
    message_obj = chat_manager.create_message(
        db=db,
        sender_id=message.sender_id,
        sender_name=message.sender_name,
        message_type=message.message_type,
        content=message.content,
        target_id=message.target_id,
        metadata=message.metadata
    )
    
    # Convert to response format
    return ChatMessageResponse(
        id=message_obj.id,
        sender_id=message_obj.sender_id,
        sender_name=message_obj.sender_name,
        message_type=message_obj.message_type.value,
        content=message_obj.content,
        timestamp=message_obj.timestamp.isoformat(),
        target_id=message_obj.target_id,
        metadata=message_obj.metadata
    )

@app.get("/chat/history/{chat_type}", tags=["Chat"])
def get_chat_history(
    chat_type: ChatType,
    target_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=1000)
):
    """Get chat history for a specific chat type"""
    db = next(get_db())
    
    messages = chat_manager.get_messages(
        db=db,
        chat_type=chat_type,
        target_id=target_id,
        limit=limit
    )
    
    # Convert messages to response format
    response_messages = []
    for msg in messages:
        response_messages.append(ChatMessageResponse(
            id=msg.id,
            sender_id=msg.sender_id,
            sender_name=msg.sender_name,
            message_type=msg.message_type.value,
            content=msg.content,
            timestamp=msg.timestamp.isoformat(),
            target_id=msg.target_id,
            metadata=msg.metadata
        ))
    
    return {
        "messages": response_messages,
        "total_count": len(messages),
        "chat_type": chat_type,
        "target_id": target_id
    }

# Map stored npc_type strings to NPC roles for the LLM prompt
_NPC_TYPE_TO_ROLE = {
    "merchant": NPCRole.MERCHANT,
    "quest_giver": NPCRole.QUEST_GIVER,
    "combat_mob": NPCRole.COMBAT_MOB,
    "informant": NPCRole.INFORMANT,
    "companion": NPCRole.COMPANION,
    "boss": NPCRole.BOSS,
}

@app.post("/chat/npc", tags=["Chat"])
async def chat_with_npc(request: NPCChatRequest):
    """Chat with an NPC using LLM (DeepSeek) integration.

    Falls back to rule-based responses automatically if DeepSeek is not
    configured/available (handled inside BaseLLMNPC.generate_response).
    """
    db = next(get_db())

    # Get NPC and player
    npc = NpcService.get_npc(db, request.npc_id)
    if not npc:
        raise HTTPException(status_code=404, detail="NPC not found")

    player = PlayerService.get_player(db, request.player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    # Generate NPC response
    try:
        # Build an LLM-capable NPC from the stored record
        role = _NPC_TYPE_TO_ROLE.get(npc.npc_type, NPCRole.INFORMANT)
        disposition = NPCDisposition.FRIENDLY if npc.is_friendly else NPCDisposition.NEUTRAL
        stats = NPCStats(health=npc.health, max_health=npc.max_health)
        llm_npc = BaseLLMNPC(
            npc_id=npc.id,
            name=npc.name,
            description=npc.description,
            disposition=disposition,
            role=role,
            stats=stats,
        )

        # Build interaction context from current player/NPC state.
        # (Reputation/gold are not modeled yet, so they default to 0.)
        context = NPCContext(
            player_level=player.level,
            player_reputation=0,
            player_health=player.health,
            player_gold=0,
            room_id=player.room_id,
        )

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
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors"""
    return schemas.ErrorResponse(
        error="Not Found",
        details=f"The requested resource was not found: {request.url.path}"
    )

@app.exception_handler(422)
async def validation_error_handler(request, exc):
    """Handle validation errors"""
    return schemas.ErrorResponse(
        error="Validation Error",
        details="The request data is invalid. Please check your input."
    )

@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Handle internal server errors"""
    return schemas.ErrorResponse(
        error="Internal Server Error",
        details="An unexpected error occurred. Please try again later."
    )
