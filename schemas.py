"""
Pydantic schemas for API request/response validation
"""
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from config import (
    MIN_ABILITY_SCORE, MAX_ABILITY_SCORE, MIN_REACTION_VALUE, MAX_REACTION_VALUE,
    DEFAULT_ABILITY_SCORE, DEFAULT_PLAYER_HEALTH, DEFAULT_PLAYER_LEVEL
)

# ---------- Base Schemas ----------
class BaseResponse(BaseModel):
    """Base response model with common fields"""
    success: bool = True
    message: str = "Operation completed successfully"
    timestamp: datetime = Field(default_factory=datetime.now)

# ---------- Ability Score Schemas ----------
class AbilityScores(BaseModel):
    """Ability scores for characters"""
    str: int = Field(default=DEFAULT_ABILITY_SCORE, ge=MIN_ABILITY_SCORE, le=MAX_ABILITY_SCORE)
    dex: int = Field(default=DEFAULT_ABILITY_SCORE, ge=MIN_ABILITY_SCORE, le=MAX_ABILITY_SCORE)
    con: int = Field(default=DEFAULT_ABILITY_SCORE, ge=MIN_ABILITY_SCORE, le=MAX_ABILITY_SCORE)
    intel: int = Field(default=DEFAULT_ABILITY_SCORE, ge=MIN_ABILITY_SCORE, le=MAX_ABILITY_SCORE)
    wis: int = Field(default=DEFAULT_ABILITY_SCORE, ge=MIN_ABILITY_SCORE, le=MAX_ABILITY_SCORE)
    cha: int = Field(default=DEFAULT_ABILITY_SCORE, ge=MIN_ABILITY_SCORE, le=MAX_ABILITY_SCORE)

    @validator('*')
    def validate_ability_score(cls, v):
        if not (MIN_ABILITY_SCORE <= v <= MAX_ABILITY_SCORE):
            raise ValueError(f'Ability score must be between {MIN_ABILITY_SCORE} and {MAX_ABILITY_SCORE}')
        return v

class AbilityModifiers(BaseModel):
    """Calculated ability modifiers"""
    str: int
    dex: int
    con: int
    intel: int
    wis: int
    cha: int

# ---------- Room Schemas ----------
class RoomBase(BaseModel):
    """Base room schema"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)

class RoomCreate(RoomBase):
    """Schema for creating a new room"""
    pass

class RoomUpdate(RoomBase):
    """Schema for updating a room (partial). Includes the tile-grid fields the
    map designer (handoff-10 §2) edits, plus room-type flags (handoff-09 §5)."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    width: Optional[int] = Field(None, ge=1, le=200)
    height: Optional[int] = Field(None, ge=1, le=200)
    tiles: Optional[str] = None
    spawn_x: Optional[int] = Field(None, ge=0)
    spawn_y: Optional[int] = Field(None, ge=0)
    room_type: Optional[str] = Field(None, max_length=20)
    is_safe: Optional[bool] = None


class RoomFeatureCreate(BaseModel):
    """Create a tile feature (handoff-09 §6): trap/hazard/sign/spawner/keg."""
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    kind: str = Field(..., max_length=20)
    glyph: str = Field("", max_length=8)
    config: dict = Field(default_factory=dict)


class RoomFeatureUpdate(BaseModel):
    """Partial update of a tile feature."""
    x: Optional[int] = Field(None, ge=0)
    y: Optional[int] = Field(None, ge=0)
    kind: Optional[str] = Field(None, max_length=20)
    glyph: Optional[str] = Field(None, max_length=8)
    config: Optional[dict] = None


class RoomFeatureOut(BaseModel):
    """A tile feature for the designer/admin."""
    id: int
    room_id: int
    x: int
    y: int
    kind: str
    glyph: str
    config: dict


class MapGenRequest(BaseModel):
    """Author-time procedural generation request (handoff-11 §D, designer §2)."""
    kind: str = Field(..., max_length=20)            # "cave" | "rooms"
    width: int = Field(..., ge=5, le=200)
    height: int = Field(..., ge=5, le=200)
    seed: Optional[int] = None
    params: dict = Field(default_factory=dict)

class RoomOut(RoomBase):
    """Schema for room output (includes the tile grid + level fields the map
    designer needs to load a room for editing)."""
    id: int
    width: Optional[int] = None
    height: Optional[int] = None
    tiles: Optional[str] = None
    spawn_x: Optional[int] = None
    spawn_y: Optional[int] = None
    room_type: Optional[str] = "dungeon"
    is_safe: Optional[bool] = False
    level_id: Optional[int] = None
    z: Optional[int] = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LevelBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)


class LevelOut(LevelBase):
    id: int

    class Config:
        from_attributes = True

