# 🗨️ Chat System & LLM-Powered NPCs

## Overview

The game now features a comprehensive chat system with intelligent NPCs that can react based on player stats and context. This system provides:

- **Global Chat**: Messages visible to all players
- **Room Chat**: Messages visible only to players in the same room
- **Private Messages**: Direct communication between players
- **NPC Chat**: Intelligent conversations with game characters
- **Real-time Updates**: Instant message delivery via WebSockets

## 🚀 Features

### Chat Types

1. **Global Chat** (`/say <message>`)
   - Broadcasts to all online players
   - Useful for announcements and general discussion

2. **Room Chat** (`/say <message>`)
   - Messages visible only to players in the same room
   - Perfect for local coordination and roleplay

3. **Private Messages** (`/tell <player_id> <message>`)
   - Direct communication between two players
   - Secret conversations and coordination

4. **NPC Chat** (`/npc <npc_id> <message>`)
   - Intelligent conversations with game characters
   - NPCs react based on player stats and context

### LLM-Powered NPCs

NPCs now have intelligent behavior that includes:

- **Context-Aware Responses**: NPCs consider player level, reputation, health, and location
- **Personality Traits**: Each NPC has unique characteristics that influence their responses
- **Role-Based Behavior**: Merchants, quest givers, and combat mobs behave differently
- **Dynamic Disposition**: NPCs can change their attitude based on player actions
- **Combat Intelligence**: Hostile NPCs can decide when to attack based on player strength

## 🛠️ Technical Implementation

### Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Chat System   │    │  WebSocket      │    │   LLM NPC       │
│                 │    │  Manager        │    │   Framework     │
│ • Global Chat   │◄──►│ • Real-time     │◄──►│ • Rule-based    │
│ • Room Chat     │    │   Broadcasting  │    │   Responses     │
│ • Private Chat  │    │ • Connection    │    │ • Context       │
│ • Chat History  │    │   Management    │    │   Awareness     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Key Components

1. **`chat_system.py`**: Core chat functionality and message management
2. **`llm_npcs.py`**: Framework for intelligent NPC behavior
3. **`chat_schemas.py`**: API schemas for chat requests/responses
4. **Enhanced `main.py`**: Chat endpoints and WebSocket integration
5. **Enhanced `websocket_cli.py`**: Chat commands and real-time display

## 📱 Usage

### CLI Commands

```bash
# Chat with current room
/say Hello everyone in this room!

# Send private message
/tell 2 Hey Player 2, want to team up?

# Chat with NPC
/npc 1 What can you tell me about this place?

# Show chat help
/chat
```

### API Endpoints

```bash
# Send a chat message
POST /chat/send
{
  "sender_id": 1,
  "message_type": "room",
  "content": "Hello room!",
  "target_id": 1
}

# Get chat history
GET /chat/history/room?target_id=1&limit=50

# Chat with NPC
POST /chat/npc
{
  "player_id": 1,
  "npc_id": 1,
  "message": "Hello!"
}
```

## 🧪 Testing

### Test the Chat System

```bash
# Run the test script
python test_chat_system.py

# Test with multiple CLI instances
# Terminal 1
python websocket_cli.py --player 1

# Terminal 2  
python websocket_cli.py --player 2

# Use chat commands in each terminal
```

### Expected Results

1. **Global Messages**: Appear in all connected terminals
2. **Room Messages**: Only visible to players in the same room
3. **Private Messages**: Only visible to the target player
4. **NPC Responses**: Contextual and intelligent
5. **Real-time Updates**: Instant message delivery

## 🔮 Future Enhancements

### LLM Integration

The current system uses rule-based responses as a placeholder. To integrate with actual LLM APIs:

1. **OpenAI Integration**:
   ```python
   import openai
   
   async def generate_llm_response(self, prompt: str) -> str:
       response = await openai.ChatCompletion.acreate(
           model="gpt-3.5-turbo",
           messages=[{"role": "user", "content": prompt}]
       )
       return response.choices[0].message.content
   ```

2. **LLM Support**:
   - DeepSeek API integration (OpenAI-compatible) for NPC responses
   - Swappable to any OpenAI-compatible endpoint via `DEEPSEEK_BASE_URL`
   - Automatic rule-based fallback when no API key is configured

### Advanced NPC Features

1. **Memory Systems**: NPCs remember past interactions
2. **Emotional States**: NPCs have moods that affect responses
3. **Quest Integration**: NPCs can give and track quests
4. **Combat AI**: Intelligent combat decision making
5. **Relationship Building**: Long-term player-NPC relationships

### Enhanced Chat Features

1. **Chat Channels**: Custom channels for different purposes
2. **Moderation Tools**: Spam protection and content filtering
3. **Rich Media**: Support for images, links, and formatting
4. **Chat Bots**: Automated responses and game assistance
5. **Voice Chat**: Real-time voice communication

## 🐛 Troubleshooting

### Common Issues

1. **Messages Not Appearing**:
   - Check WebSocket connection status
   - Verify player is in the correct room
   - Check server logs for errors

2. **NPC Not Responding**:
   - Verify NPC exists and is in the same room
   - Check NPC ID in the database
   - Ensure player has required permissions

3. **WebSocket Errors**:
   - Restart the server
   - Check port availability
   - Verify client connections

### Debug Mode

Enable debug output in the CLI:
```python
# In websocket_cli.py, the debug output is already enabled
# Look for messages starting with 🔍, 📥, 📨, etc.
```

## 📚 API Reference

### Chat Message Types

```python
class ChatType(Enum):
    GLOBAL = "global"      # All players
    ROOM = "room"          # Room-specific
    PRIVATE = "private"    # Player-to-player
    SYSTEM = "system"      # Game notifications
    NPC = "npc"           # NPC interactions
```

### NPC Dispositions

```python
class NPCDisposition(Enum):
    FRIENDLY = "friendly"      # Helpful and welcoming
    NEUTRAL = "neutral"        # Indifferent
    HOSTILE = "hostile"        # Aggressive
    FEARFUL = "fearful"        # Scared of player
    RESPECTFUL = "respectful"  # Respects player strength
```

### NPC Roles

```python
class NPCRole(Enum):
    MERCHANT = "merchant"      # Sells goods
    QUEST_GIVER = "quest_giver" # Provides missions
    COMBAT_MOB = "combat_mob"  # Hostile enemy
    INFORMANT = "informant"    # Has information
    COMPANION = "companion"    # Travels with player
    BOSS = "boss"             # Powerful enemy
```

## 🎯 Getting Started

1. **Start the Server**:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

2. **Connect Multiple Clients**:
   ```bash
   # Terminal 1
   python websocket_cli.py --player 1
   
   # Terminal 2
   python websocket_cli.py --player 2
   ```

3. **Test Chat Commands**:
   ```bash
   # In Player 1's terminal
   /say Hello everyone!
   
   # In Player 2's terminal
   /tell 1 Hi there!
   ```

4. **Chat with NPCs**:
   ```bash
   /npc 1 What's your name?
   ```

The chat system is now fully integrated with the WebSocket infrastructure, providing real-time communication and intelligent NPC interactions! 🎉
