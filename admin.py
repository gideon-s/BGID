#!/usr/bin/env python3
"""
Admin CLI for managing the Game API database
Allows viewing, creating, and deleting objects by type
"""
import requests
import json
import sys
import argparse
from typing import Optional, Dict, Any, List

class GameAdmin:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = requests.Session()
        self.running = True
        
        # Object types and their endpoints
        self.object_types = {
            'players': {
                'endpoint': '/players/',
                'create_schema': {
                    'name': 'string',
                    'health': 'integer (default: 10)',
                    'max_health': 'integer (default: 10)',
                    'level': 'integer (default: 1)',
                    'experience': 'integer (default: 0)',
                    'room_id': 'integer (required)',
                    'str': 'integer (default: 10)',
                    'dex': 'integer (default: 10)',
                    'con': 'integer (default: 10)',
                    'intel': 'integer (default: 10)',
                    'wis': 'integer (default: 10)',
                    'cha': 'integer (default: 10)'
                }
            },
            'rooms': {
                'endpoint': '/rooms/',
                'create_schema': {
                    'name': 'string (required)',
                    'description': 'string (required)'
                }
            },
            'items': {
                'endpoint': '/items/',
                'create_schema': {
                    'name': 'string (required)',
                    'description': 'string (required)',
                    'item_type': 'string (required)',
                    'value': 'integer (default: 0)',
                    'room_id': 'integer (optional)',
                    'player_id': 'integer (optional)',
                    'is_movable': 'boolean (default: true)',
                    'is_usable': 'boolean (default: false)'
                }
            },
            'npcs': {
                'endpoint': '/npcs/',
                'create_schema': {
                    'name': 'string (required)',
                    'description': 'string (required)',
                    'npc_type': 'string (required)',
                    'room_id': 'integer (required)',
                    'is_friendly': 'boolean (default: false)',
                    'combat_enabled': 'boolean (default: true)',
                    'health': 'integer (default: 8)',
                    'max_health': 'integer (default: 8)',
                    'level': 'integer (default: 1)',
                    'str': 'integer (default: 10)',
                    'dex': 'integer (default: 10)',
                    'con': 'integer (default: 10)',
                    'intel': 'integer (default: 10)',
                    'wis': 'integer (default: 10)',
                    'cha': 'integer (default: 10)'
                }
            }
        }
        
        # Command patterns
        self.commands = {
            r'^list\s+(\w+)$': self.cmd_list,
            r'^show\s+(\w+)\s+(\d+)$': self.cmd_show,
            r'^create\s+(\w+)$': self.cmd_create,
            r'^delete\s+(\w+)\s+(\d+)$': self.cmd_delete,
            r'^count\s+(\w+)$': self.cmd_count,
            r'^stats$': self.cmd_stats,
            r'^help$': self.cmd_help,
            r'^quit$': self.cmd_quit,
            r'^exit$': self.cmd_quit
        }
    
    def print_colored(self, text: str, color: str = "white"):
        """Print colored text (basic ANSI colors)"""
        colors = {
            "red": "\033[91m",
            "green": "\033[92m",
            "yellow": "\033[93m",
            "blue": "\033[94m",
            "magenta": "\033[95m",
            "cyan": "\033[96m",
            "white": "\033[97m",
            "bold": "\033[1m",
            "reset": "\033[0m"
        }
        
        if color in colors:
            print(f"{colors[color]}{text}{colors['reset']}")
        else:
            print(text)
    
    def print_header(self, text: str):
        """Print a formatted header"""
        print()
        self.print_colored("=" * 60, "cyan")
        self.print_colored(f" {text} ", "cyan")
        self.print_colored("=" * 60, "cyan")
        print()
    
    def print_error(self, message: str):
        """Print an error message"""
        self.print_colored(f"❌ Error: {message}", "red")
    
    def print_success(self, message: str):
        """Print a success message"""
        self.print_colored(f"✅ {message}", "green")
    
    def print_info(self, message: str):
        """Print an info message"""
        self.print_colored(f"ℹ️  {message}", "blue")
    
    def print_warning(self, message: str):
        """Print a warning message"""
        self.print_colored(f"⚠️  {message}", "yellow")
    
    def make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make an HTTP request to the API"""
        try:
            url = f"{self.base_url}{endpoint}"
            if method.upper() == "GET":
                response = self.session.get(url)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data)
            elif method.upper() == "DELETE":
                response = self.session.delete(url)
            else:
                self.print_error(f"Unsupported HTTP method: {method}")
                return None
            
            if response.status_code in [200, 201]:
                return response.json()
            elif response.status_code == 404:
                self.print_error(f"Not found: {endpoint}")
                return None
            else:
                self.print_error(f"API Error: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.ConnectionError:
            self.print_error("Cannot connect to the game server. Make sure it's running on localhost:8000")
            return None
        except Exception as e:
            self.print_error(f"Request failed: {e}")
            return None
    
    def validate_object_type(self, obj_type: str) -> bool:
        """Validate if the object type is supported"""
        if obj_type not in self.object_types:
            self.print_error(f"Unsupported object type: {obj_type}")
            self.print_info(f"Supported types: {', '.join(self.object_types.keys())}")
            return False
        return True
    
    def cmd_list(self, obj_type: str):
        """List all objects of a specific type"""
        if not self.validate_object_type(obj_type):
            return
        
        objects = self.make_request("GET", self.object_types[obj_type]['endpoint'])
        if objects is None:
            return
        
        if not objects:
            self.print_info(f"No {obj_type} found in the database")
            return
        
        self.print_header(f"All {obj_type.title()} ({len(objects)} total)")
        
        for obj in objects:
            if obj_type == 'players':
                print(f"  • ID {obj['id']}: {obj['name']} (Lvl {obj['level']}, HP {obj['health']}/{obj['max_health']})")
                print(f"    Room: {obj.get('room_id', 'None')}, XP: {obj['experience']}")
            elif obj_type == 'rooms':
                print(f"  • ID {obj['id']}: {obj['name']}")
                print(f"    {obj['description']}")
            elif obj_type == 'items':
                location = "Inventory" if obj.get('player_id') else f"Room {obj.get('room_id', 'None')}"
                print(f"  • ID {obj['id']}: {obj['name']} ({obj['item_type']})")
                print(f"    {obj['description']}")
                print(f"    Value: {obj['value']}, Location: {location}")
                print(f"    Movable: {'Yes' if obj.get('is_movable', True) else 'No'}, Usable: {'Yes' if obj.get('is_usable', False) else 'No'}")
            elif obj_type == 'npcs':
                print(f"  • ID {obj['id']}: {obj['name']} ({obj['npc_type']})")
                print(f"    {obj['description']}")
                print(f"    Room: {obj['room_id']}, Health: {obj['health']}/{obj['max_health']}")
                print(f"    Friendly: {'Yes' if obj.get('is_friendly', False) else 'No'}, Combat: {'Yes' if obj.get('combat_enabled', True) else 'No'}")
            print()
    
    def cmd_show(self, obj_type: str, obj_id: str):
        """Show detailed information about a specific object"""
        if not self.validate_object_type(obj_type):
            return
        
        try:
            obj_id_int = int(obj_id)
        except ValueError:
            self.print_error("Object ID must be a number")
            return
        
        endpoint = f"{self.object_types[obj_type]['endpoint'].rstrip('/')}/{obj_id_int}"
        obj = self.make_request("GET", endpoint)
        if obj is None:
            return
        
        self.print_header(f"{obj_type.title()} ID {obj_id_int}")
        print(json.dumps(obj, indent=2))
    
    def cmd_create(self, obj_type: str):
        """Create a new object of the specified type"""
        if not self.validate_object_type(obj_type):
            return
        
        schema = self.object_types[obj_type]['create_schema']
        self.print_header(f"Create New {obj_type.title()}")
        print("Enter the following information (press Enter to use defaults):")
        print()
        
        # Show schema
        for field, description in schema.items():
            print(f"  {field}: {description}")
        print()
        
        # Collect data
        data = {}
        for field, description in schema.items():
            if 'default:' in description:
                default_value = description.split('default:')[1].strip().split(')')[0]
                if default_value == 'true':
                    default_value = True
                elif default_value == 'false':
                    default_value = False
                elif default_value.isdigit():
                    default_value = int(default_value)
                else:
                    default_value = default_value.strip("'")
                
                user_input = input(f"{field} [{default_value}]: ").strip()
                if user_input:
                    # Try to convert to appropriate type
                    if isinstance(default_value, bool):
                        data[field] = user_input.lower() in ['true', 'yes', '1', 'on']
                    elif isinstance(default_value, int):
                        try:
                            data[field] = int(user_input)
                        except ValueError:
                            self.print_error(f"Invalid integer for {field}")
                            return
                    else:
                        data[field] = user_input
                else:
                    data[field] = default_value
            else:
                user_input = input(f"{field}: ").strip()
                if not user_input:
                    self.print_error(f"{field} is required")
                    return
                
                # Handle required fields
                if 'integer' in description:
                    try:
                        data[field] = int(user_input)
                    except ValueError:
                        self.print_error(f"Invalid integer for {field}")
                        return
                else:
                    data[field] = user_input
        
        # Confirm creation
        print()
        self.print_info("Creating object with the following data:")
        print(json.dumps(data, indent=2))
        print()
        
        confirm = input("Proceed with creation? (y/N): ").strip().lower()
        if confirm not in ['y', 'yes']:
            self.print_info("Creation cancelled")
            return
        
        # Create the object
        result = self.make_request("POST", self.object_types[obj_type]['endpoint'], data)
        if result:
            self.print_success(f"Successfully created {obj_type} with ID {result.get('id', 'unknown')}")
        else:
            self.print_error(f"Failed to create {obj_type}")
    
    def cmd_delete(self, obj_type: str, obj_id: str):
        """Delete an object of the specified type"""
        if not self.validate_object_type(obj_type):
            return
        
        try:
            obj_id_int = int(obj_id)
        except ValueError:
            self.print_error("Object ID must be a number")
            return
        
        # First, show the object to confirm deletion
        endpoint = f"{self.object_types[obj_type]['endpoint'].rstrip('/')}/{obj_id_int}"
        obj = self.make_request("GET", endpoint)
        if obj is None:
            return
        
        self.print_header(f"Delete {obj_type.title()} ID {obj_id_int}")
        print("Object to delete:")
        print(json.dumps(obj, indent=2))
        print()
        
        confirm = input("Are you sure you want to delete this object? (y/N): ").strip().lower()
        if confirm not in ['y', 'yes']:
            self.print_info("Deletion cancelled")
            return
        
        # Note: The current API doesn't have DELETE endpoints, so we'll show a message
        self.print_warning("DELETE functionality not yet implemented in the API")
        self.print_info("You would need to add DELETE endpoints to the API first")
    
    def cmd_count(self, obj_type: str):
        """Count objects of a specific type"""
        if not self.validate_object_type(obj_type):
            return
        
        objects = self.make_request("GET", self.object_types[obj_type]['endpoint'])
        if objects is None:
            return
        
        count = len(objects)
        self.print_info(f"Total {obj_type}: {count}")
    
    def cmd_stats(self, *args):
        """Show database statistics"""
        self.print_header("Database Statistics")
        
        total_stats = {}
        for obj_type in self.object_types:
            objects = self.make_request("GET", self.object_types[obj_type]['endpoint'])
            if objects is not None:
                count = len(objects)
                total_stats[obj_type] = count
                self.print_info(f"{obj_type.title()}: {count}")
            else:
                total_stats[obj_type] = 0
                self.print_error(f"Could not retrieve {obj_type} count")
        
        print()
        total_objects = sum(total_stats.values())
        self.print_success(f"Total objects in database: {total_objects}")
    
    def cmd_help(self, *args):
        """Show help information"""
        self.print_header("Admin CLI Help")
        print("Available Commands:")
        print()
        print("📊 Database Management:")
        print("  list <type>                    - List all objects of a specific type")
        print("  show <type> <id>              - Show detailed information about an object")
        print("  create <type>                  - Create a new object of a specific type")
        print("  delete <type> <id>            - Delete an object (when implemented)")
        print("  count <type>                   - Count objects of a specific type")
        print("  stats                          - Show database statistics")
        print()
        print("🔧 Object Types:")
        for obj_type in self.object_types:
            print(f"  {obj_type:<15} - {obj_type.title()}")
        print()
        print("📝 Examples:")
        print("  list players                   - List all players")
        print("  show rooms 1                   - Show details of room ID 1")
        print("  create rooms                   - Create a new room")
        print("  count items                    - Count total items")
        print("  stats                          - Show all statistics")
        print()
        print("💡 Tips:")
        print("  - Use 'list <type>' to see what exists before creating")
        print("  - Use 'show <type> <id>' to examine specific objects")
        print("  - The create command will prompt for required fields")
        print("  - Use 'stats' to get an overview of the database")
        print()
        print("Other Commands:")
        print("  help                           - Show this help")
        print("  quit / exit                    - Exit the admin CLI")
    
    def cmd_quit(self, *args):
        """Quit the admin CLI"""
        self.print_info("Goodbye!")
        self.running = False
    
    def process_command(self, command: str):
        """Process a command and execute the appropriate action"""
        command = command.strip()
        if not command:
            return
        
        # Try to match the command with patterns
        import re
        for pattern, handler in self.commands.items():
            match = re.match(pattern, command)
            if match:
                try:
                    handler(*match.groups())
                    return
                except Exception as e:
                    self.print_error(f"Error executing command: {e}")
                    return
        
        # If no pattern matches
        self.print_error(f"Unknown command: {command}. Type 'help' for available commands.")
    
    def run(self):
        """Main CLI loop"""
        self.print_header("Game Database Admin CLI")
        self.print_info("Type 'help' to see available commands")
        self.print_info("Type 'quit' to exit")
        print()
        
        # Show initial stats
        self.cmd_stats()
        
        while self.running:
            try:
                command = input("\nadmin> ").strip()
                if command:
                    self.process_command(command)
            except KeyboardInterrupt:
                print()
                self.cmd_quit()
            except EOFError:
                self.cmd_quit()

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Admin CLI for managing the Game API database")
    parser.add_argument("--url", default="http://localhost:8000", 
                       help="Base URL for the Game API (default: http://localhost:8000)")
    
    args = parser.parse_args()
    
    admin = GameAdmin(args.url)
    
    try:
        admin.run()
    except KeyboardInterrupt:
        print("\nGoodbye!")

if __name__ == "__main__":
    main()
