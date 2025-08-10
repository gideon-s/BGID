from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Player(Base):
    __tablename__ = "players"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True)
    health = Column(Integer, default=100)
    max_health = Column(Integer, default=100)
    level = Column(Integer, default=1)
    experience = Column(Integer, default=0)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    room = relationship("Room", back_populates="players")
    inventory = relationship("Item", back_populates="owner")

class Room(Base):
    __tablename__ = "rooms"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True)
    description = Column(Text)
    is_accessible = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    players = relationship("Player", back_populates="room")
    items = relationship("Item", back_populates="room")
    npcs = relationship("Npc", back_populates="room")

class Item(Base):
    __tablename__ = "items"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), index=True)
    description = Column(Text)
    item_type = Column(String(50))  # weapon, armor, consumable, etc.
    value = Column(Integer, default=0)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    is_equipped = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    room = relationship("Room", back_populates="items")
    owner = relationship("Player", back_populates="inventory")

class Npc(Base):
    __tablename__ = "npcs"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), index=True)
    description = Column(Text)
    npc_type = Column(String(50))  # merchant, enemy, quest_giver, etc.
    health = Column(Integer, default=100)
    max_health = Column(Integer, default=100)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    is_friendly = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    room = relationship("Room", back_populates="npcs")
