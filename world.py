#!/usr/bin/env python3
"""
In-memory authoritative world state for the MUD.

WorldState is the live source of truth for who/what is where. The database is
for persistence and recovery, not live reads:

- Structural data (rooms, resident NPCs, ground items) is loaded at startup.
- Player presence (who is online and in which room) is tracked in memory.
- Durable mutations (a player moving rooms) are written through to the DB.

See ARCHITECTURE.md (step 1).
"""
from dataclasses import dataclass, field
from typing import Dict, Set, Optional, List, Any

from database import SessionLocal
import services

# A generous cap so load() pulls the whole table (service defaults are paged).
_LOAD_LIMIT = 100_000


@dataclass
class RoomNode:
    """Live state for a single room."""
    id: int
    name: str
    description: str
    npc_ids: Set[int] = field(default_factory=set)    # resident NPCs
    item_ids: Set[int] = field(default_factory=set)   # items on the ground
    players: Set[int] = field(default_factory=set)     # online players present


class WorldState:
    """The authoritative, in-memory game world."""

    def __init__(self):
        self.rooms: Dict[int, RoomNode] = {}
        self.player_locations: Dict[int, int] = {}  # online player_id -> room_id
        self.loaded: bool = False

    # ---------- loading ----------
    def load(self) -> None:
        """(Re)load structural world data from the DB. Players start offline."""
        db = SessionLocal()
        try:
            rooms: Dict[int, RoomNode] = {}
            for room in services.RoomService.get_rooms(db, limit=_LOAD_LIMIT):
                rooms[room.id] = RoomNode(
                    id=room.id, name=room.name, description=room.description or ""
                )
            for npc in services.NpcService.get_npcs(db, limit=_LOAD_LIMIT):
                node = rooms.get(npc.room_id)
                if node:
                    node.npc_ids.add(npc.id)
            for item in services.ItemService.get_items(db, limit=_LOAD_LIMIT):
                if item.room_id and item.room_id in rooms:
                    rooms[item.room_id].item_ids.add(item.id)
            self.rooms = rooms
            self.player_locations = {}
            self.loaded = True
        finally:
            db.close()

    def reload(self) -> None:
        """Resync structural data from the DB while preserving online presence.

        Use after admin/REST edits to rooms/NPCs/items.
        """
        online = dict(self.player_locations)
        self.load()
        for player_id, room_id in online.items():
            if room_id in self.rooms:
                self.rooms[room_id].players.add(player_id)
                self.player_locations[player_id] = room_id

    # ---------- presence ----------
    def enter_world(self, player_id: int) -> Optional[int]:
        """Bring an online player into their persisted room. Returns the room id."""
        db = SessionLocal()
        try:
            player = services.PlayerService.get_player(db, player_id)
            room_id = player.room_id if player else None
        finally:
            db.close()
        if room_id is None or room_id not in self.rooms:
            return None
        self.rooms[room_id].players.add(player_id)
        self.player_locations[player_id] = room_id
        return room_id

    def leave_world(self, player_id: int) -> Optional[int]:
        """Mark a player offline. Returns the room they left, if any."""
        room_id = self.player_locations.pop(player_id, None)
        if room_id is not None and room_id in self.rooms:
            self.rooms[room_id].players.discard(player_id)
        return room_id

    def room_of(self, player_id: int) -> Optional[int]:
        """Current room of an online player, or None if offline."""
        return self.player_locations.get(player_id)

    def move_player(self, player_id: int, to_room_id: int) -> bool:
        """Move an online player to another room, writing the change through to
        the DB. Returns False if the target room doesn't exist."""
        if to_room_id not in self.rooms:
            return False
        from_room = self.player_locations.get(player_id)
        if from_room == to_room_id:
            return True
        if from_room is not None and from_room in self.rooms:
            self.rooms[from_room].players.discard(player_id)
        self.rooms[to_room_id].players.add(player_id)
        self.player_locations[player_id] = to_room_id

        db = SessionLocal()
        try:
            player = services.PlayerService.get_player(db, player_id)
            if player:
                player.room_id = to_room_id
                db.commit()
        finally:
            db.close()
        return True

    # ---------- queries ----------
    def room_snapshot(self, room_id: int) -> Optional[Dict[str, Any]]:
        """A serializable view of a room: metadata + present players, NPCs, items.

        Suitable as the payload for a ``room_state`` event.
        """
        node = self.rooms.get(room_id)
        if node is None:
            return None
        db = SessionLocal()
        try:
            npcs = []
            for npc_id in node.npc_ids:
                npc = services.NpcService.get_npc(db, npc_id)
                if npc:
                    npcs.append({"id": npc.id, "name": npc.name, "npc_type": npc.npc_type})
            items = []
            for item_id in node.item_ids:
                item = services.ItemService.get_item(db, item_id)
                if item:
                    items.append({"id": item.id, "name": item.name})
            players = []
            for player_id in node.players:
                player = services.PlayerService.get_player(db, player_id)
                if player:
                    players.append({"id": player.id, "name": player.name})
        finally:
            db.close()
        return {
            "room": {"id": node.id, "name": node.name, "description": node.description},
            "players": players,
            "npcs": npcs,
            "items": items,
        }

    def occupants(self, room_id: int) -> List[int]:
        """Online player ids currently in a room."""
        node = self.rooms.get(room_id)
        return list(node.players) if node else []

    def online_players(self) -> List[int]:
        """All online player ids."""
        return list(self.player_locations.keys())


# Global instance
world = WorldState()
