#!/usr/bin/env python3
"""
Chat System for the Multiplayer Game
Supports global, room, and private messaging
"""

import json
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum

class ChatType(Enum):
    """Types of chat messages"""
    GLOBAL = "global"
    ROOM = "room"
    PRIVATE = "private"
    SYSTEM = "system"
    NPC = "npc"

@dataclass
class ChatMessage:
    """Chat message structure"""
    id: str
    sender_id: int
    sender_name: str
    message_type: ChatType
    content: str
    timestamp: datetime
    target_id: Optional[int] = None  # For private messages or room chat
    metadata: Optional[Dict] = None  # For additional context

class ChatManager:
    """Manages all chat functionality"""
    
    def __init__(self):
        self.global_messages: List[ChatMessage] = []
        self.room_messages: Dict[int, List[ChatMessage]] = {}  # room_id -> messages
        self.private_messages: Dict[int, List[ChatMessage]] = {}  # player_id -> messages
        self.max_messages_per_chat = 100  # Keep last 100 messages per chat
        
    def add_message(self, message: ChatMessage) -> None:
        """Add a message to the appropriate chat"""
        if message.message_type == ChatType.GLOBAL:
            self.global_messages.append(message)
            if len(self.global_messages) > self.max_messages_per_chat:
                self.global_messages.pop(0)
                
        elif message.message_type == ChatType.ROOM:
            room_id = message.target_id
            if room_id not in self.room_messages:
                self.room_messages[room_id] = []
            self.room_messages[room_id].append(message)
            if len(self.room_messages[room_id]) > self.max_messages_per_chat:
                self.room_messages[room_id].pop(0)
                
        elif message.message_type == ChatType.PRIVATE:
            target_id = message.target_id
            if target_id not in self.private_messages:
                self.private_messages[target_id] = []
            self.private_messages[target_id].append(message)
            if len(self.private_messages[target_id]) > self.max_messages_per_chat:
                self.private_messages[target_id].pop(0)
    
    def get_global_messages(self, limit: int = 50) -> List[ChatMessage]:
        """Get recent global messages"""
        return self.global_messages[-limit:]
    
    def get_room_messages(self, room_id: int, limit: int = 50) -> List[ChatMessage]:
        """Get recent room messages"""
        if room_id not in self.room_messages:
            return []
        return self.room_messages[room_id][-limit:]
    
    def get_private_messages(self, player_id: int, limit: int = 50) -> List[ChatMessage]:
        """Get recent private messages for a player"""
        if player_id not in self.private_messages:
            return []
        return self.private_messages[player_id][-limit:]
    
    def create_message(self, sender_id: int, sender_name: str, message_type: ChatType, 
                      content: str, target_id: Optional[int] = None, 
                      metadata: Optional[Dict] = None) -> ChatMessage:
        """Create a new chat message"""
        message_id = f"{sender_id}_{datetime.now().timestamp()}"
        message = ChatMessage(
            id=message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            message_type=message_type,
            content=content,
            timestamp=datetime.now(),
            target_id=target_id,
            metadata=metadata
        )
        self.add_message(message)
        return message

# Global chat manager instance
chat_manager = ChatManager()
