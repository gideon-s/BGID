#!/usr/bin/env python3
"""
DeepSeek Integration for LLM-Powered NPCs

Uses the DeepSeek API (OpenAI-compatible) for intelligent NPC responses.
Requires a DEEPSEEK_API_KEY (see config.py / .env).

This module is a drop-in replacement for the previous Ollama integration and
preserves the same public surface:
    - initialize_deepseek_npcs() / cleanup_deepseek_npcs()
    - global `npc_manager`
    - DeepSeekNPCManager.generate_npc_response(...)
"""

import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from openai import AsyncOpenAI

import config


@dataclass
class DeepSeekConfig:
    """Configuration for DeepSeek integration"""
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 500
    timeout: int = 30

    @classmethod
    def from_settings(cls) -> "DeepSeekConfig":
        """Build a config from the project's config.py / environment."""
        return cls(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            model=config.DEEPSEEK_MODEL,
            temperature=config.DEEPSEEK_TEMPERATURE,
            max_tokens=config.DEEPSEEK_MAX_TOKENS,
            timeout=config.DEEPSEEK_TIMEOUT,
        )


class DeepSeekClient:
    """Client for interacting with the DeepSeek API (OpenAI-compatible)"""

    def __init__(self, cfg: DeepSeekConfig = None):
        self.config = cfg or DeepSeekConfig.from_settings()
        self.client: Optional[AsyncOpenAI] = None

    async def __aenter__(self):
        """Async context manager entry"""
        if not self.config.api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. Add it to your environment or .env file."
            )
        self.client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.close()

    async def generate_response(self, prompt: str, system_prompt: str = None) -> str:
        """Generate a response using DeepSeek's chat completions API"""
        if not self.client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                stream=False,
            )
            return (response.choices[0].message.content or "").strip()

        except asyncio.TimeoutError:
            raise Exception("Request to DeepSeek timed out")
        except Exception as e:
            raise Exception(f"Error calling DeepSeek: {e}")

    async def test_connection(self) -> bool:
        """Test if the DeepSeek API is reachable and the key is valid"""
        if not self.client:
            return False
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False


class NPCPromptBuilder:
    """Builds context-aware prompts for NPCs"""

    @staticmethod
    def build_system_prompt(npc_name: str, npc_role: str, personality_traits: List[str],
                            knowledge_domains: List[str]) -> str:
        """Build the system prompt for an NPC"""
        traits_str = ", ".join(personality_traits)
        domains_str = ", ".join(knowledge_domains)

        return f"""You are {npc_name}, a {npc_role} in a fantasy RPG game.

Your personality traits are: {traits_str}
Your areas of expertise include: {domains_str}

You should:
- Stay in character at all times
- Respond naturally to player questions and statements
- Use your knowledge domains to provide relevant information
- Express your personality traits through your responses
- Keep responses concise but engaging (2-4 sentences max)
- If asked about game mechanics, provide helpful hints
- If the player is being rude or aggressive, respond appropriately to your personality

Remember: You are an NPC in a game, not a game master or player. Stay in character!"""

    @staticmethod
    def build_user_prompt(player_message: str, context: Dict[str, Any]) -> str:
        """Build the user prompt with context"""
        context_str = f"""
Player Context:
- Level: {context.get('player_level', 'Unknown')}
- Reputation: {context.get('player_reputation', 'Unknown')}
- Health: {context.get('player_health', 'Unknown')}
- Gold: {context.get('player_gold', 'Unknown')}
- Current Room: {context.get('room_id', 'Unknown')}
- Time: {context.get('time_of_day', 'day')}
- Weather: {context.get('weather', 'clear')}

Player Message: {player_message}

Respond naturally as your character would to this player in this context."""

        return context_str


class DeepSeekNPCManager:
    """Manages LLM-powered NPC interactions using DeepSeek"""

    def __init__(self, cfg: DeepSeekConfig = None):
        self.config = cfg or DeepSeekConfig.from_settings()
        self.client: Optional[DeepSeekClient] = None
        self.prompt_builder = NPCPromptBuilder()
        self.conversation_cache: Dict[int, List[Dict]] = {}  # npc_id -> conversation history

    async def initialize(self):
        """Initialize the DeepSeek client.

        On failure, leaves ``self.client`` as ``None`` so the manager never
        looks "ready" when it isn't (callers fall back to rule-based replies).
        """
        client = DeepSeekClient(self.config)
        await client.__aenter__()

        # Test connection; tear down on failure so we don't leak a half-open client
        if not await client.test_connection():
            await client.__aexit__(None, None, None)
            raise Exception(
                "Cannot connect to DeepSeek. Check DEEPSEEK_API_KEY and network access."
            )

        self.client = client
        print("✅ Connected to DeepSeek successfully!")

    async def cleanup(self):
        """Clean up resources"""
        if self.client:
            await self.client.__aexit__(None, None, None)

    async def generate_npc_response(self, npc_id: int, npc_name: str, npc_role: str,
                                  personality_traits: List[str], knowledge_domains: List[str],
                                  player_message: str, context: Dict[str, Any]) -> str:
        """Generate an intelligent NPC response using DeepSeek"""

        if not self.client:
            raise Exception("DeepSeek client not initialized. Call initialize() first.")

        try:
            # Build the system prompt for this NPC
            system_prompt = self.prompt_builder.build_system_prompt(
                npc_name, npc_role, personality_traits, knowledge_domains
            )

            # Build the user prompt with context
            user_prompt = self.prompt_builder.build_user_prompt(player_message, context)

            # Generate response using DeepSeek
            response = await self.client.generate_response(user_prompt, system_prompt)

            # Cache the conversation
            self._cache_conversation(npc_id, player_message, response, context)

            return response

        except Exception as e:
            print(f"Error generating NPC response: {e}")
            # Fallback to a simple response
            return f"{npc_name} seems distracted and gives you a brief response: 'I'm not sure about that.'"

    def _cache_conversation(self, npc_id: int, player_message: str, npc_response: str, context: Dict[str, Any]):
        """Cache conversation history for context"""
        if npc_id not in self.conversation_cache:
            self.conversation_cache[npc_id] = []

        conversation_entry = {
            'timestamp': asyncio.get_event_loop().time(),
            'player_message': player_message,
            'npc_response': npc_response,
            'context': context
        }

        self.conversation_cache[npc_id].append(conversation_entry)

        # Keep only last 10 conversations per NPC
        if len(self.conversation_cache[npc_id]) > 10:
            self.conversation_cache[npc_id].pop(0)

    def get_conversation_history(self, npc_id: int) -> List[Dict]:
        """Get conversation history for an NPC"""
        return self.conversation_cache.get(npc_id, [])

    def clear_conversation_history(self, npc_id: int = None):
        """Clear conversation history"""
        if npc_id is None:
            self.conversation_cache.clear()
        else:
            self.conversation_cache.pop(npc_id, None)


# Global instance
npc_manager: Optional[DeepSeekNPCManager] = None


async def initialize_deepseek_npcs(cfg: DeepSeekConfig = None) -> DeepSeekNPCManager:
    """Initialize the global DeepSeek NPC manager"""
    global npc_manager

    if npc_manager is None:
        manager = DeepSeekNPCManager(cfg)
        # Only publish the global once initialization fully succeeds, so a
        # failed init doesn't leave a half-built manager that looks ready.
        await manager.initialize()
        npc_manager = manager

    return npc_manager


async def cleanup_deepseek_npcs():
    """Clean up the global DeepSeek NPC manager"""
    global npc_manager

    if npc_manager:
        await npc_manager.cleanup()
        npc_manager = None
