"""
Configuration settings for the RPG Game API
"""
import os
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from a local .env file if present
load_dotenv()

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./game.db")
DATABASE_ECHO = os.getenv("DATABASE_ECHO", "false").lower() == "true"

# Server Configuration
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Game Configuration
DEFAULT_PLAYER_HEALTH = 10
DEFAULT_PLAYER_LEVEL = 1
DEFAULT_PLAYER_EXP = 0
DEFAULT_ABILITY_SCORE = 10
DEFAULT_NPC_HEALTH = 8

# WebSocket Configuration
WEBSOCKET_PING_INTERVAL = 20
WEBSOCKET_PING_TIMEOUT = 20

# DeepSeek (LLM) Configuration
# DeepSeek exposes an OpenAI-compatible API. Set DEEPSEEK_API_KEY in your
# environment or .env file. Get a key at https://platform.deepseek.com/
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.7"))
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "500"))
DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "30"))

# Chat Configuration
MAX_CHAT_MESSAGE_LENGTH = 1000
CHAT_HISTORY_LIMIT = 100

# Validation Constraints
MIN_ABILITY_SCORE = 1
MAX_ABILITY_SCORE = 20
MIN_REACTION_VALUE = 0
MAX_REACTION_VALUE = 100

# File Paths
DATABASE_FILE = "game.db"
LOG_FILE = "server.log"
