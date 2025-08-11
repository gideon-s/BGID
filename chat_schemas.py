#!/usr/bin/env python3
"""
Chat Schemas for the API
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from chat_system import ChatType

class ChatMessageRequest(BaseModel):
    """Request to send a chat message"""
    sender_id: int = Field(..., description="ID of the player sending the message")
    message_type: ChatType = Field(..., description="Type of chat message")
    content: str = Field(..., min_length=1, max_length=500, description="Message content")
    target_id: Optional[int] = Field(None, description="Target for private/room messages")

class ChatMessageResponse(BaseModel):
    """Response containing chat message"""
    id: str
    sender_id: int
    sender_name: str
    message_type: ChatType
    content: str
    timestamp: datetime
    target_id: Optional[int] = None
    metadata: Optional[dict] = None

class ChatHistoryRequest(BaseModel):
    """Request for chat history"""
    chat_type: ChatType = Field(..., description="Type of chat to get history for")
    target_id: Optional[int] = Field(None, description="Target ID for room/private chat")
    limit: int = Field(50, ge=1, le=100, description="Number of messages to retrieve")

class ChatHistoryResponse(BaseModel):
    """Response containing chat history"""
    messages: List[ChatMessageResponse]
    total_count: int
    chat_type: ChatType
    target_id: Optional[int] = None

class NPCChatRequest(BaseModel):
    """Request to chat with an NPC"""
    player_id: int = Field(..., description="ID of the player")
    npc_id: int = Field(..., description="ID of the NPC to chat with")
    message: str = Field(..., min_length=1, max_length=500, description="Message to NPC")

class NPCChatResponse(BaseModel):
    """Response from NPC chat"""
    npc_id: int
    npc_name: str
    response: str
    disposition: str
    should_attack: bool = False
    metadata: Optional[dict] = None

class ChatStatusResponse(BaseModel):
    """Response containing chat status information"""
    online_players: List[int]
    active_chats: List[str]
    unread_messages: int
    last_activity: datetime
