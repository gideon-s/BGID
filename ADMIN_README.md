# Game Database Admin CLI

A comprehensive command-line interface for managing the Game API database. This tool allows you to view, create, and manage all game objects including players, rooms, items, and NPCs.

## Features

- **📊 Database Overview**: Get statistics and counts of all object types
- **👀 Object Inspection**: View detailed information about specific objects
- **➕ Object Creation**: Interactive creation of new game objects with validation
- **🗑️ Object Deletion**: Delete objects (when DELETE endpoints are implemented)
- **🔍 Object Listing**: List all objects of a specific type with formatted output
- **🎨 Colored Output**: Easy-to-read colored terminal output

## Installation

The admin CLI uses the same dependencies as the main game. Make sure you have the virtual environment activated:

```bash
source venv/bin/activate
```

## Usage

### Basic Usage

```bash
# Start the admin CLI
python3 admin.py

# Use a custom server URL
python3 admin.py --url http://localhost:9000

# Show help
python3 admin.py --help
```

### Available Commands

#### Database Management
- `list <type>` - List all objects of a specific type
- `show <type> <id>` - Show detailed information about an object
- `create <type>` - Create a new object of a specific type
- `delete <type> <id>` - Delete an object (when implemented)
- `count <type>` - Count objects of a specific type
- `stats` - Show database statistics

#### Object Types
- `players` - Player characters with stats and abilities
- `rooms` - Game locations and areas
- `items` - Objects that can be picked up and used
- `npcs` - Non-player characters

#### Utility Commands
- `help` - Show detailed help information
- `quit` / `exit` - Exit the admin CLI

### Examples

#### View Database Statistics
```
admin> stats
============================================================
 Database Statistics 
============================================================
ℹ️  Players: 1
ℹ️  Rooms: 2
ℹ️  Items: 2
ℹ️  Npcs: 2

✅ Total objects in database: 7
```

#### List All Players
```
admin> list players
============================================================
 All Players (1 total) 
============================================================
  • ID 1: Bryan (Lvl 1, HP 10/10)
    Room: 1, XP: 0
```

#### List All Rooms
```
admin> list rooms
============================================================
 All Rooms (2 total) 
============================================================
  • ID 1: Foyer
    A grand entrance hall.
    Accessible: Yes

  • ID 2: Great Hall
    A vast chamber with high ceilings.
    Accessible: Yes
```

#### Show Specific Object Details
```
admin> show players 1
============================================================
 Player ID 1 
============================================================
{
  "id": 1,
  "name": "Bryan",
  "room_id": 1,
  "health": 10,
  "max_health": 10,
  "level": 1,
  "experience": 0,
  "str": 10,
  "dex": 10,
  "con": 10,
  "intel": 10,
  "wis": 10,
  "cha": 10
}
```

#### Create a New Room
```
admin> create rooms
============================================================
 Create New Rooms 
============================================================
Enter the following information (press Enter to use defaults):
  name: string (required)
  description: string (required)
  is_accessible: boolean (default: true)

name: Library
description: A quiet room filled with ancient tomes
is_accessible [true]: 

Creating object with the following data:
{
  "name": "Library",
  "description": "A quiet room filled with ancient tomes",
  "is_accessible": true
}

Proceed with creation? (y/N): y
✅ Successfully created rooms with ID 3
```

## Object Schemas

### Players
- **Required**: `name`, `room_id`
- **Defaults**: `health: 10`, `max_health: 10`, `level: 1`, `experience: 0`
- **Abilities**: `str: 10`, `dex: 10`, `con: 10`, `intel: 10`, `wis: 10`, `cha: 10`

### Rooms
- **Required**: `name`, `description`
- **Defaults**: `is_accessible: true`

### Items
- **Required**: `name`, `description`, `item_type`
- **Defaults**: `value: 0`, `is_movable: true`, `is_usable: false`
- **Optional**: `room_id`, `player_id`

### NPCs
- **Required**: `name`, `description`, `npc_type`, `room_id`
- **Defaults**: `is_friendly: false`, `combat_enabled: true`, `health: 8`, `max_health: 8`, `level: 1`
- **Abilities**: `str: 10`, `dex: 10`, `con: 10`, `intel: 10`, `wis: 10`, `cha: 10`

## Tips

1. **Start with `stats`** to get an overview of your database
2. **Use `list <type>`** to see what exists before creating new objects
3. **Use `show <type> <id>`** to examine specific objects in detail
4. **The create command** will prompt for required fields and offer sensible defaults
5. **All commands support tab completion** in most terminals
6. **Use Ctrl+C** to safely exit the CLI

## Error Handling

The admin CLI provides clear error messages for:
- Invalid object types
- Missing required fields
- API connection issues
- Invalid data types
- Server errors

## Future Enhancements

- **DELETE endpoints** - Currently shows a warning that DELETE functionality needs to be implemented in the API
- **Bulk operations** - Create multiple objects at once
- **Data export/import** - Backup and restore database state
- **Advanced filtering** - Search and filter objects by criteria
- **Batch operations** - Modify multiple objects at once

## Troubleshooting

### Connection Issues
If you get connection errors, make sure:
1. The game server is running (`uvicorn main:app --host 127.0.0.1 --port 8000`)
2. The server URL is correct (use `--url` flag if different)
3. The server is accessible from your network

### Permission Issues
Make sure you have:
1. Read/write access to the database
2. Proper API permissions (if using authentication)
3. Network access to the server

### Data Validation Errors
The CLI validates all input data:
1. Required fields must be provided
2. Integers must be valid numbers
3. Booleans accept: `true`, `yes`, `1`, `on` or `false`, `no`, `0`, `off`
4. All other fields are treated as strings

## Contributing

To add support for new object types:
1. Add the type to `self.object_types` in the `GameAdmin` class
2. Define the endpoint and create schema
3. Add handling in the `cmd_list` method for formatted display
4. Test with the CLI

The admin CLI is designed to be easily extensible for new game features!
