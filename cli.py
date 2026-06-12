#!/usr/bin/env python3
"""
Interactive CLI for the Game API
Allows natural language commands like /look, /go north, /take item
"""
import requests
import json
import sys
import re
from typing import Optional, Dict, Any

class GameCLI:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.current_player_id = 1  # Default to player ID 1
        self.session = requests.Session()
        self.running = True
        
        # Command patterns
        self.commands = {
            r'^/look$': self.cmd_look,
            r'^/go\s+(.+)$': self.cmd_go,
            r'^/take\s+(.+)$': self.cmd_take,
            r'^/drop\s+(.+)$': self.cmd_drop,
            r'^/use\s+(.+)$': self.cmd_use,
            r'^/inventory$': self.cmd_inventory,
            r'^/status$': self.cmd_status,
            r'^/sheet$': self.cmd_sheet,
            r'^/inspect\s+(.+)$': self.cmd_inspect,
            r'^/help$': self.cmd_help,
            r'^/quit$': self.cmd_quit,
            r'^/player\s+(\d+)$': self.cmd_player,
            r'^/rooms$': self.cmd_rooms,
            r'^/items$': self.cmd_items,
            r'^/npcs$': self.cmd_npcs,
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
        self.print_colored("=" * 50, "cyan")
        self.print_colored(f" {text} ", "cyan")
        self.print_colored("=" * 50, "cyan")
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
    
    def make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make an HTTP request to the API"""
        try:
            url = f"{self.base_url}{endpoint}"
            if method.upper() == "GET":
                response = self.session.get(url)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data)
            else:
                self.print_error(f"Unsupported HTTP method: {method}")
                return None
            
            if response.status_code == 200:
                return response.json()
            else:
                self.print_error(f"API Error: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.ConnectionError:
            self.print_error("Cannot connect to the game server. Make sure it's running on localhost:8000")
            return None
        except Exception as e:
            self.print_error(f"Request failed: {e}")
            return None
    
    def cmd_look(self, *args):
        """Look around the current room"""
        state = self.make_request("GET", f"/state/{self.current_player_id}")
        if not state:
            return
        
        room = state["current_room"]
        self.print_header(f"Looking around {room['name']}")
        print(room["description"])
        print()
        
        # Show other players in the room
        other_players = state.get("other_players_in_room", [])
        if other_players:
            self.print_colored("Other players here:", "green")
            for player in other_players:
                print(f"  • {player['name']} (Level {player['level']})")
            print()
        
        # Show items in the room
        items = state["items_in_room"]
        if items:
            self.print_colored("Items you can see:", "yellow")
            for item in items:
                print(f"  • {item['name']} - {item['description']}")
            print()
        
        # Show NPCs in the room
        npcs = state["npcs_in_room"]
        if npcs:
            self.print_colored("People you can see:", "yellow")
            for npc in npcs:
                print(f"  • {npc['name']} - {npc['description']}")
            print()
        
        # Show exits (for now, just show available rooms)
        self.print_colored("Available exits:", "yellow")
        rooms = self.make_request("GET", "/rooms/")
        if rooms:
            for room in rooms["items"]:
                if room["id"] != state["current_room"]["id"]:
                    print(f"  • {room['name']}")
    
    def cmd_go(self, direction: str):
        """Go to a room by name"""
        # Get available rooms
        rooms = self.make_request("GET", "/rooms/")
        if not rooms:
            return
        
        # Find room by name (case-insensitive)
        target_room = None
        for room in rooms["items"]:
            if room["name"].lower() == direction.lower():
                target_room = room
                break

        if not target_room:
            self.print_error(f"Room '{direction}' not found. Available rooms:")
            for room in rooms["items"]:
                print(f"  • {room['name']}")
            return
        
        # Perform the move action
        action_data = {
            "player_id": self.current_player_id,
            "action_type": "move",
            "target_type": "room",
            "target_id": target_room["id"]
        }
        
        result = self.make_request("POST", "/action", action_data)
        if result and result.get("success"):
            self.print_success(f"Moved to {target_room['name']}")
            # Show the new room
            self.cmd_look()
        else:
            self.print_error("Failed to move to that room")
    
    def cmd_take(self, item_name: str):
        """Take an item by name"""
        # Get current state to see available items
        state = self.make_request("GET", f"/state/{self.current_player_id}")
        if not state:
            return
        
        # Find item by name (case-insensitive)
        target_item = None
        for item in state["items_in_room"]:
            if item["name"].lower() == item_name.lower():
                target_item = item
                break
        
        if not target_item:
            self.print_error(f"Item '{item_name}' not found in this room")
            return
        
        # Perform the take action
        action_data = {
            "player_id": self.current_player_id,
            "action_type": "pickup",
            "target_type": "item",
            "target_id": target_item["id"]
        }
        
        result = self.make_request("POST", "/action", action_data)
        if result and result.get("success"):
            self.print_success(f"Picked up {target_item['name']}")
        else:
            self.print_error("Failed to pick up the item")
    
    def cmd_drop(self, item_name: str):
        """Drop an item by name"""
        # Get current state to see inventory
        state = self.make_request("GET", f"/state/{self.current_player_id}")
        if not state:
            return
        
        # Find item by name (case-insensitive)
        target_item = None
        for item in state["inventory"]:
            if item["name"].lower() == item_name.lower():
                target_item = item
                break
        
        if not target_item:
            self.print_error(f"Item '{item_name}' not found in your inventory")
            return
        
        # Perform the drop action
        action_data = {
            "player_id": self.current_player_id,
            "action_type": "drop",
            "target_type": "item",
            "target_id": target_item["id"]
        }
        
        result = self.make_request("POST", "/action", action_data)
        if result and result.get("success"):
            self.print_success(f"Dropped {target_item['name']}")
        else:
            self.print_error("Failed to drop the item")

    def cmd_use(self, item_name: str):
        """Use an item (from inventory or room)"""
        state = self.make_request("GET", f"/state/{self.current_player_id}")
        if not state:
            return
        inv_item = next((i for i in state["inventory"] if i["name"].lower()==item_name.lower()), None)
        room_item = next((i for i in state["items_in_room"] if i["name"].lower()==item_name.lower()), None)
        target = inv_item or room_item
        if not target:
            self.print_error(f"No item '{item_name}' in inventory or room.")
            return
        result = self.make_request("POST", "/action", {
            "player_id": self.current_player_id,
            "action_type": "use",
            "target_type": "item",
            "target_id": target["id"]
        })
        if result and result.get("success"):
            self.print_success(f"You use the {target['name']}.")
        else:
            self.print_error(result.get("error","Failed to use item.") if result else "Failed to use item.")
    
    def cmd_inventory(self, *args):
        """Show player inventory"""
        state = self.make_request("GET", f"/state/{self.current_player_id}")
        if not state:
            return
        
        inventory = state["inventory"]
        self.print_header("Inventory")
        
        if not inventory:
            print("Your inventory is empty.")
        else:
            for item in inventory:
                print(f"  • {item['name']} - {item['description']}")
                print(f"    Type: {item['item_type']}, Value: {item['value']}")
                if item['is_equipped']:
                    self.print_colored("    [EQUIPPED]", "green")
                print()
    
    def cmd_status(self, *args):
        """Show player status"""
        state = self.make_request("GET", f"/state/{self.current_player_id}")
        if not state:
            return
        
        player = state["player"]
        room = state["current_room"]
        
        self.print_header("Player Status")
        print(f"Name: {player['name']}")
        print(f"Health: {player['health']}/{player['max_health']}")
        print(f"Level: {player['level']}")
        print(f"Experience: {player['experience']}")
        print(f"Location: {room['name']}")
        print()
        
        # Show inventory count
        inventory_count = len(state["inventory"])
        print(f"Inventory: {inventory_count} items")

    def cmd_sheet(self, *args):
        """Show classic D&D-style ability scores"""
        data = self.make_request("GET", f"/players/{self.current_player_id}/sheet")
        if not data:
            return
        self.print_header("Character Sheet")
        print(f"{data['name']} (Lvl {data['level']})  HP {data['health']}/{data['max_health']}")
        ab = data['abilities']; mods = data['modifiers']
        print("STR {0} ({1:+})  DEX {2} ({3:+})  CON {4} ({5:+})".format(ab['str'],mods['str'],ab['dex'],mods['dex'],ab['con'],mods['con']))
        print("INT {0} ({1:+})  WIS {2} ({3:+})  CHA {4} ({5:+})".format(ab['intel'],mods['intel'],ab['wis'],mods['wis'],ab['cha'],mods['cha']))

    def cmd_inspect(self, name: str):
        """Inspect an NPC in the room; show sheet + reactions toward you"""
        state = self.make_request("GET", f"/state/{self.current_player_id}")
        if not state: return
        target = next((n for n in state.get("npcs_in_room", []) if n["name"].lower()==name.lower()), None)
        if not target:
            self.print_error(f"No NPC named '{name}' here.")
            return
        npc_id = target["id"]
        sheet = self.make_request("GET", f"/npcs/{npc_id}/sheet")
        react = self.make_request("GET", f"/npcs/{npc_id}/reaction/{self.current_player_id}")
        if sheet:
            self.print_header(f"{sheet['name']} ({sheet['npc_type']})")
            print(sheet["description"])
            print(f"Combat: {'Yes' if sheet['combat_enabled'] else 'No'}")
            ab = sheet['abilities']; mods = sheet['modifiers']
            print("STR {0} ({1:+})  DEX {2} ({3:+})  CON {4} ({5:+})".format(ab['str'],mods['str'],ab['dex'],mods['dex'],ab['con'],mods['con']))
            print("INT {0} ({1:+})  WIS {2} ({3:+})  CHA {4} ({5:+})".format(ab['intel'],mods['intel'],ab['wis'],mods['wis'],ab['cha'],mods['cha']))
        if react:
            print("Reactions → threat:{threat} attraction:{attraction} arousal:{arousal} aggression:{aggression}".format(**react))
    
    def cmd_help(self, *args):
        """Show help information"""
        self.print_header("Available Commands")
        print("Game Commands:")
        print("  /look                    - Look around the current room")
        print("  /go <room_name>          - Move to a different room")
        print("  /take <item_name>        - Pick up an item")
        print("  /drop <item_name>        - Drop an item from inventory")
        print("  /use <item_name>         - Use an item")
        print("  /inventory               - Show your inventory")
        print("  /status                  - Show player status")
        print("  /sheet                   - Show character sheet with ability scores")
        print("  /inspect <npc_name>      - Inspect an NPC and see their reactions")
        print()
        print("Utility Commands:")
        print("  /rooms                   - List all available rooms")
        print("  /items                   - List all items")
        print("  /npcs                    - List all NPCs")
        print("  /player <id>             - Switch to a different player")
        print("  /help                    - Show this help")
        print("  /quit                    - Exit the game")
        print()
        print("Examples:")
        print("  /go tavern               - Move to the tavern")
        print("  /take sword              - Pick up a sword")
        print("  /drop sword              - Drop a sword")
    
    def cmd_quit(self, *args):
        """Quit the game"""
        self.print_info("Thanks for playing! Goodbye!")
        self.running = False
    
    def cmd_player(self, player_id: str):
        """Switch to a different player"""
        try:
            new_id = int(player_id)
            # Check if player exists
            player = self.make_request("GET", f"/players/{new_id}")
            if player:
                self.current_player_id = new_id
                self.print_success(f"Switched to player {new_id}: {player['name']}")
            else:
                self.print_error(f"Player {new_id} not found")
        except ValueError:
            self.print_error("Invalid player ID. Use a number.")
    
    def cmd_rooms(self, *args):
        """List all available rooms"""
        rooms = self.make_request("GET", "/rooms/")
        if not rooms:
            return
        
        self.print_header("Available Rooms")
        for room in rooms["items"]:
            print(f"  • {room['name']}")
            print(f"    {room['description']}")
            print()
    
    def cmd_items(self, *args):
        """List all items"""
        items = self.make_request("GET", "/items/")
        if not items:
            return
        
        self.print_header("All Items")
        for item in items["items"]:
            location = "Inventory" if item['player_id'] else f"Room {item['room_id']}"
            print(f"  • {item['name']} - {item['description']}")
            print(f"    Type: {item['item_type']}, Value: {item['value']}, Location: {location}")
            print()
    
    def cmd_npcs(self, *args):
        """List all NPCs"""
        npcs = self.make_request("GET", "/npcs/")
        if not npcs:
            return
        
        self.print_header("All NPCs")
        for npc in npcs["items"]:
            print(f"  • {npc['name']} - {npc['description']}")
            print(f"    Type: {npc['npc_type']}, Health: {npc['health']}/{npc['max_health']}")
            print(f"    Friendly: {'Yes' if npc['is_friendly'] else 'No'}")
            print()
    
    def process_command(self, command: str):
        """Process a command and execute the appropriate action"""
        command = command.strip()
        if not command:
            return
        
        # Check if it's a command (starts with /)
        if not command.startswith('/'):
            self.print_error("Commands must start with /. Type /help for available commands.")
            return
        
        # Try to match the command with patterns
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
        self.print_error(f"Unknown command: {command}. Type /help for available commands.")
    
    def run(self):
        """Main CLI loop"""
        self.print_header("Welcome to the Game CLI!")
        self.print_info("Type /help to see available commands")
        self.print_info("Type /quit to exit")
        print()
        
        # Show initial room
        self.cmd_look()
        
        while self.running:
            try:
                command = input(f"\n[{self.current_player_id}]> ").strip()
                if command:
                    self.process_command(command)
            except KeyboardInterrupt:
                print()
                self.cmd_quit()
            except EOFError:
                self.cmd_quit()

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Interactive CLI for the Game API")
    parser.add_argument("--url", default="http://localhost:8000", 
                       help="Base URL for the Game API (default: http://localhost:8000)")
    parser.add_argument("--player", type=int, default=1,
                       help="Starting player ID (default: 1)")
    
    args = parser.parse_args()
    
    cli = GameCLI(args.url)
    cli.current_player_id = args.player
    
    try:
        cli.run()
    except KeyboardInterrupt:
        print("\nGoodbye!")

if __name__ == "__main__":
    main()
