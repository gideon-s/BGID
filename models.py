"""
SQLAlchemy ORM models for the RPG Game API
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, CheckConstraint, 
    UniqueConstraint, Text, DateTime
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
from database import Base
from config import (
    DEFAULT_PLAYER_HEALTH, DEFAULT_PLAYER_LEVEL, DEFAULT_PLAYER_EXP,
    DEFAULT_ABILITY_SCORE, DEFAULT_NPC_HEALTH
)

# ---------- Ability Scores Mixin ----------
class AbilityScoresMixin:
    """Mixin providing ability scores and modifiers for characters"""
    
    str = Column(Integer, default=DEFAULT_ABILITY_SCORE, nullable=False)
    dex = Column(Integer, default=DEFAULT_ABILITY_SCORE, nullable=False)
    con = Column(Integer, default=DEFAULT_ABILITY_SCORE, nullable=False)
    intel = Column(Integer, default=DEFAULT_ABILITY_SCORE, nullable=False)
    wis = Column(Integer, default=DEFAULT_ABILITY_SCORE, nullable=False)
    cha = Column(Integer, default=DEFAULT_ABILITY_SCORE, nullable=False)

    def ability_mod(self, name: str) -> int:
        """Calculate ability modifier for a given ability"""
        if name == "int":
            name = "intel"
        return (getattr(self, name) - 10) // 2

    def get_all_modifiers(self) -> dict[str, int]:
        """Get all ability modifiers as a dictionary"""
        return {ability: self.ability_mod(ability) for ability in ["str", "dex", "con", "intel", "wis", "cha"]}

    @property
    def abilities(self) -> dict[str, int]:
        """Ability scores as a dict, so response schemas (PlayerOut/NpcOut)
        can serialize the flat columns into a nested ``abilities`` object."""
        return {
            "str": self.str, "dex": self.dex, "con": self.con,
            "intel": self.intel, "wis": self.wis, "cha": self.cha,
        }

# ---------- Base Models ----------
class Room(Base):
    """Room model representing locations in the game world"""
    __tablename__ = "rooms"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, default="", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    players = relationship("Player", back_populates="room", cascade="all, delete-orphan")
    npcs = relationship("Npc", back_populates="room", cascade="all, delete-orphan")
    items = relationship("Item", back_populates="room", cascade="all, delete-orphan")
    # Exits leading out of this room
    exits = relationship(
        "RoomExit",
        foreign_keys="RoomExit.from_room_id",
        back_populates="from_room",
        cascade="all, delete-orphan",
    )

class RoomExit(Base):
    """A directed exit from one room to another in a given direction.

    Two-way connections are two RoomExit rows (north + its reverse south);
    one-way exits are a single row. An exit may be locked behind a key item.
    """
    __tablename__ = "room_exits"

    id = Column(Integer, primary_key=True, index=True)
    from_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    to_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    direction = Column(String(20), nullable=False)
    description = Column(Text, default="", nullable=False)
    is_locked = Column(Boolean, default=False, nullable=False)
    key_item_id = Column(Integer, ForeignKey("items.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("from_room_id", "direction", name="uq_room_exit_direction"),
    )

    from_room = relationship("Room", foreign_keys=[from_room_id], back_populates="exits")
    to_room = relationship("Room", foreign_keys=[to_room_id])

class User(Base):
    """An account. One user owns many player characters (one-to-many).

    Identity is username + password (no email verification — the host has no
    mail capability). `role` is 'player' or 'admin'; admins may mutate world
    state (rooms/npcs/items/exits) via the protected CRUD endpoints.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=True, index=True)  # optional, unverified
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="player", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    # An account's player characters.
    characters = relationship(
        "Player", back_populates="owner", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class RevokedToken(Base):
    """Blacklisted refresh-token jti (SQLite stand-in for dreamcrawler's Redis
    blacklist). A jti lands here when a refresh token is rotated or on logout;
    kept until `expires_at` (the token's own expiry), after which the token
    fails its exp check anyway and the row can be pruned."""
    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Player(Base, AbilityScoresMixin):
    """Player model representing game characters"""
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    # Owning account. Nullable so seeded/system characters can exist ownerless,
    # but every character created through the API belongs to a User.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    health = Column(Integer, default=DEFAULT_PLAYER_HEALTH, nullable=False)
    max_health = Column(Integer, default=DEFAULT_PLAYER_HEALTH, nullable=False)
    level = Column(Integer, default=DEFAULT_PLAYER_LEVEL, nullable=False)
    experience = Column(Integer, default=DEFAULT_PLAYER_EXP, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    owner = relationship("User", back_populates="characters")
    room = relationship("Room", back_populates="players")
    items = relationship("Item", back_populates="player", cascade="all, delete-orphan")
    npc_reactions = relationship("NpcReaction", back_populates="player", cascade="all, delete-orphan")

    def is_alive(self) -> bool:
        """Check if player is alive"""
        return self.health > 0
    
    def heal(self, amount: int) -> int:
        """Heal player by specified amount, return actual healing done"""
        old_health = self.health
        self.health = min(self.max_health, self.health + amount)
        return self.health - old_health
    
    def take_damage(self, amount: int) -> int:
        """Apply damage to player, return actual damage taken"""
        old_health = self.health
        self.health = max(0, self.health - amount)
        return old_health - self.health

class Npc(Base, AbilityScoresMixin):
    """NPC model representing non-player characters"""
    __tablename__ = "npcs"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, default="", nullable=False)
    npc_type = Column(String(50), default="generic", nullable=False, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Combat and behavior flags
    combat_enabled = Column(Boolean, default=True, nullable=False)
    is_friendly = Column(Boolean, default=False, nullable=False)
    health = Column(Integer, default=DEFAULT_NPC_HEALTH, nullable=False)
    max_health = Column(Integer, default=DEFAULT_NPC_HEALTH, nullable=False)
    
    # Relationships
    room = relationship("Room", back_populates="npcs")
    reactions = relationship("NpcReaction", back_populates="npc", cascade="all, delete-orphan")

    def is_alive(self) -> bool:
        """Check if NPC is alive"""
        return self.health > 0

class NpcReaction(Base):
    """NPC reactions to specific players"""
    __tablename__ = "npc_reactions"
    
    id = Column(Integer, primary_key=True, index=True)
    npc_id = Column(Integer, ForeignKey("npcs.id"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Reaction values (0-100)
    threat = Column(Integer, default=0, nullable=False)
    attraction = Column(Integer, default=0, nullable=False)
    arousal = Column(Integer, default=0, nullable=False)
    aggression = Column(Integer, default=0, nullable=False)
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("npc_id", "player_id", name="uq_npc_player_reaction"),
        CheckConstraint("threat BETWEEN 0 AND 100"),
        CheckConstraint("attraction BETWEEN 0 AND 100"),
        CheckConstraint("arousal BETWEEN 0 AND 100"),
        CheckConstraint("aggression BETWEEN 0 AND 100"),
    )
    
    # Relationships
    npc = relationship("Npc", back_populates="reactions")
    player = relationship("Player", back_populates="npc_reactions")

class Item(Base):
    """Item model representing objects in the game world"""
    __tablename__ = "items"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, default="", nullable=False)
    item_type = Column(String(50), default="generic", nullable=False, index=True)
    value = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Location tracking
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True)
    
    # Item properties
    is_movable = Column(Boolean, default=True, nullable=False)
    is_usable = Column(Boolean, default=False, nullable=False)
    is_equippable = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    room = relationship("Room", back_populates="items")
    player = relationship("Player", back_populates="items")

    def is_owned(self) -> bool:
        """Check if item is owned by a player"""
        return self.player_id is not None
    
    def is_in_room(self) -> bool:
        """Check if item is in a room"""
        return self.room_id is not None
    
    def can_pickup(self) -> bool:
        """Check if item can be picked up"""
        return self.is_movable and self.is_in_room()
