"""
Business logic services for the RPG Game API
"""
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
import models
import schemas
import directions
from utils import dict_from_model, log_action, validate_ability_scores

# ---------- Player Services ----------
class PlayerService:
    """Service for player-related operations"""
    
    @staticmethod
    def create_player(db: Session, player_data: schemas.PlayerCreate) -> models.Player:
        """Create a new player"""
        try:
            # Flatten the nested abilities object onto the model's columns
            # (AbilityScores fields map 1:1 to str/dex/con/intel/wis/cha).
            player_dict = player_data.dict()
            abilities = player_dict.pop('abilities', None)
            if abilities:
                player_dict.update(abilities)

            db_player = models.Player(**player_dict)
            db.add(db_player)
            db.commit()
            db.refresh(db_player)
            
            log_action("create_player", db_player.id, f"Created player '{db_player.name}'")
            return db_player
            
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=400, detail="Player name already exists")
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to create player: {str(e)}")
    
    @staticmethod
    def get_player(db: Session, player_id: int) -> Optional[models.Player]:
        """Get player by ID"""
        return db.query(models.Player).filter(models.Player.id == player_id).first()
    
    @staticmethod
    def get_players(db: Session, skip: int = 0, limit: int = 100) -> List[models.Player]:
        """Get list of players with pagination"""
        return db.query(models.Player).offset(skip).limit(limit).all()
    
    @staticmethod
    def update_player(db: Session, player_id: int, player_data: schemas.PlayerUpdate) -> models.Player:
        """Update player information"""
        player = PlayerService.get_player(db, player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        
        update_data = player_data.dict(exclude_unset=True)
        
        # Validate ability scores if provided
        if 'abilities' in update_data:
            if not validate_ability_scores(update_data['abilities'].dict()):
                raise HTTPException(status_code=400, detail="Invalid ability scores")
        
        for field, value in update_data.items():
            setattr(player, field, value)
        
        db.commit()
        db.refresh(player)
        
        log_action("update_player", player_id, f"Updated player fields: {list(update_data.keys())}")
        return player
    
    @staticmethod
    def delete_player(db: Session, player_id: int) -> bool:
        """Delete a player"""
        player = PlayerService.get_player(db, player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        
        db.delete(player)
        db.commit()
        
        log_action("delete_player", player_id, f"Deleted player '{player.name}'")
        return True
    
    @staticmethod
    def get_player_state(db: Session, player_id: int) -> Dict[str, Any]:
        """Player-centric world state: the player, their current room, who/what
        is there, and their inventory. Powers the interactive CLI clients."""
        player = PlayerService.get_player(db, player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        room = player.room
        others = [p for p in room.players if p.id != player.id] if room else []
        npcs = room.npcs if room else []
        room_items = room.items if room else []

        return {
            "player": {
                "id": player.id, "name": player.name,
                "health": player.health, "max_health": player.max_health,
                "level": player.level, "experience": player.experience,
            },
            "current_room": (
                {"id": room.id, "name": room.name, "description": room.description}
                if room else None
            ),
            "other_players_in_room": [
                {"id": p.id, "name": p.name, "level": p.level} for p in others
            ],
            "npcs_in_room": [
                {"id": n.id, "name": n.name, "description": n.description,
                 "npc_type": n.npc_type, "health": n.health,
                 "max_health": n.max_health, "is_friendly": n.is_friendly}
                for n in npcs
            ],
            "items_in_room": [
                {"id": i.id, "name": i.name, "description": i.description,
                 "item_type": i.item_type, "value": i.value}
                for i in room_items
            ],
            "inventory": [
                {"id": i.id, "name": i.name, "description": i.description,
                 "item_type": i.item_type, "value": i.value, "is_equipped": False}
                for i in player.items
            ],
        }

    @staticmethod
    def get_player_sheet(db: Session, player_id: int) -> schemas.PlayerSheet:
        """Get comprehensive player character sheet"""
        player = PlayerService.get_player(db, player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        
        # Get inventory count
        inventory_count = len(player.items)
        
        # Get location name
        location_name = player.room.name if player.room else "Unknown"
        
        # Create ability scores schema
        abilities = schemas.AbilityScores(
            str=player.str, dex=player.dex, con=player.con,
            intel=player.intel, wis=player.wis, cha=player.cha
        )
        
        # Calculate modifiers
        modifiers = schemas.AbilityModifiers(
            str=player.ability_mod("str"),
            dex=player.ability_mod("dex"),
            con=player.ability_mod("con"),
            intel=player.ability_mod("intel"),
            wis=player.ability_mod("wis"),
            cha=player.ability_mod("cha")
        )
        
        return schemas.PlayerSheet(
            id=player.id,
            name=player.name,
            health=player.health,
            max_health=player.max_health,
            level=player.level,
            experience=player.experience,
            abilities=abilities,
            modifiers=modifiers,
            location_name=location_name,
            inventory_count=inventory_count
        )

# ---------- Room Services ----------
class RoomService:
    """Service for room-related operations"""
    
    @staticmethod
    def create_room(db: Session, room_data: schemas.RoomCreate) -> models.Room:
        """Create a new room"""
        try:
            db_room = models.Room(**room_data.dict())
            db.add(db_room)
            db.commit()
            db.refresh(db_room)
            
            log_action("create_room", 0, f"Created room '{db_room.name}'")
            return db_room
            
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to create room: {str(e)}")
    
    @staticmethod
    def get_room(db: Session, room_id: int) -> Optional[models.Room]:
        """Get room by ID"""
        return db.query(models.Room).filter(models.Room.id == room_id).first()
    
    @staticmethod
    def get_rooms(db: Session, skip: int = 0, limit: int = 100) -> List[models.Room]:
        """Get list of rooms with pagination"""
        return db.query(models.Room).offset(skip).limit(limit).all()
    
    @staticmethod
    def get_room_state(db: Session, room_id: int) -> Dict[str, Any]:
        """Get complete room state including players, NPCs, and items"""
        room = RoomService.get_room(db, room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        return {
            "room": dict_from_model(room),
            "players": [dict_from_model(p) for p in room.players],
            "npcs": [dict_from_model(n) for n in room.npcs],
            "items": [dict_from_model(i) for i in room.items]
        }

# ---------- Item Services ----------
class ItemService:
    """Service for item-related operations"""
    
    @staticmethod
    def create_item(db: Session, item_data: schemas.ItemCreate) -> models.Item:
        """Create a new item"""
        try:
            db_item = models.Item(**item_data.dict())
            db.add(db_item)
            db.commit()
            db.refresh(db_item)
            
            log_action("create_item", 0, f"Created item '{db_item.name}'")
            return db_item
            
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to create item: {str(e)}")
    
    @staticmethod
    def get_item(db: Session, item_id: int) -> Optional[models.Item]:
        """Get item by ID"""
        return db.query(models.Item).filter(models.Item.id == item_id).first()
    
    @staticmethod
    def get_items(db: Session, skip: int = 0, limit: int = 100) -> List[models.Item]:
        """Get list of items with pagination"""
        return db.query(models.Item).offset(skip).limit(limit).all()
    
    @staticmethod
    def move_item(db: Session, item_id: int, new_room_id: Optional[int], new_player_id: Optional[int]) -> models.Item:
        """Move an item to a new location"""
        item = ItemService.get_item(db, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        if not item.is_movable:
            raise HTTPException(status_code=400, detail="Item cannot be moved")
        
        item.room_id = new_room_id
        item.player_id = new_player_id
        db.commit()
        db.refresh(item)
        
        log_action("move_item", 0, f"Moved item '{item.name}' to room {new_room_id} or player {new_player_id}")
        return item

# ---------- NPC Services ----------
class NpcService:
    """Service for NPC-related operations"""
    
    @staticmethod
    def create_npc(db: Session, npc_data: schemas.NpcCreate) -> models.Npc:
        """Create a new NPC"""
        try:
            # Flatten the nested abilities object onto the model's columns
            # (AbilityScores fields map 1:1 to str/dex/con/intel/wis/cha).
            npc_dict = npc_data.dict()
            abilities = npc_dict.pop('abilities', None)
            if abilities:
                npc_dict.update(abilities)

            db_npc = models.Npc(**npc_dict)
            db.add(db_npc)
            db.commit()
            db.refresh(db_npc)
            
            log_action("create_npc", 0, f"Created NPC '{db_npc.name}'")
            return db_npc
            
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to create NPC: {str(e)}")
    
    @staticmethod
    def get_npc(db: Session, npc_id: int) -> Optional[models.Npc]:
        """Get NPC by ID"""
        return db.query(models.Npc).filter(models.Npc.id == npc_id).first()
    
    @staticmethod
    def get_npcs(db: Session, skip: int = 0, limit: int = 100) -> List[models.Npc]:
        """Get list of NPCs with pagination"""
        return db.query(models.Npc).offset(skip).limit(limit).all()
    
    @staticmethod
    def get_npc_sheet(db: Session, npc_id: int) -> schemas.NpcSheet:
        """Get comprehensive NPC character sheet"""
        npc = NpcService.get_npc(db, npc_id)
        if not npc:
            raise HTTPException(status_code=404, detail="NPC not found")
        
        # Get location name
        location_name = npc.room.name if npc.room else "Unknown"
        
        # Create ability scores schema
        abilities = schemas.AbilityScores(
            str=npc.str, dex=npc.dex, con=npc.con,
            intel=npc.intel, wis=npc.wis, cha=npc.cha
        )
        
        # Calculate modifiers
        modifiers = schemas.AbilityModifiers(
            str=npc.ability_mod("str"),
            dex=npc.ability_mod("dex"),
            con=npc.ability_mod("con"),
            intel=npc.ability_mod("intel"),
            wis=npc.ability_mod("wis"),
            cha=npc.ability_mod("cha")
        )
        
        return schemas.NpcSheet(
            id=npc.id,
            name=npc.name,
            description=npc.description,
            npc_type=npc.npc_type,
            combat_enabled=npc.combat_enabled,
            health=npc.health,
            max_health=npc.max_health,
            abilities=abilities,
            modifiers=modifiers,
            location_name=location_name
        )

# ---------- NPC Reaction Services ----------
class NpcReactionService:
    """Service for an NPC's reaction toward a specific player."""

    @staticmethod
    def get_reaction(db: Session, npc_id: int, player_id: int) -> Optional[models.NpcReaction]:
        """Return the reaction row, or None if it doesn't exist yet."""
        return (
            db.query(models.NpcReaction)
            .filter_by(npc_id=npc_id, player_id=player_id)
            .first()
        )

    @staticmethod
    def get_or_create_reaction(db: Session, npc_id: int, player_id: int) -> models.NpcReaction:
        """Return the reaction, creating a neutral (all-zero) one if absent.

        Validates that both the NPC and player exist (404 otherwise).
        """
        if not NpcService.get_npc(db, npc_id):
            raise HTTPException(status_code=404, detail="NPC not found")
        if not PlayerService.get_player(db, player_id):
            raise HTTPException(status_code=404, detail="Player not found")

        reaction = NpcReactionService.get_reaction(db, npc_id, player_id)
        if reaction is None:
            reaction = models.NpcReaction(npc_id=npc_id, player_id=player_id)
            db.add(reaction)
            db.commit()
            db.refresh(reaction)
        return reaction

    @staticmethod
    def update_reaction(db: Session, npc_id: int, player_id: int,
                        data: schemas.NpcReactionUpdate) -> models.NpcReaction:
        """Apply a partial update to the reaction (creating it if absent)."""
        reaction = NpcReactionService.get_or_create_reaction(db, npc_id, player_id)
        for field, value in data.dict(exclude_unset=True).items():
            setattr(reaction, field, value)
        db.commit()
        db.refresh(reaction)
        return reaction


# ---------- Room Exit Services ----------
class RoomExitService:
    """Service for room connections (exits)."""

    @staticmethod
    def get_exits(db: Session, room_id: int) -> List[models.RoomExit]:
        return db.query(models.RoomExit).filter_by(from_room_id=room_id).all()

    @staticmethod
    def get_exit(db: Session, room_id: int, direction: str) -> Optional[models.RoomExit]:
        return (
            db.query(models.RoomExit)
            .filter_by(from_room_id=room_id, direction=directions.normalize(direction))
            .first()
        )

    @staticmethod
    def create_exit(db: Session, from_room_id: int, data: schemas.RoomExitCreate) -> models.RoomExit:
        direction = directions.normalize(data.direction)
        if not directions.is_valid(direction):
            raise HTTPException(status_code=400, detail=f"Invalid direction: {data.direction}")
        if from_room_id == data.to_room_id:
            raise HTTPException(status_code=400, detail="An exit cannot lead back to the same room")
        if not RoomService.get_room(db, from_room_id):
            raise HTTPException(status_code=404, detail="Source room not found")
        if not RoomService.get_room(db, data.to_room_id):
            raise HTTPException(status_code=404, detail="Destination room not found")
        if data.key_item_id is not None and not ItemService.get_item(db, data.key_item_id):
            raise HTTPException(status_code=404, detail="Key item not found")
        if RoomExitService.get_exit(db, from_room_id, direction):
            raise HTTPException(status_code=409, detail=f"Room {from_room_id} already has a '{direction}' exit")

        exit_row = models.RoomExit(
            from_room_id=from_room_id, to_room_id=data.to_room_id, direction=direction,
            description=data.description or "", is_locked=data.is_locked, key_item_id=data.key_item_id,
        )
        db.add(exit_row)

        # Auto-create the paired return exit for two-way connections
        if data.bidirectional:
            rev = directions.reverse(direction)
            if rev and not RoomExitService.get_exit(db, data.to_room_id, rev):
                db.add(models.RoomExit(
                    from_room_id=data.to_room_id, to_room_id=from_room_id, direction=rev,
                    description=data.description or "", is_locked=data.is_locked, key_item_id=data.key_item_id,
                ))

        db.commit()
        db.refresh(exit_row)
        log_action("create_exit", from_room_id, f"{direction} -> room {data.to_room_id}")
        return exit_row

    @staticmethod
    def delete_exit(db: Session, from_room_id: int, direction: str, bidirectional: bool = False) -> bool:
        direction = directions.normalize(direction)
        exit_row = RoomExitService.get_exit(db, from_room_id, direction)
        if not exit_row:
            raise HTTPException(status_code=404, detail="Exit not found")
        to_room_id = exit_row.to_room_id
        db.delete(exit_row)
        if bidirectional:
            rev = directions.reverse(direction)
            rev_row = RoomExitService.get_exit(db, to_room_id, rev)
            if rev_row:
                db.delete(rev_row)
        db.commit()
        return True


# ---------- Game Action Services ----------
class GameActionService:
    """Service for game action processing"""
    
    @staticmethod
    def perform_action(db: Session, action_request: schemas.ActionRequest) -> schemas.ActionResponse:
        """Process a game action and return the result"""
        player = PlayerService.get_player(db, action_request.player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        
        action_type = action_request.action_type.lower()
        
        if action_type == "move":
            return GameActionService._handle_move(db, player, action_request)
        elif action_type == "pickup":
            return GameActionService._handle_pickup(db, player, action_request)
        elif action_type == "drop":
            return GameActionService._handle_drop(db, player, action_request)
        elif action_type == "use":
            return GameActionService._handle_use(db, player, action_request)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action type: {action_type}")
    
    @staticmethod
    def _handle_move(db: Session, player: models.Player, action_request: schemas.ActionRequest) -> schemas.ActionResponse:
        """Handle player movement"""
        if not action_request.target_id:
            raise HTTPException(status_code=400, detail="Target room ID required for move action")
        
        room = RoomService.get_room(db, action_request.target_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # Update player location
        old_room_id = player.room_id
        player.room_id = room.id
        db.commit()
        
        log_action("move", player.id, f"Moved from room {old_room_id} to room {room.id}")
        
        return schemas.ActionResponse(
            success=True,
            message=f"Player {player.name} moved to {room.name}",
            player_state=dict_from_model(player),
            room_state=dict_from_model(room)
        )
    
    @staticmethod
    def _handle_pickup(db: Session, player: models.Player, action_request: schemas.ActionRequest) -> schemas.ActionResponse:
        """Handle item pickup"""
        if not action_request.target_id:
            raise HTTPException(status_code=400, detail="Target item ID required for pickup action")
        
        item = ItemService.get_item(db, action_request.target_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        if not item.can_pickup():
            raise HTTPException(status_code=400, detail="Item cannot be picked up")
        
        if item.room_id != player.room_id:
            raise HTTPException(status_code=400, detail="Item is not in the same room")
        
        # Move item to player
        item.room_id = None
        item.player_id = player.id
        db.commit()
        
        log_action("pickup", player.id, f"Picked up item '{item.name}'")
        
        return schemas.ActionResponse(
            success=True,
            message=f"Player {player.name} picked up {item.name}",
            player_state=dict_from_model(player),
            target_state=dict_from_model(item)
        )
    
    @staticmethod
    def _handle_drop(db: Session, player: models.Player, action_request: schemas.ActionRequest) -> schemas.ActionResponse:
        """Handle item drop"""
        if not action_request.target_id:
            raise HTTPException(status_code=400, detail="Target item ID required for drop action")
        
        item = ItemService.get_item(db, action_request.target_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        if item.player_id != player.id:
            raise HTTPException(status_code=400, detail="Item is not owned by player")
        
        # Move item to room
        item.player_id = None
        item.room_id = player.room_id
        db.commit()
        
        log_action("drop", player.id, f"Dropped item '{item.name}'")
        
        return schemas.ActionResponse(
            success=True,
            message=f"Player {player.name} dropped {item.name}",
            player_state=dict_from_model(player),
            target_state=dict_from_model(item)
        )
    
    @staticmethod
    def _handle_use(db: Session, player: models.Player, action_request: schemas.ActionRequest) -> schemas.ActionResponse:
        """Handle item usage"""
        if not action_request.target_id:
            raise HTTPException(status_code=400, detail="Target item ID required for use action")
        
        item = ItemService.get_item(db, action_request.target_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        if not item.is_usable:
            raise HTTPException(status_code=400, detail="Item is not usable")
        
        if item.player_id != player.id:
            raise HTTPException(status_code=400, detail="Item is not owned by player")
        
        log_action("use", player.id, f"Used item '{item.name}'")
        
        return schemas.ActionResponse(
            success=True,
            message=f"Player {player.name} used {item.name}",
            player_state=dict_from_model(player),
            target_state=dict_from_model(item)
        )
