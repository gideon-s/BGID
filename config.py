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

# Auth / JWT Configuration
# JWT_SECRET signs access + refresh tokens. MUST be set in production (.env).
# If blank, security.py generates an ephemeral per-process secret (fine for
# local dev/tests — tokens just don't survive a restart) and logs a warning.
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
# The room new characters spawn into.
STARTING_ROOM_ID = int(os.getenv("STARTING_ROOM_ID", "1"))
# Comma-separated usernames granted the admin role at registration. The very
# first account to register also becomes admin if no admin exists yet.
ADMIN_USERNAMES = [u.strip().lower() for u in os.getenv("ADMIN_USERNAMES", "").split(",") if u.strip()]
# Password policy minimum length (registration).
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))
# Max characters a single account may own.
MAX_CHARACTERS_PER_ACCOUNT = int(os.getenv("MAX_CHARACTERS_PER_ACCOUNT", "5"))

# Rate limits for LLM NPC conversation (`talk` / POST /chat/npc), per account.
# Each DeepSeek call costs money; these cap burst and sustained usage. Enforced
# in-memory (single worker). Set either to 0 to block `talk` entirely.
TALK_RATE_PER_MIN = int(os.getenv("TALK_RATE_PER_MIN", "10"))
TALK_RATE_PER_HOUR = int(os.getenv("TALK_RATE_PER_HOUR", "120"))

# Real-time tile combat (Phase 1 graphical overhaul). The combat tick drives
# mob AI and is separate from the slow 15s regen tick. Move cooldown bounds how
# fast a player can step. Mob chatter (smack-talk) is throttled per-mob.
COMBAT_TICK_SECONDS = float(os.getenv("COMBAT_TICK_SECONDS", "0.3"))   # mob AI cadence
MOVE_COOLDOWN_SECONDS = float(os.getenv("MOVE_COOLDOWN_SECONDS", "0.12"))  # per-player move rate cap
# Mob "speed": min seconds between a mob's steps / attacks, decoupled from the
# tick rate so the tick can stay snappy without mobs zipping a tile every tick.
MOB_MOVE_COOLDOWN_SECONDS = float(os.getenv("MOB_MOVE_COOLDOWN_SECONDS", "0.5"))
MOB_ATTACK_COOLDOWN_SECONDS = float(os.getenv("MOB_ATTACK_COOLDOWN_SECONDS", "1.2"))
MOB_CHATTER_COOLDOWN_SECONDS = float(os.getenv("MOB_CHATTER_COOLDOWN_SECONDS", "8"))  # per-mob smack-talk cooldown
FOV_RADIUS = int(os.getenv("FOV_RADIUS", "8"))  # client view radius
# Global cap on mob smack-talk LLM calls, per room, per minute (distinct from
# the player-`talk` budget — mob chatter is mob-initiated cost).
MOB_CHATTER_RATE_PER_MIN = int(os.getenv("MOB_CHATTER_RATE_PER_MIN", "8"))

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
