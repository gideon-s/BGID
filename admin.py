"""
Admin CLI for managing the RPG Game database
"""
import requests
import json
import sys
from typing import Dict, Any, Optional, List
from config import HOST, PORT

class GameAdmin:
    """Administrative interface for managing the RPG Game database"""
    
    def __init__(self):
        """Initialize the admin interface"""
        self.base_url = f"http://{HOST}:{PORT}"
        self.session = requests.Session()
        
        # Define object types and their API endpoints
        self.object_types = {
            'players': {
                'endpoint': '/players/',
                'create_schema': {
                    'name': 'string (required)',
                    'room_id': 'integer (required)',
                    'health': 'integer (default: 10)',
                    'max_health': 'integer (default: 10)',
                    'level': 'integer (default: 1)',
                    'experience': 'integer (default: 0)',
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
                    'item_type': 'string (default: generic)',
                    'value': 'integer (default: 0)',
                    'room_id': 'integer (optional)',
                    'player_id': 'integer (optional)',
                    'is_movable': 'boolean (default: true)',
                    'is_usable': 'boolean (default: false)',
                    'is_equippable': 'boolean (default: false)'
                }
            },
            'npcs': {
                'endpoint': '/npcs/',
                'create_schema': {
                    'name': 'string (required)',
                    'description': 'string (required)',
                    'npc_type': 'string (default: generic)',
                    'room_id': 'integer (required)',
                    'combat_enabled': 'boolean (default: true)',
                    'is_friendly': 'boolean (default: false)',
                    'health': 'integer (default: 8)',
                    'max_health': 'integer (default: 8)',
                    'str': 'integer (default: 10)',
                    'dex': 'integer (default: 10)',
                    'con': 'integer (default: 10)',
                    'intel': 'integer (default: 10)',
                    'wis': 'integer (default: 10)',
                    'cha': 'integer (default: 10)'
                }
            }
        }
        
        # Command mapping
        self.commands = {
            'list': self.cmd_list,
            'show': self.cmd_show,
            'create': self.cmd_create,
            'delete': self.cmd_delete,
            'count': self.cmd_count,
            'stats': self.cmd_stats,
            'help': self.cmd_help,
            'quit': self.cmd_quit,
            'exit': self.cmd_quit
        }
    
    def run(self):
        """Main admin interface loop"""
        self.print_banner()
        
        while True:
            try:
                command = input("\nadmin> ").strip().lower()
                if not command:
                    continue
                
                # Parse command and arguments
                parts = command.split()
                cmd = parts[0]
                args = parts[1:] if len(parts) > 1 else []
                
                # Execute command
                if cmd in self.commands:
                    self.commands[cmd](args)
                else:
                    print(f"❌ Unknown command: {cmd}")
                    print("   Type 'help' to see available commands")
                    
            except KeyboardInterrupt:
                print("\n\nℹ️  Use 'quit' or 'exit' to exit the admin interface")
            except EOFError:
                print("\n\nℹ️  Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    def print_banner(self):
        """Display the admin interface banner"""
        print("=" * 60)
        print(" Game Database Admin CLI ")
        print("=" * 60)
        print("\nℹ️  Type 'help' to see available commands")
        print("ℹ️  Type 'quit' to exit")
    
    def api_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make an API request and return the response"""
        try:
            url = f"{self.base_url}{endpoint}"
            
            if method.upper() == 'GET':
                response = self.session.get(url)
            elif method.upper() == 'POST':
                response = self.session.post(url, json=data)
            elif method.upper() == 'PUT':
                response = self.session.put(url, json=data)
            elif method.upper() == 'DELETE':
                response = self.session.delete(url)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            
            if response.content:
                return response.json()
            return {}
            
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    raise Exception(f"API Error: {e.response.status_code} - {error_detail}")
                except:
                    raise Exception(f"API Error: {e.response.status_code} - {e.response.text}")
            else:
                raise Exception(f"Connection Error: {e}")
    
    def cmd_list(self, args: List[str]):
        """List objects of a specific type"""
        if not args:
            print("❌ Usage: list <type>")
            print("   Available types: players, rooms, items, npcs")
            return
        
        obj_type = args[0].lower()
        if obj_type not in self.object_types:
            print(f"❌ Unknown object type: {obj_type}")
            print("   Available types: players, rooms, items, npcs")
            return
        
        try:
            endpoint = self.object_types[obj_type]['endpoint']
            response = self.api_request('GET', endpoint)
            
            if 'items' in response and response['items']:
                print(f"\n============================================================")
                print(f" All {obj_type.title()} ({len(response['items'])} total) ")
                print(f"============================================================")
                
                for obj in response['items']:
                    if obj_type == 'players':
                        print(f"  • ID {obj['id']}: {obj['name']} (Lvl {obj['level']}, HP {obj['health']}/{obj['max_health']})")
                        print(f"    Room: {obj['room_id']}, XP: {obj['experience']}")
                    elif obj_type == 'rooms':
                        print(f"  • ID {obj['id']}: {obj['name']}")
                        print(f"    Description: {obj['description'][:50]}{'...' if len(obj['description']) > 50 else ''}")
                    elif obj_type == 'items':
                        print(f"  • ID {obj['id']}: {obj['name']} ({obj['item_type']})")
                        print(f"    Value: {obj['value']}, Movable: {'Yes' if obj['is_movable'] else 'No'}")
                        if obj.get('room_id'):
                            print(f"    Location: Room {obj['room_id']}")
                        elif obj.get('player_id'):
                            print(f"    Location: Player {obj['player_id']}")
                    elif obj_type == 'npcs':
                        print(f"  • ID {obj['id']}: {obj['name']} ({obj['npc_type']})")
                        print(f"    Room: {obj['room_id']}, Friendly: {'Yes' if obj['is_friendly'] else 'No'}")
                        print(f"    Combat: {'Enabled' if obj['combat_enabled'] else 'Disabled'}")
                    print()
            else:
                print(f"ℹ️  No {obj_type} found in the database")
                
        except Exception as e:
            print(f"❌ Error listing {obj_type}: {e}")
    
    def cmd_show(self, args: List[str]):
        """Show details of a specific object"""
        if len(args) < 2:
            print("❌ Usage: show <type> <id>")
            return
        
        obj_type = args[0].lower()
        obj_id = args[1]
        
        if obj_type not in self.object_types:
            print(f"❌ Unknown object type: {obj_type}")
            return
        
        try:
            endpoint = f"{self.object_types[obj_type]['endpoint']}{obj_id}"
            obj = self.api_request('GET', endpoint)
            
            print(f"\n============================================================")
            print(f" {obj_type.title()} Details (ID: {obj_id}) ")
            print(f"============================================================")
            
            for key, value in obj.items():
                if key != 'id':
                    print(f"  {key.title()}: {value}")
                    
        except Exception as e:
            print(f"❌ Error showing {obj_type} {obj_id}: {e}")
    
    def cmd_create(self, args: List[str]):
        """Create a new object"""
        if not args:
            print("❌ Usage: create <type>")
            print("   Available types: players, rooms, items, npcs")
            return
        
        obj_type = args[0].lower()
        if obj_type not in self.object_types:
            print(f"❌ Unknown object type: {obj_type}")
            return
        
        try:
            print(f"\n============================================================")
            print(f" Create New {obj_type.title()} ")
            print(f"============================================================")
            print("\nEnter the following information (press Enter to use defaults):\n")
            
            schema = self.object_types[obj_type]['create_schema']
            data = {}
            
            for field, description in schema.items():
                if 'required' in description:
                    value = input(f"  {field}: ")
                    if not value:
                        print(f"❌ {field} is required!")
                        return
                    data[field] = value
                else:
                    default_value = input(f"  {field}: ")
                    if default_value:
                        data[field] = default_value
            
            # Convert data types
            for field, value in data.items():
                if field in ['health', 'max_health', 'level', 'experience', 'value', 'room_id', 'player_id']:
                    try:
                        data[field] = int(value)
                    except ValueError:
                        print(f"❌ {field} must be a number!")
                        return
                elif field in ['is_movable', 'is_usable', 'is_equippable', 'combat_enabled', 'is_friendly']:
                    if value.lower() in ['true', 'yes', '1']:
                        data[field] = True
                    elif value.lower() in ['false', 'no', '0']:
                        data[field] = False
                    else:
                        print(f"❌ {field} must be true/false!")
                        return
            
            # Create the object
            endpoint = self.object_types[obj_type]['endpoint']
            response = self.api_request('POST', endpoint, data)
            
            print(f"\n✅ {obj_type.title()} created successfully!")
            print(f"   ID: {response['id']}")
            print(f"   Name: {response['name']}")
            
        except Exception as e:
            print(f"❌ Error creating {obj_type}: {e}")
    
    def cmd_delete(self, args: List[str]):
        """Delete an object (not yet implemented in the API)"""
        print("❌ Delete functionality not yet implemented in the API")
        print("   This will be available when DELETE endpoints are added")
    
    def cmd_count(self, args: List[str]):
        """Count objects of each type"""
        try:
            print(f"\n============================================================")
            print(f" Database Object Counts ")
            print(f"============================================================")
            
            total_count = 0
            
            for obj_type in self.object_types:
                try:
                    endpoint = self.object_types[obj_type]['endpoint']
                    response = self.api_request('GET', endpoint)
                    count = len(response.get('items', []))
                    total_count += count
                    print(f"ℹ️  {obj_type.title()}: {count}")
                except Exception as e:
                    print(f"❌ Error counting {obj_type}: {e}")
            
            print(f"\n✅ Total objects in database: {total_count}")
            
        except Exception as e:
            print(f"❌ Error getting counts: {e}")
    
    def cmd_stats(self, args: List[str]):
        """Show database statistics"""
        self.cmd_count([])
    
    def cmd_help(self, args: List[str]):
        """Show help information"""
        print("\n============================================================")
        print(" Admin CLI Help ")
        print("============================================================")
        print("\nAvailable Commands:")
        print("  list <type>     - List all objects of a specific type")
        print("  show <type> <id> - Show details of a specific object")
        print("  create <type>   - Create a new object")
        print("  delete <type> <id> - Delete an object (not implemented)")
        print("  count           - Count objects of each type")
        print("  stats           - Show database statistics")
        print("  help            - Show this help message")
        print("  quit/exit       - Exit the admin interface")
        
        print("\nObject Types:")
        print("  players         - Player characters")
        print("  rooms           - Game world locations")
        print("  items           - Game objects and equipment")
        print("  npcs            - Non-player characters")
        
        print("\nExamples:")
        print("  list players    - Show all players")
        print("  show rooms 1    - Show details of room 1")
        print("  create players  - Create a new player")
        print("  count           - Show object counts")
    
    def cmd_quit(self, args: List[str]):
        """Exit the admin interface"""
        print("ℹ️  Goodbye!")
        sys.exit(0)

def main():
    """Main entry point"""
    try:
        admin = GameAdmin()
        admin.run()
    except KeyboardInterrupt:
        print("\n\nℹ️  Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
