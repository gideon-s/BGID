from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, CheckConstraint, UniqueConstraint
)
from sqlalchemy.orm import relationship
from database import Base

# ---------- Ability mixin ----------
class AbilityScoresMixin:
    str = Column(Integer, default=10, nullable=False)
    dex = Column(Integer, default=10, nullable=False)
    con = Column(Integer, default=10, nullable=False)
    intel = Column(Integer, default=10, nullable=False)
    wis = Column(Integer, default=10, nullable=False)
    cha = Column(Integer, default=10, nullable=False)

    def ability_mod(self, name: str) -> int:
        if name == "int":
            name = "intel"
        return (getattr(self, name) - 10) // 2

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, default="", nullable=False)
    
    players = relationship("Player", back_populates="room")
    npcs = relationship("Npc", back_populates="room")
    items = relationship("Item", back_populates="room")

class Player(Base, AbilityScoresMixin):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    health = Column(Integer, default=10, nullable=False)
    max_health = Column(Integer, default=10, nullable=False)
    level = Column(Integer, default=1, nullable=False)
    experience = Column(Integer, default=0, nullable=False)
    
    room = relationship("Room", back_populates="players")
    items = relationship("Item", back_populates="player")

class Npc(Base, AbilityScoresMixin):
    __tablename__ = "npcs"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, default="", nullable=False)
    npc_type = Column(String, default="generic", nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    room = relationship("Room", back_populates="npcs")
    
    combat_enabled = Column(Boolean, default=True, nullable=False)
    is_friendly = Column(Boolean, default=False, nullable=False)
    health = Column(Integer, default=8, nullable=False)
    max_health = Column(Integer, default=8, nullable=False)

class NpcReaction(Base):
    __tablename__ = "npc_reactions"
    id = Column(Integer, primary_key=True)
    npc_id = Column(Integer, ForeignKey("npcs.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    
    threat = Column(Integer, default=0, nullable=False)
    attraction = Column(Integer, default=0, nullable=False)
    arousal = Column(Integer, default=0, nullable=False)
    aggression = Column(Integer, default=0, nullable=False)
    
    __table_args__ = (
        UniqueConstraint("npc_id", "player_id", name="uq_npc_player_reaction"),
        CheckConstraint("threat BETWEEN 0 AND 100"),
        CheckConstraint("attraction BETWEEN 0 AND 100"),
        CheckConstraint("arousal BETWEEN 0 AND 100"),
        CheckConstraint("aggression BETWEEN 0 AND 100"),
    )

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, default="", nullable=False)
    item_type = Column(String, default="generic", nullable=False)
    value = Column(Integer, default=0, nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    
    # NEW flags
    is_movable = Column(Boolean, default=True, nullable=False)
    is_usable = Column(Boolean, default=False, nullable=False)
    
    room = relationship("Room", back_populates="items")
    player = relationship("Player", back_populates="items")
