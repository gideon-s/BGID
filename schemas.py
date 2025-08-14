from pydantic import BaseModel, conint
from typing import List, Optional, Dict

class RoomOut(BaseModel):
    id: int
    name: str
    description: str

class PlayerOut(BaseModel):
    id: int
    name: str
    room_id: int
    health: int
    max_health: int
    level: int
    experience: int
    str: int = 10
    dex: int = 10
    con: int = 10
    intel: int = 10
    wis: int = 10
    cha: int = 10

class AbilityScores(BaseModel):
    str: int = 10
    dex: int = 10
    con: int = 10
    intel: int = 10
    wis: int = 10
    cha: int = 10

class PlayerSheet(BaseModel):
    id: int
    name: str
    health: int
    max_health: int
    level: int
    experience: int
    abilities: AbilityScores
    modifiers: Dict[str, int]
    location_name: str

class ItemOut(BaseModel):
    id: int
    name: str
    description: str
    item_type: str
    value: int
    room_id: Optional[int] = None
    player_id: Optional[int] = None
    is_movable: bool
    is_usable: bool

class NpcOut(BaseModel):
    id: int
    name: str
    description: str
    npc_type: str
    room_id: int
    is_friendly: bool
    combat_enabled: bool
    health: int
    max_health: int
    str: int = 10
    dex: int = 10
    con: int = 10
    intel: int = 10
    wis: int = 10
    cha: int = 10

class NpcSheet(BaseModel):
    id: int
    name: str
    description: str
    npc_type: str
    combat_enabled: bool
    health: int
    max_health: int
    abilities: AbilityScores
    modifiers: Dict[str, int]
    location_name: str

ZeroTo100 = conint(ge=0, le=100)

class NpcReactionOut(BaseModel):
    npc_id: int
    player_id: int
    threat: ZeroTo100
    attraction: ZeroTo100
    arousal: ZeroTo100
    aggression: ZeroTo100

class NpcReactionUpdate(BaseModel):
    threat: Optional[ZeroTo100] = None
    attraction: Optional[ZeroTo100] = None
    arousal: Optional[ZeroTo100] = None
    aggression: Optional[ZeroTo100] = None

# Additional schemas needed for compatibility
class PlayerCreate(BaseModel):
    name: str
    health: int = 10
    max_health: int = 10
    level: int = 1
    experience: int = 0
    room_id: int

class Player(PlayerOut):
    pass

class RoomCreate(BaseModel):
    name: str
    description: str

class Room(RoomOut):
    pass

class ItemCreate(BaseModel):
    name: str
    description: str
    item_type: str
    value: int = 0
    room_id: Optional[int] = None
    player_id: Optional[int] = None
    is_movable: bool = True
    is_usable: bool = False

class Item(ItemOut):
    pass

class NpcCreate(BaseModel):
    name: str
    description: str
    npc_type: str
    room_id: int
    is_friendly: bool = False
    combat_enabled: bool = True
    health: int = 8
    max_health: int = 8

class Npc(NpcOut):
    pass

class ActionRequest(BaseModel):
    player_id: int
    action_type: str
    target_id: Optional[int] = None
    target_type: Optional[str] = None
    parameters: Optional[dict] = None

class ActionResponse(BaseModel):
    success: bool
    message: str
    player_state: Optional[dict] = None
    room_state: Optional[dict] = None

class PlayerState(BaseModel):
    player: PlayerOut
    current_room: RoomOut
    inventory: List[ItemOut]
    npcs_in_room: List[NpcOut]
    items_in_room: List[ItemOut]
    other_players_in_room: List[PlayerOut]

class ChatMessageResponse(BaseModel):
    id: str
    sender_id: int
    sender_name: str
    message_type: str
    content: str
    timestamp: str
    target_id: Optional[int] = None
    metadata: Optional[dict] = None
