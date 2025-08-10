# FastAPI Game API

A FastAPI-based game API with SQLite database and SQLAlchemy models for managing players, rooms, items, and NPCs.

## Features

- **Player Management**: Create, read, and manage player characters
- **Room System**: Navigate between different game locations
- **Item System**: Pick up, drop, and manage inventory items
- **NPC System**: Interact with non-player characters
- **Action System**: Perform game actions like moving, picking up items, etc.
- **State Management**: Get comprehensive player state information

## Models

- **Player**: Character with health, level, experience, and location
- **Room**: Game locations with descriptions and accessibility
- **Item**: Objects that can be picked up, equipped, or found in rooms
- **Npc**: Non-player characters with different types and behaviors

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

### Game Actions
- `POST /action` - Perform game actions (move, pickup, drop, etc.)
- `GET /state/{player_id}` - Get comprehensive player state

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
├── main.py          # FastAPI application and endpoints
├── models.py        # SQLAlchemy database models
├── schemas.py       # Pydantic schemas for request/response
├── database.py      # Database configuration and session management
├── requirements.txt # Python dependencies
└── README.md        # This file
```

## Development

The application includes basic game logic for:
- Moving between rooms
- Picking up and dropping items
- Basic validation and error handling

You can extend the action system in the `/action` endpoint to add more game mechanics like:
- Combat system
- Item usage
- NPC interactions
- Quest system
- More complex movement rules

## Database Seeding

The project includes a `seed.py` script that populates the database with initial sample data:

```bash
# Seed the database with sample data
python seed.py

# Clear all data from the database
python seed.py --clear
```

The seed script creates:
- **Room**: "The Rusty Tavern" - A cozy tavern with fireplace and tables
- **Player**: "Hero" - A level 1 player starting in the tavern
- **Item**: "Iron Sword" - A weapon found in the tavern
- **NPC**: "Old Tom" - A friendly innkeeper merchant

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
# Get player state
curl "http://localhost:8000/state/1"

# Pick up an item
curl -X POST "http://localhost:8000/action" \
     -H "Content-Type: application/json" \
     -d '{"player_id": 1, "action_type": "pickup", "target_type": "item", "target_id": 1}'
```

## Interactive CLI

The project includes an interactive command-line interface (`cli.py`) that provides a natural language interface to the game:

```bash
# Start the CLI
python cli.py

# Start with a different player ID
python cli.py --player 2

# Connect to a different server
python cli.py --url http://localhost:8001
```

### Available Commands

**Game Commands:**
- `/look` - Look around the current room
- `/go <room_name>` - Move to a different room
- `/take <item_name>` - Pick up an item
- `/drop <item_name>` - Drop an item from inventory
- `/inventory` - Show your inventory
- `/status` - Show player status

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

[1]> /look
==================================================
 Looking around The Rusty Tavern 
==================================================
A cozy tavern with a crackling fireplace, wooden tables, and the smell of ale in the air...

[1]> /take sword
✅ Picked up Iron Sword

[1]> /inventory
==================================================
 Inventory 
==================================================
  • Iron Sword - A well-crafted iron sword with a leather-wrapped hilt...
    Type: weapon, Value: 50

[1]> /status
==================================================
 Player Status 
==================================================
Name: Hero
Health: 100/100
Level: 1
Experience: 0
Location: The Rusty Tavern
Inventory: 1 items
```

The CLI provides a user-friendly way to interact with the game without needing to remember API endpoints or JSON structures.
