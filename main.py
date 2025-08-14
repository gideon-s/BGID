from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio
import models
import schemas
from database import engine, get_db
from websocket_manager import manager
from chat_system import chat_manager, ChatType
from chat_schemas import ChatMessageRequest, ChatHistoryRequest, NPCChatRequest
from llm_npcs import BaseLLMNPC, NPCContext, NPCDisposition, NPCStats
from ollama_integration import initialize_ollama_npcs, cleanup_ollama_npcs

# Helper functions for ability scores
def _abilities_of(obj) -> schemas.AbilityScores:
    return schemas.AbilityScores(str=obj.str, dex=obj.dex, con=obj.con, intel=obj.intel, wis=obj.wis, cha=obj.cha)

def _mods_of(obj) -> dict[str, int]:
    return {k: obj.ability_mod(k) for k in ["str","dex","con","intel","wis","cha"]}

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Game API", description="A FastAPI game with SQLite database and WebSocket multiplayer")

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    try:
        # Initialize Ollama NPC manager
        await initialize_ollama_npcs()
        print("🚀 Ollama NPC system initialized successfully!")
    except Exception as e:
        print(f"⚠️  Warning: Could not initialize Ollama NPC system: {e}")
        print("   NPCs will use rule-based responses instead.")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up services on shutdown"""
    try:
        await cleanup_ollama_npcs()
        print("🧹 Ollama NPC system cleaned up successfully!")
    except Exception as e:
        print(f"⚠️  Warning: Error cleaning up Ollama NPC system: {e}")

@app.get("/")
async def root():
    return {"message": "Welcome to the Game API!"}

@app.websocket("/ws/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: int):
    """WebSocket endpoint for real-time multiplayer communication"""
    # Verify player exists
    db = next(get_db())
    player = db.query(models.Player).filter(models.Player.id == player_id).first()
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
            # Wait for messages from the client
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

@app.post("/players/", response_model=schemas.PlayerOut)
def create_player(player: schemas.PlayerCreate, db: Session = Depends(get_db)):
    db_player = models.Player(**player.dict())
    db.add(db_player)
    db.commit()
    db.refresh(db_player)
    return db_player

@app.get("/players/", response_model=List[schemas.Player])
def get_players(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    players = db.query(models.Player).offset(skip).limit(limit).all()
    return players

@app.get("/players/{player_id}", response_model=schemas.Player)
def get_player(player_id: int, db: Session = Depends(get_db)):
    player = db.query(models.Player).filter(models.Player.id == player_id).first()
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return player

@app.post("/rooms/", response_model=schemas.Room)
def create_room(room: schemas.RoomCreate, db: Session = Depends(get_db)):
    db_room = models.Room(**room.dict())
    db.add(db_room)
    db.commit()
    db.refresh(db_room)
    return db_room

@app.get("/rooms/", response_model=List[schemas.Room])
def get_rooms(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    rooms = db.query(models.Room).offset(skip).limit(limit).all()
    return rooms

@app.get("/rooms/{room_id}", response_model=schemas.Room)
def get_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return room

@app.post("/items/", response_model=schemas.Item)
def create_item(item: schemas.ItemCreate, db: Session = Depends(get_db)):
    db_item = models.Item(**item.dict())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.get("/items/", response_model=List[schemas.Item])
def get_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(models.Item).offset(skip).limit(limit).all()
    return items

@app.get("/items/{item_id}", response_model=schemas.Item)
def get_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.post("/npcs/", response_model=schemas.Npc)
def create_npc(npc: schemas.NpcCreate, db: Session = Depends(get_db)):
    db_npc = models.Npc(**npc.dict())
    db.add(db_npc)
    db.commit()
    db.refresh(db_npc)
    return db_npc

@app.get("/npcs/", response_model=List[schemas.Npc])
def get_npcs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    npcs = db.query(models.Npc).offset(skip).limit(limit).all()
    return npcs

@app.get("/npcs/{npc_id}", response_model=schemas.Npc)
def get_npc(npc_id: int, db: Session = Depends(get_db)):
    npc = db.query(models.Npc).filter(models.Npc.id == npc_id).first()
    if npc is None:
        raise HTTPException(status_code=404, detail="NPC not found")
    return npc

@app.get("/players/{player_id}/sheet", response_model=schemas.PlayerSheet)
def get_player_sheet(player_id: int, db: Session = Depends(get_db)):
    p = db.query(models.Player).get(player_id)
    if not p:
        raise HTTPException(404, "Player not found")
    return schemas.PlayerSheet(
        id=p.id, name=p.name, health=p.health, max_health=p.max_health,
        level=p.level, experience=p.experience,
        abilities=_abilities_of(p), modifiers=_mods_of(p),
        location_name=p.room.name if p.room else "Unknown"
    )

@app.get("/npcs/{npc_id}/sheet", response_model=schemas.NpcSheet)
def get_npc_sheet(npc_id: int, db: Session = Depends(get_db)):
    n = db.query(models.Npc).get(npc_id)
    if not n:
        raise HTTPException(404, "NPC not found")
    return schemas.NpcSheet(
        id=n.id, name=n.name, description=n.description, npc_type=n.npc_type,
        combat_enabled=n.combat_enabled, health=n.health, max_health=n.max_health,
        abilities=_abilities_of(n), modifiers=_mods_of(n),
        location_name=n.room.name if n.room else "Unknown"
    )

@app.get("/npcs/{npc_id}/reaction/{player_id}", response_model=schemas.NpcReactionOut)
def get_reaction(npc_id: int, player_id: int, db: Session = Depends(get_db)):
    r = db.query(models.NpcReaction).filter_by(npc_id=npc_id, player_id=player_id).first()
    if not r:
        r = models.NpcReaction(npc_id=npc_id, player_id=player_id)
        db.add(r); db.commit(); db.refresh(r)
    return schemas.NpcReactionOut(
        npc_id=r.npc_id, player_id=r.player_id,
        threat=r.threat, attraction=r.attraction, arousal=r.arousal, aggression=r.aggression
    )

@app.patch("/npcs/{npc_id}/reaction/{player_id}", response_model=schemas.NpcReactionOut)
def update_reaction(npc_id: int, player_id: int, payload: schemas.NpcReactionUpdate, db: Session = Depends(get_db)):
    r = db.query(models.NpcReaction).filter_by(npc_id=npc_id, player_id=player_id).first()
    if not r:
        r = models.NpcReaction(npc_id=npc_id, player_id=player_id)
        db.add(r)
    for k, v in payload.dict(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit(); db.refresh(r)
    return schemas.NpcReactionOut(
        npc_id=r.npc_id, player_id=r.player_id,
        threat=r.threat, attraction=r.attraction, arousal=r.arousal, aggression=r.aggression
    )

@app.post("/action", response_model=schemas.ActionResponse)
def perform_action(action: schemas.ActionRequest, db: Session = Depends(get_db)):
    # Get the player
    player = db.query(models.Player).filter(models.Player.id == action.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Store the old room for broadcasting
    old_room_id = player.room_id
    
    if action.action_type == "move":
        if action.target_type == "room" and action.target_id:
            # Check if room exists
            room = db.query(models.Room).filter(models.Room.id == action.target_id).first()
            if not room:
                raise HTTPException(status_code=404, detail="Room not found")
            # Check if room is accessible (handle case where is_accessible column might not exist yet)
            if hasattr(room, 'is_accessible') and not room.is_accessible:
                raise HTTPException(status_code=400, detail="Room is not accessible")
            
            player.room_id = action.target_id
            db.commit()
            db.refresh(player)
            
            # Broadcast real-time updates
            try:
                # Notify players in the old room that this player left
                if old_room_id:
                    player_info = {"id": player.id, "name": player.name, "level": player.level}
                    # Use asyncio.run_coroutine_threadsafe for proper async execution
                    import asyncio
                    import threading
                    
                    def run_broadcast():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(manager.broadcast_player_left(action.player_id, old_room_id, player_info))
                        finally:
                            loop.close()
                    
                    # Run in a separate thread to avoid blocking
                    threading.Thread(target=run_broadcast, daemon=True).start()
                    manager.unsubscribe_from_room(action.player_id, old_room_id)
                
                # Subscribe to new room and notify players there
                manager.subscribe_to_room(action.player_id, action.target_id)
                player_info = {"id": player.id, "name": player.name, "level": player.level}
                
                def run_join_broadcast():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(manager.broadcast_player_joined(action.player_id, action.target_id, player_info))
                    finally:
                        loop.close()
                
                threading.Thread(target=run_join_broadcast, daemon=True).start()
                
                # Broadcast the move action
                def run_action_broadcast():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(manager.broadcast_player_action(
                            action.player_id, action.target_id, "move", 
                            {"from_room": old_room_id, "to_room": action.target_id, "room_name": room.name}
                        ))
                    finally:
                        loop.close()
                
                threading.Thread(target=run_action_broadcast, daemon=True).start()
                
            except Exception as e:
                print(f"Error broadcasting move action: {e}")
            
            return schemas.ActionResponse(
                success=True,
                message=f"Player {player.name} moved to {room.name}",
                player_state={
                    "id": player.id,
                    "name": player.name,
                    "room_id": player.room_id,
                    "health": player.health,
                    "max_health": player.max_health,
                    "level": player.level,
                    "experience": player.experience
                }
            )
    
    elif action.action_type == "pickup":
        if action.target_type == "item" and action.target_id:
            item = db.query(models.Item).filter(models.Item.id == action.target_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")
            if item.room_id != player.room_id:
                raise HTTPException(status_code=400, detail="Item is not in the same room")
            if item.player_id:
                raise HTTPException(status_code=400, detail="Item is already owned")
            
            item.player_id = player.id
            item.room_id = None
            db.commit()
            db.refresh(item)
            
            return schemas.ActionResponse(
                success=True,
                message=f"Player {player.name} picked up {item.name}",
                player_state={
                    "id": player.id,
                    "name": player.name,
                    "room_id": player.room_id,
                    "health": player.health,
                    "max_health": player.max_health,
                    "level": player.level,
                    "experience": player.experience
                }
            )
    
    elif action.action_type == "drop":
        if action.target_type == "item" and action.target_id:
            item = db.query(models.Item).filter(models.Item.id == action.target_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")
            if item.player_id != player.id:
                raise HTTPException(status_code=400, detail="Item is not owned by player")
            
            item.player_id = None
            item.room_id = player.room_id
            db.commit()
            db.refresh(item)
            
            return schemas.ActionResponse(
                success=True,
                message=f"Player {player.name} dropped {item.name}",
                player_state={
                    "id": player.id,
                    "name": player.name,
                    "room_id": player.room_id,
                    "health": player.health,
                    "max_health": player.max_health,
                    "level": player.level,
                    "experience": player.experience
                }
            )
    
    # Default response for unhandled actions
    return schemas.ActionResponse(
        success=False,
        message=f"Action '{action.action_type}' not implemented or invalid"
    )

@app.get("/state/{player_id}", response_model=schemas.PlayerState)
def get_player_state(player_id: int, db: Session = Depends(get_db)):
    # Get the player
    player = db.query(models.Player).filter(models.Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Get the current room
    current_room = db.query(models.Room).filter(models.Room.id == player.room_id).first()
    if not current_room:
        raise HTTPException(status_code=404, detail="Player's room not found")
    
    # Get player's inventory
    inventory = db.query(models.Item).filter(models.Item.player_id == player_id).all()
    
    # Get items in the room
    items_in_room = db.query(models.Item).filter(
        models.Item.room_id == player.room_id,
        models.Item.player_id.is_(None)
    ).all()
    
    # Get NPCs in the room
    npcs_in_room = db.query(models.Npc).filter(models.Npc.room_id == player.room_id).all()
    
    # Get other players in the room (excluding the current player)
    other_players_in_room = db.query(models.Player).filter(
        models.Player.room_id == player.room_id,
        models.Player.id != player_id
    ).all()
    
    # Convert SQLAlchemy objects to dictionaries for Pydantic validation
    def model_to_dict(model_obj):
        if model_obj is None:
            return None
        if hasattr(model_obj, '__dict__'):
            # Remove SQLAlchemy internal attributes
            return {k: v for k, v in model_obj.__dict__.items() 
                   if not k.startswith('_')}
        return model_obj

    def models_to_dict_list(model_list):
        return [model_to_dict(obj) for obj in model_list]

    return schemas.PlayerState(
        player=model_to_dict(player),
        current_room=model_to_dict(current_room),
        inventory=models_to_dict_list(inventory),
        npcs_in_room=models_to_dict_list(npcs_in_room),
        items_in_room=models_to_dict_list(items_in_room),
        other_players_in_room=models_to_dict_list(other_players_in_room)
    )

# Chat System Endpoints
@app.post("/chat/send", response_model=schemas.ChatMessageResponse)
async def send_chat_message(chat_request: ChatMessageRequest, db: Session = Depends(get_db)):
    """Send a chat message"""
    # Verify sender exists
    sender = db.query(models.Player).filter(models.Player.id == chat_request.sender_id).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")
    
    # Create and store the message
    message = chat_manager.create_message(
        sender_id=chat_request.sender_id,
        sender_name=sender.name,
        message_type=chat_request.message_type,
        content=chat_request.content,
        target_id=chat_request.target_id
    )
    
    # Broadcast to appropriate recipients via WebSocket
    if chat_request.message_type == ChatType.GLOBAL:
        # Broadcast to all connected players
        asyncio.create_task(manager.broadcast_to_all({
            "type": "chat_message",
            "message_type": "global",
            "sender_id": sender.id,
            "sender_name": sender.name,
            "content": chat_request.content,
            "timestamp": message.timestamp.isoformat()
        }))
    
    elif chat_request.message_type == ChatType.ROOM:
        # Broadcast to players in the room
        if chat_request.target_id:
            asyncio.create_task(manager.broadcast_to_room(chat_request.target_id, {
                "type": "chat_message",
                "message_type": "room",
                "sender_id": sender.id,
                "sender_name": sender.name,
                "content": chat_request.content,
                "timestamp": message.timestamp.isoformat(),
                "room_id": chat_request.target_id
            }))
    
    elif chat_request.message_type == ChatType.PRIVATE:
        # Send to specific player
        if chat_request.target_id:
            asyncio.create_task(manager.send_personal_message(chat_request.target_id, {
                "type": "chat_message",
                "message_type": "private",
                "sender_id": sender.id,
                "sender_name": sender.name,
                "content": chat_request.content,
                "timestamp": message.timestamp.isoformat()
            }))
    
    # Convert the ChatMessage to ChatMessageResponse format
    return schemas.ChatMessageResponse(
        id=message.id,
        sender_id=message.sender_id,
        sender_name=message.sender_name,
        message_type=message.message_type.value,  # Convert enum to string
        content=message.content,
        timestamp=message.timestamp.isoformat(),  # Convert datetime to string
        target_id=message.target_id,
        metadata=message.metadata
    )

@app.get("/chat/history/{chat_type}")
async def get_chat_history(chat_type: ChatType, target_id: Optional[int] = None, 
                    limit: int = 50, db: Session = Depends(get_db)):
    """Get chat history for a specific chat type"""
    if chat_type == ChatType.GLOBAL:
        messages = chat_manager.get_global_messages(limit)
    elif chat_type == ChatType.ROOM:
        if not target_id:
            raise HTTPException(status_code=400, detail="target_id required for room chat")
        messages = chat_manager.get_room_messages(target_id, limit)
    elif chat_type == ChatType.PRIVATE:
        if not target_id:
            raise HTTPException(status_code=400, detail="target_id required for private chat")
        messages = chat_manager.get_private_messages(target_id, limit)
    else:
        raise HTTPException(status_code=400, detail="Invalid chat type")
    
    # Convert ChatMessage objects to ChatMessageResponse format
    response_messages = []
    for msg in messages:
        response_messages.append(schemas.ChatMessageResponse(
            id=msg.id,
            sender_id=msg.sender_id,
            sender_name=msg.sender_name,
            message_type=msg.message_type.value,  # Convert enum to string
            content=msg.content,
            timestamp=msg.timestamp.isoformat(),  # Convert datetime to string
            target_id=msg.target_id,
            metadata=msg.metadata
        ))
    
    return {
        "messages": response_messages,
        "total_count": len(messages),
        "chat_type": chat_type,
        "target_id": target_id
    }

@app.post("/chat/npc")
async def chat_with_npc(chat_request: NPCChatRequest, db: Session = Depends(get_db)):
    """Chat with an NPC using LLM-powered responses"""
    # Verify player exists
    player = db.query(models.Player).filter(models.Player.id == chat_request.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Verify NPC exists
    npc = db.query(models.Npc).filter(models.Npc.id == chat_request.npc_id).first()
    if not npc:
        raise HTTPException(status_code=404, detail="NPC not found")
    
    # Check if NPC is in the same room as player
    if npc.room_id != player.room_id:
        raise HTTPException(status_code=400, detail="NPC is not in the same room")
    
    # Create NPC context
    context = NPCContext(
        player_level=player.level,
        player_reputation=getattr(player, 'reputation', 0),
        player_health=player.health,
        player_gold=getattr(player, 'gold', 0),
        room_id=player.room_id
    )
    
    # Create NPC context
    context = NPCContext(
        player_level=player.level,
        player_reputation=getattr(player, 'reputation', 0),
        player_health=player.health,
        player_gold=getattr(player, 'gold', 0),
        room_id=player.room_id
    )
    
    # Try to get intelligent response from NPC
    try:
        # Create a temporary NPC instance to generate response
        from llm_npcs import MerchantNPC, QuestGiverNPC, CombatMobNPC
        
        if npc.npc_type == "merchant":
            npc_instance = MerchantNPC(npc.id, npc.name, npc.description)
        elif npc.npc_type == "quest_giver":
            npc_instance = QuestGiverNPC(npc.id, npc.name, npc.description)
        elif npc.npc_type == "combat_mob":
            npc_instance = CombatMobNPC(npc.id, npc.name, npc.description, npc.level)
        else:
            # Generic NPC
            npc_instance = BaseLLMNPC(
                npc.id, npc.name, npc.description,
                NPCDisposition.NEUTRAL, NPCRole.INFORMANT,
                NPCStats(level=npc.level, health=npc.health, max_health=npc.max_health)
            )
        
        # Generate intelligent response
        response = await npc_instance.generate_response(chat_request.message, context)
        
        # Check if NPC should attack (for combat mobs)
        should_attack = npc_instance.should_attack_player(context)
        
    except Exception as e:
        print(f"Error generating NPC response: {e}")
        # Fallback response
        response = f"{npc.name} says: 'I heard you say: {chat_request.message}'"
        should_attack = False
    
    return {
        "npc_id": npc.id,
        "npc_name": npc.name,
        "response": response,
        "disposition": "neutral",
        "should_attack": should_attack
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