# ---------- Player Schemas ----------
class PlayerBase(BaseModel):
    """Base player schema"""
    name: str = Field(..., min_length=1, max_length=100)
    room_id: int = Field(..., gt=0)

class PlayerCreate(PlayerBase):
    """Schema for creating a new player"""
    health: Optional[int] = Field(DEFAULT_PLAYER_HEALTH, ge=1)
    max_health: Optional[int] = Field(DEFAULT_PLAYER_HEALTH, ge=1)
    level: Optional[int] = Field(DEFAULT_PLAYER_LEVEL, ge=1)
    experience: Optional[int] = Field(0, ge=0)
    abilities: Optional[AbilityScores] = None

    @validator('max_health')
    def max_health_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('max_health must be positive')
        return v

    @validator('health')
    def health_cannot_exceed_max(cls, v, values):
        if 'max_health' in values and v > values['max_health']:
            raise ValueError('health cannot exceed max_health')
        return v

class PlayerUpdate(BaseModel):
    """Schema for updating a player"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    room_id: Optional[int] = Field(None, gt=0)
    health: Optional[int] = Field(None, ge=0)
    max_health: Optional[int] = Field(None, ge=1)
    level: Optional[int] = Field(None, ge=1)
    experience: Optional[int] = Field(None, ge=0)
    abilities: Optional[AbilityScores] = None

class PlayerOut(PlayerBase):
    """Schema for player output"""
    id: int
    health: int
    max_health: int
    level: int
    experience: int
    abilities: AbilityScores
    created_at: Optional[datetime] = None
    last_active: Optional[datetime] = None

    class Config:
        from_attributes = True

class PlayerSheet(BaseModel):
    """Comprehensive player character sheet"""
    id: int
    name: str
    health: int
    max_health: int
    level: int
    experience: int
    abilities: AbilityScores
    modifiers: AbilityModifiers
    location_name: str
    inventory_count: int

    class Config:
        from_attributes = True

# ---------- Item Schemas ----------
class ItemBase(BaseModel):
    """Base item schema"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    item_type: str = Field(default="generic", max_length=50)
    value: int = Field(default=0, ge=0)

class ItemCreate(ItemBase):
    """Schema for creating a new item"""
    glyph: str = Field(default="📦", max_length=8)
    room_id: Optional[int] = Field(None, gt=0)
    player_id: Optional[int] = Field(None, gt=0)
    tile_x: Optional[int] = Field(None, ge=0)
    tile_y: Optional[int] = Field(None, ge=0)
    is_movable: bool = True
    is_usable: bool = False
    is_equippable: bool = False
    equip_slot: Optional[str] = Field(None, max_length=20)
    attack_bonus: int = 0
    defense_bonus: int = 0
    damage_bonus: int = 0

class ItemUpdate(BaseModel):
    """Schema for updating an item"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    item_type: Optional[str] = Field(None, max_length=50)
    value: Optional[int] = Field(None, ge=0)
    room_id: Optional[int] = Field(None, gt=0)
    player_id: Optional[int] = Field(None, gt=0)
    is_movable: Optional[bool] = None
    is_usable: Optional[bool] = None
    is_equippable: Optional[bool] = None

class ItemOut(ItemBase):
    """Schema for item output"""
    id: int
    glyph: str = "📦"
    room_id: Optional[int] = None
    player_id: Optional[int] = None
    tile_x: Optional[int] = None
    tile_y: Optional[int] = None
    is_movable: bool
    is_usable: bool
    is_equippable: bool
    equip_slot: Optional[str] = None
    equipped: bool = False
    attack_bonus: int = 0
    defense_bonus: int = 0
    damage_bonus: int = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# ---------- NPC Schemas ----------
class NpcBase(BaseModel):
    """Base NPC schema"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    npc_type: str = Field(default="generic", max_length=50)
    room_id: int = Field(..., gt=0)

class NpcCreate(NpcBase):
    """Schema for creating a new NPC"""
    combat_enabled: bool = True
    is_friendly: bool = False
    # Tile/AI fields (graphical overhaul + handoff-09): exposed so the admin
    # monster editor can author hostility, aggro, glyph, home tile, and wandering.
    is_hostile: bool = False
    aggro_radius: int = Field(6, ge=0)
    glyph: str = Field("👤", max_length=8)
    home_x: Optional[int] = Field(None, ge=0)
    home_y: Optional[int] = Field(None, ge=0)
    wanders: bool = False
    health: Optional[int] = Field(8, ge=1)
    max_health: Optional[int] = Field(8, ge=1)
    abilities: Optional[AbilityScores] = None

