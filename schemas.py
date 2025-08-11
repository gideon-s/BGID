from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# Player schemas
class PlayerBase(BaseModel):
    name: str
    health: int = 100
    max_health: int = 100
    level: int = 1
    experience: int = 0
    room_id: Optional[int] = None

class PlayerCreate(PlayerBase):
    pass

class Player(PlayerBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# Room schemas
class RoomBase(BaseModel):
    name: str
    description: str
    is_accessible: bool = True

class RoomCreate(RoomBase):
    pass

class Room(RoomBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# Item schemas
class ItemBase(BaseModel):
    name: str
    description: str
    item_type: str
    value: int = 0
    room_id: Optional[int] = None
    player_id: Optional[int] = None
    is_equipped: bool = False

class ItemCreate(ItemBase):
    pass

class Item(ItemBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# Npc schemas
class NpcBase(BaseModel):
    name: str
    description: str
    npc_type: str
    health: int = 100
    max_health: int = 100
    room_id: int
    is_friendly: bool = True

class NpcCreate(NpcBase):
    pass

class Npc(NpcBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# Action schemas
class ActionRequest(BaseModel):
    player_id: int
    action_type: str  # move, attack, pickup, drop, use, etc.
    target_id: Optional[int] = None
    target_type: Optional[str] = None  # item, npc, room, etc.
    parameters: Optional[dict] = None

class ActionResponse(BaseModel):
    success: bool
    message: str
    player_state: Optional[Player] = None
    room_state: Optional[Room] = None

# State schemas
class PlayerState(BaseModel):
    player: Player
    current_room: Room
    inventory: List[Item]
    npcs_in_room: List[Npc]
    items_in_room: List[Item]
    other_players_in_room: List[Player]  # New field for other players

# Chat schemas
class ChatMessageResponse(BaseModel):
    id: str
    sender_id: int
    sender_name: str
    message_type: str
    content: str
    timestamp: datetime
    target_id: Optional[int] = None
    metadata: Optional[dict] = None
