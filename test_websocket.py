#!/usr/bin/env python3
"""
Test script to verify WebSocket functionality
"""
import asyncio
import websockets
import json
import requests

async def test_websocket():
    base_url = "http://localhost:8000"
    ws_url = "ws://localhost:8000"
    
    print("🧪 Testing WebSocket Functionality")
    print("=" * 50)
    
    # Test 1: Check if server is running
    print("\n1. Checking server status...")
    try:
        response = requests.get(f"{base_url}/")
        if response.status_code == 200:
            print("   ✅ Server is running")
        else:
            print(f"   ❌ Server returned status {response.status_code}")
            return
    except Exception as e:
        print(f"   ❌ Cannot connect to server: {e}")
        return
    
    # Test 2: Check if players exist
    print("\n2. Checking existing players...")
    try:
        players = requests.get(f"{base_url}/players/").json()
        print(f"   Found {len(players)} players:")
        for player in players:
            print(f"   - {player['name']} (ID: {player['id']}) in room {player['room_id']}")
    except Exception as e:
        print(f"   ❌ Error getting players: {e}")
        return
    
    if not players:
        print("   ❌ No players found. Please seed the database first.")
        return
    
    # Test 3: Test WebSocket connection
    print("\n3. Testing WebSocket connection...")
    player_id = players[0]['id']
    
    try:
        uri = f"{ws_url}/ws/{player_id}"
        print(f"   Connecting to: {uri}")
        
        websocket = await websockets.connect(uri)
        print("   ✅ WebSocket connection established!")
        
        # Test 4: Send a test message
        print("\n4. Testing message sending...")
        test_message = "Hello WebSocket!"
        await websocket.send(test_message)
        print(f"   ✅ Sent message: {test_message}")
        
        # Test 5: Wait for response
        print("\n5. Waiting for response...")
        try:
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            print(f"   ✅ Received response: {response}")
            
            # Parse JSON response
            try:
                data = json.loads(response)
                print(f"   ✅ Response is valid JSON: {data}")
            except json.JSONDecodeError:
                print(f"   ⚠️  Response is not JSON: {response}")
                
        except asyncio.TimeoutError:
            print("   ⚠️  No response received within 5 seconds")
        
        # Test 6: Test room subscription
        print("\n6. Testing room subscription...")
        player_state = requests.get(f"{base_url}/state/{player_id}").json()
        current_room = player_state['current_room']['name']
        print(f"   Player is in room: {current_room}")
        print("   ✅ WebSocket should be subscribed to room updates")
        
        # Test 7: Move another player to trigger WebSocket events
        print("\n7. Testing real-time updates...")
        if len(players) > 1:
            other_player = players[1]
            print(f"   Moving {other_player['name']} to trigger WebSocket events...")
            
            # Move the other player to a different room
            rooms = requests.get(f"{base_url}/rooms/").json()
            target_room = None
            for room in rooms:
                if room['id'] != other_player['room_id']:
                    target_room = room
                    break
            
            if target_room:
                move_action = {
                    "player_id": other_player['id'],
                    "action_type": "move",
                    "target_type": "room",
                    "target_id": target_room['id']
                }
                
                result = requests.post(f"{base_url}/action", json=move_action).json()
                if result.get('success'):
                    print(f"   ✅ Moved {other_player['name']} to {target_room['name']}")
                    print("   🔴 WebSocket should receive 'player_left' event")
                    
                    # Wait for WebSocket message
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                        print(f"   ✅ Received WebSocket update: {response}")
                    except asyncio.TimeoutError:
                        print("   ⚠️  No WebSocket update received")
                else:
                    print(f"   ❌ Failed to move player: {result.get('message', 'Unknown error')}")
            else:
                print("   ⚠️  No other rooms available for testing")
        else:
            print("   ⚠️  Only one player available, can't test real-time updates")
        
        # Clean up
        await websocket.close()
        print("\n   ✅ WebSocket connection closed")
        
    except Exception as e:
        print(f"   ❌ WebSocket test failed: {e}")
        return
    
    print("\n" + "=" * 50)
    print("🎯 WebSocket Test Complete!")
    print("\nNext steps:")
    print("1. Run: python websocket_cli.py --player 1")
    print("2. In another terminal: python websocket_cli.py --player 2")
    print("3. Move players between rooms to see real-time updates!")

if __name__ == "__main__":
    asyncio.run(test_websocket())