class NpcUpdate(BaseModel):
    """Schema for updating an NPC (all fields optional / partial)."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    npc_type: Optional[str] = Field(None, max_length=50)
    room_id: Optional[int] = Field(None, gt=0)
    combat_enabled: Optional[bool] = None
    is_friendly: Optional[bool] = None
    is_hostile: Optional[bool] = None
    aggro_radius: Optional[int] = Field(None, ge=0)
    glyph: Optional[str] = Field(None, max_length=8)
    home_x: Optional[int] = Field(None, ge=0)
    home_y: Optional[int] = Field(None, ge=0)
    wanders: Optional[bool] = None
    health: Optional[int] = Field(None, ge=0)
    max_health: Optional[int] = Field(None, ge=1)
    abilities: Optional[AbilityScores] = None

class NpcOut(NpcBase):
    """Schema for NPC output"""
    id: int
    combat_enabled: bool
    is_friendly: bool
    is_hostile: bool = False
    aggro_radius: int = 6
    glyph: str = "👤"
    home_x: Optional[int] = None
    home_y: Optional[int] = None
    wanders: bool = False
    health: int
    max_health: int
    abilities: AbilityScores
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class NpcSheet(BaseModel):
    """Comprehensive NPC character sheet"""
    id: int
    name: str
    description: str
    npc_type: str
    combat_enabled: bool
    health: int
    max_health: int
    abilities: AbilityScores
    modifiers: AbilityModifiers
    location_name: str

    class Config:
        from_attributes = True

# ---------- NPC Reaction Schemas ----------
class NpcReactionBase(BaseModel):
    """Base NPC reaction schema"""
    npc_id: int = Field(..., gt=0)
    player_id: int = Field(..., gt=0)

class NpcReactionOut(NpcReactionBase):
    """Schema for NPC reaction output"""
    id: int
    threat: int = Field(..., ge=MIN_REACTION_VALUE, le=MAX_REACTION_VALUE)
    attraction: int = Field(..., ge=MIN_REACTION_VALUE, le=MAX_REACTION_VALUE)
    arousal: int = Field(..., ge=MIN_REACTION_VALUE, le=MAX_REACTION_VALUE)
    aggression: int = Field(..., ge=MIN_REACTION_VALUE, le=MAX_REACTION_VALUE)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class NpcReactionUpdate(BaseModel):
    """Schema for updating NPC reactions"""
    threat: Optional[int] = Field(None, ge=MIN_REACTION_VALUE, le=MAX_REACTION_VALUE)
    attraction: Optional[int] = Field(None, ge=MIN_REACTION_VALUE, le=MAX_REACTION_VALUE)
    arousal: Optional[int] = Field(None, ge=MIN_REACTION_VALUE, le=MAX_REACTION_VALUE)
    aggression: Optional[int] = Field(None, ge=MIN_REACTION_VALUE, le=MAX_REACTION_VALUE)

# ---------- Join Schema ----------
class JoinRequest(BaseModel):
    """Request to join the game by name (web client entry)."""
    name: str = Field(..., min_length=1, max_length=100)

# ---------- Room Exit Schemas ----------
class RoomExitCreate(BaseModel):
    """Schema for creating an exit out of a room."""
    direction: str = Field(..., min_length=1, max_length=20)
    to_room_id: int = Field(..., gt=0)
    description: str = Field(default="", max_length=1000)
    is_locked: bool = False
    key_item_id: Optional[int] = Field(None, gt=0)
    bidirectional: bool = Field(True, description="Also create the reverse exit")

class RoomExitOut(BaseModel):
    """Schema for an exit."""
    id: int
    from_room_id: int
    to_room_id: int
    direction: str
    description: str
    is_locked: bool
    key_item_id: Optional[int] = None

    class Config:
        from_attributes = True

# ---------- Action Schemas ----------
class ActionRequest(BaseModel):
    """Schema for game actions"""
    player_id: int = Field(..., gt=0)
    action_type: str = Field(..., min_length=1, max_length=50)
    target_id: Optional[int] = Field(None, gt=0)
    parameters: Optional[Dict[str, Any]] = None

class ActionResponse(BaseResponse):
    """Schema for action responses"""
    player_state: Optional[Dict[str, Any]] = None
    room_state: Optional[Dict[str, Any]] = None
    target_state: Optional[Dict[str, Any]] = None

# ---------- List Response Schemas ----------
class ListResponse(BaseModel):
    """Generic list response wrapper"""
    items: List[Any]
    total_count: int
    page: int = 1
    page_size: int = 100

class PlayersListResponse(ListResponse):
    """Players list response"""
    items: List[PlayerOut]

class RoomsListResponse(ListResponse):
    """Rooms list response"""
    items: List[RoomOut]

class ItemsListResponse(ListResponse):
    """Items list response"""
    items: List[ItemOut]

class NpcsListResponse(ListResponse):
    """NPCs list response"""
    items: List[NpcOut]

# ---------- Error Schemas ----------
class ErrorResponse(BaseModel):
    """Standard error response"""
    success: bool = False
    error: str
    details: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
