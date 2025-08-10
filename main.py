from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import models
import schemas
from database import engine, get_db

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Game API", description="A FastAPI game with SQLite database")

@app.get("/")
async def root():
    return {"message": "Welcome to the Game API!"}

@app.post("/players/", response_model=schemas.Player)
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
    return item

@app.post("/action", response_model=schemas.ActionResponse)
def perform_action(action: schemas.ActionRequest, db: Session = Depends(get_db)):
    # Get the player
    player = db.query(models.Player).filter(models.Player.id == action.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Simple action handling - you can expand this based on your game logic
    if action.action_type == "move":
        if action.target_type == "room" and action.target_id:
            # Check if room exists
            room = db.query(models.Room).filter(models.Room.id == action.target_id).first()
            if not room:
                raise HTTPException(status_code=404, detail="Room not found")
            if not room.is_accessible:
                raise HTTPException(status_code=400, detail="Room is not accessible")
            
            player.room_id = action.target_id
            db.commit()
            db.refresh(player)
            
            return schemas.ActionResponse(
                success=True,
                message=f"Player {player.name} moved to {room.name}",
                player_state=player
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
                player_state=player
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
                player_state=player
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
    
    return schemas.PlayerState(
        player=player,
        current_room=current_room,
        inventory=inventory,
        npcs_in_room=npcs_in_room,
        items_in_room=items_in_room
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
