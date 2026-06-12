#!/usr/bin/env python3
"""
WebSocket-enabled CLI for real-time multiplayer gaming
"""
import asyncio
import websockets
import json
import sys
import argparse
import re
from typing import Optional, Dict, Any
import requests

class WebSocketGameCLI:
    def __init__(self, base_url: str = "http://localhost:8000", player_id: int = 1):
        self.base_url = base_url
        self.ws_url = base_url.replace("http", "ws")
        self.player_id = player_id
        self.websocket = None
        self.running = True
        self.connected = False
        
        # Command patterns (same as regular CLI)
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
            r'^/chat$': self.cmd_chat,
            r'^/say\s+(.+)$': self.cmd_say,
            r'^/tell\s+(\d+)\s+(.+)$': self.cmd_tell,
            r'^/npc\s+(\d+)\s+(.+)$': self.cmd_npc_chat
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
    
    def print_realtime(self, message: str):
        """Print real-time updates"""
        self.print_colored(f"🔴 {message}", "magenta")
    
    async def connect_websocket(self):
        """Connect to the WebSocket endpoint"""
        try:
            self.websocket = await websockets.connect(f"{self.ws_url}/ws/{self.player_id}")
            self.connected = True
            self.print_success(f"Connected to WebSocket as Player {self.player_id}")
            return True
        except Exception as e:
            self.print_error(f"Failed to connect to WebSocket: {e}")
            return False
    
    async def listen_for_updates(self):
        """Listen for real-time updates from the WebSocket"""
        if not self.websocket:
            return
        
        print("🔍 WebSocket listener started and listening for messages...")
        
        try:
            async for message in self.websocket:
                try:
                    print(f"📥 Raw message received: {message}")
                    data = json.loads(message)
                    print(f"📨 Parsed message: {data}")
                    await self.handle_websocket_message(data)
                except json.JSONDecodeError:
                    print(f"Received non-JSON message: {message}")
        except websockets.exceptions.ConnectionClosed:
            self.print_error("WebSocket connection closed")
            self.connected = False
        except Exception as e:
            self.print_error(f"WebSocket error: {e}")
            self.connected = False
    
    async def handle_websocket_message(self, data: Dict[str, Any]):
        """Handle incoming WebSocket messages"""
        msg_type = data.get("type")
        print(f"🔍 Handling message type: {msg_type}")
        
        if msg_type == "player_joined":
            player_info = data.get("player_info", {})
            message = f"{player_info.get('name', 'Unknown')} has entered the room!"
            print(f"📢 Broadcasting: {message}")
            self.print_realtime(message)
            
        elif msg_type == "player_left":
            player_info = data.get("player_info", {})
            message = f"{player_info.get('name', 'Unknown')} has left the room!"
            print(f"📢 Broadcasting: {message}")
            self.print_realtime(message)
            
        elif msg_type == "player_action":
            player_id = data.get("player_id")
            action_type = data.get("action_type")
            action_data = data.get("action_data", {})
            
            if action_type == "move":
                room_name = action_data.get("room_name", "unknown room")
                message = f"Another player moved to {room_name}"
                print(f"📢 Broadcasting: {message}")
                self.print_realtime(message)
                
        elif msg_type == "echo":
            # Just for testing - ignore echo messages
            print("🔇 Ignoring echo message")
            pass
            
        elif msg_type == "chat_message":
            # Handle chat messages
            sender_name = data.get("sender_name", "Unknown")
            content = data.get("content", "")
            message_type = data.get("message_type", "unknown")
            
            if message_type == "global":
                self.print_realtime(f"🌍 {sender_name}: {content}")
            elif message_type == "room":
                room_id = data.get("room_id", "unknown")
                self.print_realtime(f"🏠 [{room_id}] {sender_name}: {content}")
            elif message_type == "private":
                self.print_realtime(f"💬 {sender_name} whispers: {content}")
            
        else:
            print(f"❓ Unknown message type: {msg_type}")
            self.print_info(f"Received message: {data}")
    
    def make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make an HTTP request to the API"""
        try:
            url = f"{self.base_url}{endpoint}"
            if method.upper() == "GET":
                response = requests.get(url)
            elif method.upper() == "POST":
                response = requests.post(url, json=data)
            else:
                self.print_error(f"Unsupported HTTP method: {method}")
                return None
            
            if response.status_code == 200:
                return response.json()
            else:
                try:
                    body = response.json()
                    detail = body.get("detail") or body.get("error") or response.text
                except Exception:
                    detail = response.text
                self.print_error(detail)
                return None

        except requests.exceptions.ConnectionError:
            self.print_error("Cannot connect to the game server. Make sure it's running on localhost:8000")
            return None
        except Exception as e:
            self.print_error(f"Request failed: {e}")
            return None
    
    def cmd_look(self, *args):
        """Look around the current room"""
        state = self.make_request("GET", f"/state/{self.player_id}")
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
        
        # Show exits
        exits = state.get("exits", [])
        if exits:
            self.print_colored("Exits:", "yellow")
            for e in exits:
                lock = " (locked)" if e.get("is_locked") else ""
                dest = e.get("to_room") or "?"
                print(f"  • {e['direction']} → {dest}{lock}")

    def cmd_go(self, where: str):
        """Move through an exit, by direction (e.g. 'north'/'n') or destination
        room name."""
        state = self.make_request("GET", f"/state/{self.player_id}")
        if not state:
            return
        w = where.strip().lower()
        direction = w
        for e in state.get("exits", []):
            if (e.get("to_room") or "").lower() == w:
                direction = e["direction"]
                break

        result = self.make_request("POST", "/action", {
            "player_id": self.player_id,
            "action_type": "move",
            "parameters": {"direction": direction},
        })
        if result and result.get("success"):
            self.print_success(result.get("message", "You move."))
            self.cmd_look()
        # On failure, make_request already surfaced the server's reason.
    
    def cmd_take(self, item_name: str):
        """Take an item by name"""
        state = self.make_request("GET", f"/state/{self.player_id}")
        if not state:
            return
        
        target_item = None
        for item in state["items_in_room"]:
            if item["name"].lower() == item_name.lower():
                target_item = item
                break
        
        if not target_item:
            self.print_error(f"Item '{item_name}' not found in this room")
            return
        
        action_data = {
            "player_id": self.player_id,
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
        state = self.make_request("GET", f"/state/{self.player_id}")
        if not state:
            return
        
        target_item = None
        for item in state["inventory"]:
            if item["name"].lower() == item_name.lower():
                target_item = item
                break
        
        if not target_item:
            self.print_error(f"Item '{item_name}' not found in your inventory")
            return
        
        action_data = {
            "player_id": self.player_id,
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
        state = self.make_request("GET", f"/state/{self.player_id}")
        if not state:
            return
        inv_item = next((i for i in state["inventory"] if i["name"].lower()==item_name.lower()), None)
        room_item = next((i for i in state["items_in_room"] if i["name"].lower()==item_name.lower()), None)
        target = inv_item or room_item
        if not target:
            self.print_error(f"No item '{item_name}' in inventory or room.")
            return
        result = self.make_request("POST", "/action", {
            "player_id": self.player_id,
            "action_type": "use",
            "target_type": "item",
            "target_id": target["id"]
        })
        if result and result.get("success"):
            self.print_success(f"You use the {target['name']}.")
        else:
            self.print_error(result.get("error","Failed to use item.") if result else "Failed to use item.")
    
    def cmd_inventory(self, *args):
        """Show inventory"""
        state = self.make_request("GET", f"/state/{self.player_id}")
        if not state:
            return
        
        inventory = state["inventory"]
        if inventory:
            self.print_header("Inventory")
            for item in inventory:
                print(f"  • {item['name']} - {item['description']}")
                print(f"    Type: {item['item_type']}, Value: {item['value']}")
                print()
        else:
            self.print_info("Your inventory is empty")
    
    def cmd_status(self, *args):
        """Show player status"""
        state = self.make_request("GET", f"/state/{self.player_id}")
        if not state:
            return
        
        player = state["player"]
        self.print_header("Player Status")
        print(f"Name: {player['name']}")
        print(f"Health: {player['health']}/{player['max_health']}")
        print(f"Level: {player['level']}")
        print(f"Experience: {player['experience']}")
        print(f"Location: {state['current_room']['name']}")
        print(f"Inventory: {len(state['inventory'])} items")

    def cmd_sheet(self, *args):
        """Show classic D&D-style ability scores"""
        data = self.make_request("GET", f"/players/{self.player_id}/sheet")
        if not data:
            return
        self.print_header("Character Sheet")
        print(f"{data['name']} (Lvl {data['level']})  HP {data['health']}/{data['max_health']}")
        ab = data['abilities']; mods = data['modifiers']
        print("STR {0} ({1:+})  DEX {2} ({3:+})  CON {4} ({5:+})".format(ab['str'],mods['str'],ab['dex'],mods['dex'],ab['con'],mods['con']))
        print("INT {0} ({1:+})  WIS {2} ({3:+})  CHA {4} ({5:+})".format(ab['intel'],mods['intel'],ab['wis'],mods['wis'],ab['cha'],mods['cha']))

    def cmd_inspect(self, name: str):
        """Inspect an NPC in the room; show sheet + reactions toward you"""
        state = self.make_request("GET", f"/state/{self.player_id}")
        if not state: return
        target = next((n for n in state.get("npcs_in_room", []) if n["name"].lower()==name.lower()), None)
        if not target:
            self.print_error(f"No NPC named '{name}' here.")
            return
        npc_id = target["id"]
        sheet = self.make_request("GET", f"/npcs/{npc_id}/sheet")
        react = self.make_request("GET", f"/npcs/{npc_id}/reaction/{self.player_id}")
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
        print("Chat Commands:")
        print("  /say <message>           - Send message to current room")
        print("  /tell <player_id> <message> - Send private message to player")
        print("  /npc <npc_id> <message> - Chat with NPC")
        print("  /chat                    - Show chat help")
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
        print("  /use potion              - Use a potion")
        print("  /inspect merchant        - Inspect the merchant NPC")
        print()
        print("🔴 Real-time Updates:")
        print("  This CLI shows real-time updates when other players")
        print("  join/leave rooms or perform actions!")
    
    def cmd_quit(self, *args):
        """Quit the game"""
        self.print_info("Goodbye!")
        self.running = False
    
    def cmd_player(self, player_id: str):
        """Switch to a different player"""
        try:
            new_id = int(player_id)
            self.player_id = new_id
            self.print_success(f"Switched to player {new_id}")
        except ValueError:
            self.print_error("Player ID must be a number")
    
    def cmd_rooms(self, *args):
        """List all rooms"""
        rooms = self.make_request("GET", "/rooms/")
        if not rooms:
            return
        
        self.print_header("All Rooms")
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
            print(f"  • {npc['name']} - {npc['npc_type']} - {npc['description']}")
            print(f"    Health: {npc['health']}/{npc['max_health']}")
            print()
    
    def cmd_chat(self, *args):
        """Show chat help"""
        self.print_header("Chat Commands")
        print("💬 Available chat commands:")
        print("  /say <message>     - Send message to current room")
        print("  /tell <player> <message> - Send private message to player")
        print("  /npc <npc_id> <message> - Chat with NPC")
        print("  /chat              - Show this help")
        print()
    
    def cmd_say(self, *args):
        """Send a message to the current room"""
        if not args:
            self.print_error("Usage: /say <message>")
            return
        
        message = " ".join(args)
        state = self.make_request("GET", f"/state/{self.player_id}")
        if not state:
            return
        
        room_id = state["current_room"]["id"]
        
        # Send room chat message
        chat_data = {
            "sender_id": self.player_id,
            "message_type": "room",
            "content": message,
            "target_id": room_id
        }
        
        response = self.make_request("POST", "/chat/send", chat_data)
        if response:
            self.print_success(f"Message sent to room: {message}")
        else:
            self.print_error("Failed to send message")
    
    def cmd_tell(self, *args):
        """Send a private message to another player"""
        if len(args) < 2:
            self.print_error("Usage: /tell <player_id> <message>")
            return
        
        try:
            target_player_id = int(args[0])
            message = " ".join(args[1:])
        except ValueError:
            self.print_error("Player ID must be a number")
            return
        
        # Send private message
        chat_data = {
            "sender_id": self.player_id,
            "message_type": "private",
            "content": message,
            "target_id": target_player_id
        }
        
        response = self.make_request("POST", "/chat/send", chat_data)
        if response:
            self.print_success(f"Private message sent to Player {target_player_id}: {message}")
        else:
            self.print_error("Failed to send private message")
    
    def cmd_npc_chat(self, *args):
        """Chat with an NPC"""
        if len(args) < 2:
            self.print_error("Usage: /npc <npc_id> <message>")
            return
        
        try:
            npc_id = int(args[0])
            message = " ".join(args[1:])
        except ValueError:
            self.print_error("NPC ID must be a number")
            return
        
        # Chat with NPC
        chat_data = {
            "player_id": self.player_id,
            "npc_id": npc_id,
            "message": message
        }
        
        response = self.make_request("POST", "/chat/npc", chat_data)
        if response:
            self.print_info(f"💬 {response['npc_name']}: {response['response']}")
            if response.get('should_attack'):
                self.print_error("⚠️  The NPC seems hostile and may attack!")
        else:
            self.print_error("Failed to chat with NPC")
    
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
        self.print_error(f"Unknown command: {command}. Type /help for available commands.")
    
    async def run(self):
        """Main CLI loop with WebSocket support"""
        # Connect to WebSocket
        if not await self.connect_websocket():
            self.print_error("Failed to connect to WebSocket. Running in offline mode.")
        
        self.print_header("Welcome to the WebSocket Game CLI!")
        self.print_info("Type /help to see available commands")
        self.print_info("Type /quit to exit")
        self.print_info("Real-time updates will appear automatically!")
        print()
        
        # Show initial room
        self.cmd_look()
        
        # Start WebSocket listener in background
        websocket_task = None
        if self.connected:
            websocket_task = asyncio.create_task(self.listen_for_updates())
            print("🔍 WebSocket listener started and listening for messages...")
        
        try:
            while self.running:
                try:
                    # Use asyncio.to_thread to avoid blocking the event loop
                    command = await asyncio.to_thread(input, f"\n[{self.player_id}]> ")
                    if command:
                        self.process_command(command.strip())
                except KeyboardInterrupt:
                    print()
                    self.cmd_quit()
                except EOFError:
                    self.cmd_quit()
                
                # Small delay to prevent excessive CPU usage
                await asyncio.sleep(0.01)
        finally:
            # Clean up WebSocket
            if websocket_task:
                websocket_task.cancel()
                try:
                    await websocket_task
                except asyncio.CancelledError:
                    pass
            
            if self.websocket:
                await self.websocket.close()

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="WebSocket-enabled CLI for the Game API")
    parser.add_argument("--url", default="http://localhost:8000", 
                       help="Base URL for the Game API (default: http://localhost:8000)")
    parser.add_argument("--player", type=int, default=1,
                       help="Starting player ID (default: 1)")
    
    args = parser.parse_args()
    
    cli = WebSocketGameCLI(args.url, args.player)
    
    try:
        await cli.run()
    except KeyboardInterrupt:
        print("\nGoodbye!")

if __name__ == "__main__":
    asyncio.run(main())
