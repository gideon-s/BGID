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
# Seconds after a hostile mob is slain before it respawns at its home tile with
# full health (so a one-mob zone stays fightable).
MOB_RESPAWN_SECONDS = float(os.getenv("MOB_RESPAWN_SECONDS", "15"))
# Brief invulnerability after a player respawns, so an adjacent hostile can't
# chain-kill them before they get a chance to move away.
RESPAWN_GRACE_SECONDS = float(os.getenv("RESPAWN_GRACE_SECONDS", "3"))
MOB_CHATTER_COOLDOWN_SECONDS = float(os.getenv("MOB_CHATTER_COOLDOWN_SECONDS", "8"))  # per-mob smack-talk cooldown
FOV_RADIUS = int(os.getenv("FOV_RADIUS", "8"))  # client view radius
# Global cap on mob smack-talk LLM calls, per room, per minute (distinct from
# the player-`talk` budget — mob chatter is mob-initiated cost).
MOB_CHATTER_RATE_PER_MIN = int(os.getenv("MOB_CHATTER_RATE_PER_MIN", "8"))

# Free-form character appearance/description (feeds the portrait prompt). Capped
# so prompts stay bounded and image-gen cost/quality stays predictable.
APPEARANCE_MAX_LENGTH = int(os.getenv("APPEARANCE_MAX_LENGTH", "400"))

# Rooms where players cannot attack each other (PvP truce). Defaults to the
# starting room (the Foyer) — a safe arrival/respawn hub. Comma-separated ids.
PVP_SAFE_ROOM_IDS = {int(x) for x in
                     os.getenv("PVP_SAFE_ROOM_IDS", str(STARTING_ROOM_ID)).split(",")
                     if x.strip()}

# A locked door, once opened with its key, stays open this long for ALL players
# (a single shared timer); then it re-locks and the key respawns at its home tile.
# Using the key CONSUMES it ("crumbles to dust"). See world.door_unlocks.
DOOR_UNLOCK_SECONDS = float(os.getenv("DOOR_UNLOCK_SECONDS", "600"))   # 10 minutes

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

# Novita (image generation) Configuration — Phase 5 character/NPC portraits.
# Novita exposes a text-to-image HTTP API (NOT OpenAI-compatible). Set
# NOVITA_API_KEY in your environment or .env file. Get a key at
# https://novita.ai/ — until it's set, portraits are dark by default and the
# game falls back to emoji glyphs (exactly how DeepSeek-off degrades to canned
# barbs). Generation is generate-once + hash-cached, so N subjects = N calls
# ever (see portraits.py).
NOVITA_API_KEY = os.getenv("NOVITA_API_KEY", "")
NOVITA_BASE_URL = os.getenv("NOVITA_BASE_URL", "https://api.novita.ai")
# Per-purpose models (see portraits.STYLES). Both default to Standard SDXL 1.0
# checkpoints, so they share the sampler params below. Swap either via .env —
# no code change. Browse Novita's catalog (GET /v3/model) for alternatives.
#   - Portraits: ZavyChromaXL — painterly fantasy character busts.
#   - Tokens:    SDXL Unstable Diffusers — versatile "game art" model, good for
#                top-down overhead RPG map tokens. (Token generation is a future
#                phase; the model is configured now so the seam is ready.)
NOVITA_PORTRAIT_MODEL = os.getenv("NOVITA_PORTRAIT_MODEL", "zavychromaxl_v40_253521.safetensors")
NOVITA_PORTRAIT_WIDTH = int(os.getenv("NOVITA_PORTRAIT_WIDTH", "1024"))
NOVITA_PORTRAIT_HEIGHT = int(os.getenv("NOVITA_PORTRAIT_HEIGHT", "1024"))
NOVITA_TOKEN_MODEL = os.getenv("NOVITA_TOKEN_MODEL", "sdxlUnstableDiffusers_v11_216694.safetensors")
NOVITA_TOKEN_WIDTH = int(os.getenv("NOVITA_TOKEN_WIDTH", "768"))
NOVITA_TOKEN_HEIGHT = int(os.getenv("NOVITA_TOKEN_HEIGHT", "768"))
# Shared sampler params (tuned for Standard SDXL; Turbo/Lightning models would
# need fewer steps + lower guidance, so prefer Standard checkpoints).
NOVITA_STEPS = int(os.getenv("NOVITA_STEPS", "28"))
NOVITA_GUIDANCE_SCALE = float(os.getenv("NOVITA_GUIDANCE_SCALE", "7.0"))
NOVITA_SAMPLER = os.getenv("NOVITA_SAMPLER", "DPM++ 2M Karras")
# Total seconds to wait for an async txt2img task to finish (POST then poll the
# task-result endpoint). Caps the poll loop; a slow/stuck job just leaves the
# glyph in place.
NOVITA_TIMEOUT = int(os.getenv("NOVITA_TIMEOUT", "120"))
NOVITA_POLL_INTERVAL = float(os.getenv("NOVITA_POLL_INTERVAL", "2.0"))
# Cost guard: max portrait generations running concurrently. The hash dedup +
# in-flight guard already bound *identical* subjects to one call; this bounds a
# flood of *distinct* new subjects from fanning out unbounded API calls at once.
PORTRAIT_MAX_CONCURRENT = int(os.getenv("PORTRAIT_MAX_CONCURRENT", "2"))

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
