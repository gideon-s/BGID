# RPG Game API - Refactored

A modern, well-structured RPG game API built with FastAPI, featuring real-time multiplayer, database management, and LLM-powered NPCs.

## 🏗️ Project Structure

```
app/
├── config.py              # Configuration settings and constants
├── utils.py               # Utility functions and helpers
├── models.py              # SQLAlchemy ORM models
├── schemas.py             # Pydantic validation schemas
├── services.py            # Business logic services
├── main.py                # FastAPI application and endpoints
├── database.py            # Database connection and session management
├── websocket_manager.py   # WebSocket connection management
├── chat_system.py         # Chat message handling
├── chat_schemas.py        # Chat-specific schemas
├── llm_npcs.py           # LLM-powered NPC system
├── deepseek_integration.py # DeepSeek LLM integration
├── admin.py               # Admin CLI for database management
├── cli.py                 # Game CLI interface
├── websocket_cli.py       # WebSocket-enabled CLI
├── seed.py                # Database seeding script
├── run.py                 # Server startup script
└── requirements.txt       # Python dependencies
```

## 🚀 Key Improvements

### 1. **Separation of Concerns**
- **Models**: Pure SQLAlchemy ORM models with business logic methods
- **Schemas**: Pydantic validation with proper field constraints
- **Services**: Business logic separated from API endpoints
- **API**: Clean, focused endpoint definitions

### 2. **Configuration Management**
- Centralized configuration in `config.py`
- Environment variable support
- Consistent constants across the application

### 3. **Enhanced Data Models**
- Proper indexing for performance
- Timestamp tracking (created_at, updated_at)
- Better relationship definitions with cascading
- Improved validation and constraints

### 4. **Service Layer Architecture**
- `PlayerService`: Player management operations
- `RoomService`: Room and location management
- `ItemService`: Item handling and movement
- `NpcService`: NPC management and interactions
- `GameActionService`: Game action processing

### 5. **Improved API Design**
- Proper HTTP status codes
- Consistent response formats
- Better error handling
- API documentation with tags
- Health check endpoint

### 6. **Enhanced Admin CLI**
- Cleaner command structure
- Better error handling
- Improved user experience
- Configuration-driven object schemas

## 🛠️ Installation & Setup

### 1. **Clone and Setup**
```bash
git clone <repository>
cd app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. **Configuration**
Copy the example configuration and modify as needed:
```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. **Database Setup**
```bash
# The database will be created automatically on first run
python3 run.py
```

## 🎮 Usage

### **Start the Server**
```bash
python3 run.py
# Or directly with uvicorn:
uvicorn main:app --host 127.0.0.1 --port 8000
```

### **Admin CLI**
```bash
python3 admin.py
```

Available commands:
- `list <type>` - List objects (players, rooms, items, npcs)
- `show <type> <id>` - Show object details
- `create <type>` - Create new object
- `count` - Show database statistics
- `help` - Show help information

### **Game CLI**
```bash
python3 cli.py
```

### **WebSocket CLI**
```bash
python3 websocket_cli.py
```

## 📚 API Endpoints

### **Core Endpoints**
- `GET /` - API information
- `GET /health` - Health check
- `GET /docs` - Interactive API documentation

### **Players**
- `GET /players/` - List players
- `POST /players/` - Create player
- `GET /players/{id}` - Get player
- `PUT /players/{id}` - Update player
- `DELETE /players/{id}` - Delete player
- `GET /players/{id}/sheet` - Get character sheet

### **Rooms**
- `GET /rooms/` - List rooms
- `POST /rooms/` - Create room
- `GET /rooms/{id}` - Get room
- `GET /rooms/{id}/state` - Get room state

### **Items**
- `GET /items/` - List items
- `POST /items/` - Create item
- `GET /items/{id}` - Get item

### **NPCs**
- `GET /npcs/` - List NPCs
- `POST /npcs/` - Create NPC
- `GET /npcs/{id}` - Get NPC
- `GET /npcs/{id}/sheet` - Get NPC sheet

### **Game Actions**
- `POST /action` - Perform game action

### **Chat System**
- `POST /chat/send` - Send chat message
- `GET /chat/history/{type}` - Get chat history
- `POST /chat/npc` - Chat with NPC

### **WebSocket**
- `WS /ws/{player_id}` - Real-time multiplayer

## 🔧 Configuration Options

### **Environment Variables**
```bash
# Server
HOST=127.0.0.1
PORT=8000
DEBUG=true

# Database
DATABASE_URL=sqlite:///./game.db
DATABASE_ECHO=false

# Game Settings
DEFAULT_PLAYER_HEALTH=10
DEFAULT_PLAYER_LEVEL=1
DEFAULT_ABILITY_SCORE=10
DEFAULT_NPC_HEALTH=8

# DeepSeek (LLM)
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT=30
```

## 🎯 Game Features

### **Character System**
- 6 ability scores (STR, DEX, CON, INT, WIS, CHA)
- Health and experience tracking
- Level progression
- Inventory management

### **World System**
- Room-based navigation
- Item placement and movement
- NPC interactions
- Real-time multiplayer

### **Combat & Actions**
- Move between rooms
- Pick up and drop items
- Use items
- NPC reactions and dispositions

### **Chat System**
- Global, room, and private messaging
- NPC conversations with LLM
- Message history and persistence

## 🧪 Testing

### **Run Tests**
```bash
pytest
pytest --asyncio-mode=auto  # For async tests
```

### **API Testing**
```bash
# Test health endpoint
curl http://localhost:8000/health

# Test player creation
curl -X POST "http://localhost:8000/players/" \
  -H "Content-Type: application/json" \
  -d '{"name": "TestPlayer", "room_id": 1}'
```

## 🚀 Development

### **Code Style**
- Follow PEP 8
- Use type hints
- Document all functions and classes
- Keep functions focused and small

### **Adding New Features**
1. **Models**: Add to `models.py`
2. **Schemas**: Add to `schemas.py`
3. **Services**: Add to `services.py`
4. **API**: Add to `main.py`
5. **Admin**: Update `admin.py` if needed

### **Database Migrations**
```bash
# Create migration
alembic revision --autogenerate -m "Description"

# Apply migration
alembic upgrade head
```

## 🔍 Monitoring & Debugging

### **Logs**
- Action logging in services
- WebSocket connection tracking
- API request/response logging

### **Health Checks**
- Database connectivity
- Service status
- WebSocket manager status

## 📈 Performance Considerations

- Database indexing on frequently queried fields
- Connection pooling for database sessions
- Efficient WebSocket message broadcasting
- Pagination for large result sets

## 🔒 Security Features

- Input validation with Pydantic
- SQL injection protection via SQLAlchemy
- WebSocket authentication
- Rate limiting (can be added)

## 🌟 Future Enhancements

- [ ] User authentication and authorization
- [ ] Combat system
- [ ] Quest system
- [ ] Economy and trading
- [ ] Guild/clan system
- [ ] Achievement system
- [ ] Analytics and metrics
- [ ] Docker containerization
- [ ] Kubernetes deployment
- [ ] CI/CD pipeline

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License.

## 🆘 Support

- Check the API documentation at `/docs`
- Review the code comments
- Open an issue for bugs
- Submit feature requests

---

**Happy Gaming! 🎮✨**
