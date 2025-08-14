# FastAPI Game API

A FastAPI-based RPG game API with SQLite database, SQLAlchemy models, and D&D-style character progression. Features include ability scores, NPC reactions, enhanced item system, and real-time WebSocket multiplayer support.

## Features

- **D&D-Style Character System**: Players and NPCs have STR, DEX, CON, INT, WIS, CHA ability scores with automatic modifiers
- **Player Management**: Create, read, and manage player characters with character sheets
- **Room System**: Navigate between different game locations
- **Enhanced Item System**: Items with movable/usable flags, pick up, drop, and use items
- **Advanced NPC System**: NPCs with ability scores, combat flags, and dynamic reactions toward players
- **NPC Reaction System**: Track NPC feelings (threat, attraction, arousal, aggression) toward players
- **Action System**: Perform game actions like moving, picking up items, using items, etc.
- **State Management**: Get comprehensive player state information
- **Real-time Multiplayer**: WebSocket support for live game updates
- **Interactive CLI**: Natural language command interface
- **Chat System**: Global, room, and private messaging

## Models

- **Player**: Character with health, level, experience, location, and D&D ability scores
- **Room**: Game locations with descriptions and accessibility
- **Item**: Objects with movable/usable flags that can be picked up, used, or found in rooms
- **Npc**: Non-player characters with ability scores, combat flags, and behaviors
- **NpcReaction**: Tracks NPC emotional responses toward specific players

## API Endpoints

### Core CRUD Operations
- `POST /players/` - Create a new player
- `GET /players/` - List all players
- `GET /players/{player_id}` - Get player details
- `POST /rooms/` - Create a new room
- `GET /rooms/` - List all rooms
- `GET /rooms/{room_id}` - Get room details
- `POST /items/` - Create a new item
- `GET /items/` - List all items
- `GET /items/{item_id}` - Get item details
- `POST /npcs/` - Create a new NPC
- `GET /npcs/` - List all NPCs
- `GET /npcs/{npc_id}` - Get NPC details

### New Character Sheet Endpoints
- `GET /players/{player_id}/sheet` - Get detailed character sheet with ability scores and modifiers
- `GET /npcs/{npc_id}/sheet` - Get NPC character sheet with ability scores and modifiers

### NPC Reaction System
- `GET /npcs/{npc_id}/reaction/{player_id}` - Get NPC's current reactions toward a player
- `PATCH /npcs/{npc_id}/reaction/{player_id}` - Update NPC reactions toward a player

### Game Actions
- `POST /action` - Perform game actions (move, pickup, drop, use, etc.)
- `GET /state/{player_id}` - Get comprehensive player state

### Chat System
- `POST /chat/send` - Send chat messages (global, room, private)
- `GET /chat/history/{chat_type}` - Get chat history

### WebSocket
- `WS /ws/{player_id}` - Real-time WebSocket connection for live updates

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the server:
```bash
uvicorn main:app --reload
```

Or run directly:
```bash
python main.py
```

3. Access the API documentation:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Database

The application uses SQLite with SQLAlchemy ORM. The database file (`game.db`) will be created automatically when you first run the application.

## Example Usage

### Create a Room
```bash
curl -X POST "http://localhost:8000/rooms/" \
     -H "Content-Type: application/json" \
     -d '{"name": "Tavern", "description": "A cozy tavern with a fireplace"}'
```

### Create a Player
```bash
curl -X POST "http://localhost:8000/players/" \
     -H "Content-Type: application/json" \
     -d '{"name": "Hero", "room_id": 1}'
```

### Get Character Sheet
```bash
curl "http://localhost:8000/players/1/sheet"
```

### Get NPC Reactions
```bash
curl "http://localhost:8000/npcs/1/reaction/1"
```

### Move Player
```bash
curl -X POST "http://localhost:8000/action" \
     -H "Content-Type: application/json" \
     -d '{"player_id": 1, "action_type": "move", "target_type": "room", "target_id": 2}'
```

### Get Player State
```bash
curl "http://localhost:8000/state/1"
```

## Project Structure

```
app/
├── main.py              # FastAPI application and endpoints
├── models.py            # SQLAlchemy database models with ability scores
├── schemas.py           # Pydantic schemas for request/response
├── database.py          # Database configuration and session management
├── seed.py              # Database seeding with sample data
├── cli.py               # Interactive command-line interface
├── websocket_cli.py     # WebSocket-enabled CLI for multiplayer
├── websocket_manager.py # WebSocket connection management
├── chat_system.py       # Chat functionality
├── llm_npcs.py          # AI-powered NPC system
├── ollama_integration.py # Ollama LLM integration
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

## Development

The application includes advanced game logic for:
- D&D-style character progression with ability scores
- Dynamic NPC reactions and relationships
- Enhanced item system with usage flags
- Real-time multiplayer via WebSockets
- AI-powered NPC interactions
- Chat system with multiple channels

You can extend the system to add more game mechanics like:
- Combat system using ability scores
- Skill checks and saving throws
- Quest system with NPC reactions
- Item crafting and enchantments
- More complex social interactions

## Database Seeding

The project includes a `seed.py` script that populates the database with initial sample data:

```bash
# Seed the database with sample data
python seed.py

