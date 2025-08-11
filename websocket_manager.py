#!/usr/bin/env python3
"""
WebSocket Manager for real-time multiplayer communication
"""
import json
import asyncio
from typing import Dict, Set, Optional
from fastapi import WebSocket
from datetime import datetime

class ConnectionManager:
    def __init__(self):
        # Store active connections by player ID
        self.active_connections: Dict[int, WebSocket] = {}
        # Store room subscriptions (which players are listening to which rooms)
        self.room_subscriptions: Dict[int, Set[int]] = {}  # room_id -> set of player_ids
        
    async def connect(self, websocket: WebSocket, player_id: int):
        """Connect a player's WebSocket"""
        await websocket.accept()
        self.active_connections[player_id] = websocket
        print(f"Player {player_id} connected via WebSocket")
        
    def disconnect(self, player_id: int):
        """Disconnect a player's WebSocket"""
        if player_id in self.active_connections:
            del self.active_connections[player_id]
            # Remove player from all room subscriptions
            for room_id in list(self.room_subscriptions.keys()):
                if room_id in self.room_subscriptions:
                    self.room_subscriptions[room_id].discard(player_id)
                    # Clean up empty room subscriptions
                    if not self.room_subscriptions[room_id]:
                        del self.room_subscriptions[room_id]
            print(f"Player {player_id} disconnected from WebSocket")
    
    def subscribe_to_room(self, player_id: int, room_id: int):
        """Subscribe a player to updates from a specific room"""
        if room_id not in self.room_subscriptions:
            self.room_subscriptions[room_id] = set()
        self.room_subscriptions[room_id].add(player_id)
        print(f"Player {player_id} subscribed to room {room_id}")
    
    def unsubscribe_from_room(self, player_id: int, room_id: int):
        """Unsubscribe a player from updates from a specific room"""
        if room_id in self.room_subscriptions and player_id in self.room_subscriptions[room_id]:
            self.room_subscriptions[room_id].discard(player_id)
            if not self.room_subscriptions[room_id]:
                del self.room_subscriptions[room_id]
            print(f"Player {player_id} unsubscribed from room {room_id}")
    
    async def broadcast_to_room(self, room_id: int, message: dict, exclude_player: Optional[int] = None):
        """Broadcast a message to all players in a specific room"""
        if room_id not in self.room_subscriptions:
            return
        
        # Create a copy of the set to avoid modification during iteration
        player_ids = list(self.room_subscriptions[room_id])
        disconnected_players = []
        
        for player_id in player_ids:
            if player_id == exclude_player:
                continue
                
            if player_id in self.active_connections:
                try:
                    await self.active_connections[player_id].send_text(json.dumps(message))
                except Exception as e:
                    print(f"Error sending message to player {player_id}: {e}")
                    disconnected_players.append(player_id)
            else:
                disconnected_players.append(player_id)
        
        # Clean up disconnected players
        for player_id in disconnected_players:
            self.unsubscribe_from_room(player_id, room_id)
    
    async def send_personal_message(self, player_id: int, message: dict):
        """Send a message to a specific player"""
        if player_id in self.active_connections:
            try:
                await self.active_connections[player_id].send_text(json.dumps(message))
            except Exception as e:
                print(f"Error sending personal message to player {player_id}: {e}")
                self.disconnect(player_id)
    
    async def broadcast_to_all(self, message: dict):
        """Broadcast a message to all connected players"""
        disconnected_players = []
        
        for player_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                print(f"Error broadcasting to player {player_id}: {e}")
                disconnected_players.append(player_id)
        
        # Clean up disconnected players
        for player_id in disconnected_players:
            self.disconnect(player_id)
    
    async def broadcast_player_action(self, player_id: int, room_id: int, action_type: str, action_data: dict):
        """Broadcast a player's action to others in the same room"""
        message = {
            "type": "player_action",
            "timestamp": datetime.utcnow().isoformat(),
            "player_id": player_id,
            "action_type": action_type,
            "action_data": action_data
        }
        
        await self.broadcast_to_room(room_id, message, exclude_player=player_id)
    
    async def broadcast_player_joined(self, player_id: int, room_id: int, player_info: dict):
        """Broadcast when a player joins a room"""
        message = {
            "type": "player_joined",
            "timestamp": datetime.utcnow().isoformat(),
            "player_id": player_id,
            "player_info": player_info,
            "room_id": room_id
        }
        
        await self.broadcast_to_room(room_id, message, exclude_player=player_id)
    
    async def broadcast_player_left(self, player_id: int, room_id: int, player_info: dict):
        """Broadcast when a player leaves a room"""
        message = {
            "type": "player_left",
            "timestamp": datetime.utcnow().isoformat(),
            "player_id": player_id,
            "player_info": player_info,
            "room_id": room_id
        }
        
        await self.broadcast_to_room(room_id, message, exclude_player=player_id)

# Global instance
manager = ConnectionManager()