# Clear all data from the database
python seed.py --clear
```

The seed script creates:
- **Rooms**: "Foyer" and "Great Hall" - Grand entrance areas
- **Player**: "Bryan" - A level 1 player with default ability scores
- **NPCs**: 
  - "Caretaker" - Combat-enabled NPC with WIS 12, CHA 8
  - "Innkeeper" - Non-combat NPC with WIS 12, CHA 14
- **Items**: 
  - "Rusty Key" - Movable and usable key item
  - "Sturdy Stool" - Non-movable but usable furniture
- **NPC Reactions**: Initial reaction values for Caretaker toward Bryan

## Quick Start

1. Create and activate virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Seed the database:
```bash
python seed.py
```

4. Run the server:
```bash
python main.py
# or
uvicorn main:app --reload
```

5. Test the API:
```bash
# Get character sheet
curl "http://localhost:8000/players/1/sheet"

# Get player state
curl "http://localhost:8000/state/1"

# Get NPC reactions
curl "http://localhost:8000/npcs/1/reaction/1"
```

## Interactive CLI

The project includes two interactive command-line interfaces:

### Standard CLI (`cli.py`)
```bash
# Start the CLI
python cli.py

# Start with a different player ID
python cli.py --player 2

# Connect to a different server
python cli.py --url http://localhost:8001
```

### WebSocket CLI (`websocket_cli.py`)
```bash
# Start the WebSocket CLI for real-time multiplayer
python websocket_cli.py --player 1
```

### Available Commands

**Game Commands:**
- `/look` - Look around the current room
- `/go <room_name>` - Move to a different room
- `/take <item_name>` - Pick up an item
- `/drop <item_name>` - Drop an item from inventory
- `/use <item_name>` - Use an item (from inventory or room)
- `/inventory` - Show your inventory
- `/status` - Show player status
- `/sheet` - Show character sheet with D&D-style ability scores
- `/inspect <npc_name>` - Inspect an NPC and see their reactions toward you

**Utility Commands:**
- `/rooms` - List all available rooms
- `/items` - List all items
- `/npcs` - List all NPCs
- `/player <id>` - Switch to a different player
- `/help` - Show help information
- `/quit` - Exit the game

### Example CLI Session

```
==================================================
 Welcome to the Game CLI! 
==================================================

[1]> /sheet
==================================================
 Character Sheet 
==================================================
Bryan (Lvl 1)  HP 10/10
STR 10 (+0)  DEX 10 (+0)  CON 10 (+0)
INT 10 (+0)  WIS 10 (+0)  CHA 10 (+0)

[1]> /look
==================================================
 Looking around Foyer 
==================================================
A grand entrance hall.

Items you can see:
  • Rusty Key - Pitted iron, still turns.
  • Sturdy Stool - It wobbles but holds.

People you can see:
  • Caretaker - A curt, watchful presence.
  • Innkeeper - Polite, harried, not interested in brawls.

[1]> /inspect Caretaker
==================================================
 Caretaker (caretaker) 
==================================================
A curt, watchful presence.
Combat: Yes
STR 10 (+0)  DEX 10 (+0)  CON 10 (+0)
INT 10 (+0)  WIS 12 (+1)  CHA 8 (-1)
Reactions → threat:10 attraction:5 arousal:0 aggression:5

[1]> /use key
✅ You use the Rusty Key.
```

## D&D-Style Ability Scores

The game features a complete D&D-style ability score system:

- **STR (Strength)**: Physical power and athletic training
- **DEX (Dexterity)**: Agility, reflexes, balance, and precision
- **CON (Constitution)**: Health, stamina, and vital force
- **INT (Intelligence)**: Mental acuity, accuracy of recall, and ability to reason
- **WIS (Wisdom)**: Awareness of surroundings and intuition
- **CHA (Charisma)**: Ability to interact effectively with others

**Ability Modifiers**: Each ability score has a modifier calculated as `(score - 10) // 2`
- Score 10-11: +0 modifier
- Score 12-13: +1 modifier
- Score 14-15: +2 modifier
- Score 8-9: -1 modifier
- Score 6-7: -2 modifier

## NPC Reaction System

NPCs have dynamic emotional responses toward players tracked across four dimensions:

- **Threat** (0-100): How dangerous the NPC perceives the player
- **Attraction** (0-100): How appealing or interesting the NPC finds the player
- **Arousal** (0-100): How excited or stimulated the NPC is by the player
- **Aggression** (0-100): How likely the NPC is to attack or confront the player

Reactions automatically update based on player actions and can be manually adjusted via the API.

## Enhanced Item System

Items now have additional properties:

- **is_movable**: Whether the item can be picked up and carried
- **is_usable**: Whether the item can be used/activated
- **item_type**: Classification (weapon, armor, key, furniture, etc.)
- **value**: Monetary or gameplay value

This allows for more realistic item interactions - furniture stays in place but can be used, keys are portable and functional, etc.

## WebSocket Multiplayer

The WebSocket system provides real-time updates for:

- Player movement between rooms
- Item pickups and drops
- NPC interactions
- Chat messages
- Game state changes

Players automatically receive notifications when others join/leave their room or perform actions.

## Chat System

The game includes a comprehensive chat system:

- **Global Chat**: Messages visible to all players
- **Room Chat**: Messages visible only to players in the same room
- **Private Chat**: Direct messages between specific players
- **NPC Chat**: AI-powered conversations with NPCs

Chat history is preserved and can be retrieved via API endpoints.

The CLI provides a user-friendly way to interact with the game without needing to remember API endpoints or JSON structures, while the WebSocket CLI adds real-time multiplayer capabilities.
