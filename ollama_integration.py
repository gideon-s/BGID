#!/usr/bin/env python3
"""
Ollama Integration for LLM-Powered NPCs
Uses local Mistral model for intelligent NPC responses
"""

import asyncio
import json
import aiohttp
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

@dataclass
class OllamaConfig:
    """Configuration for Ollama integration"""
    base_url: str = "http://localhost:11434"
    model: str = "mistral"
    temperature: float = 0.7
    max_tokens: int = 500
    timeout: int = 30

class OllamaClient:
    """Client for interacting with Ollama API"""
    
    def __init__(self, config: OllamaConfig = None):
        self.config = config or OllamaConfig()
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def generate_response(self, prompt: str, system_prompt: str = None) -> str:
        """Generate a response using Ollama"""
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")
        
        # Prepare the request payload
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens
            }
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        try:
            async with self.session.post(
                f"{self.config.base_url}/api/generate",
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("response", "").strip()
                else:
                    error_text = await response.text()
                    raise Exception(f"Ollama API error {response.status}: {error_text}")
        
        except asyncio.TimeoutError:
            raise Exception("Request to Ollama timed out")
        except Exception as e:
            raise Exception(f"Error calling Ollama: {e}")
    
    async def test_connection(self) -> bool:
        """Test if Ollama is running and accessible"""
        try:
            async with self.session.get(f"{self.config.base_url}/api/tags") as response:
                return response.status == 200
        except:
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

class OllamaNPCManager:
    """Manages LLM-powered NPC interactions using Ollama"""
    
    def __init__(self, config: OllamaConfig = None):
        self.config = config or OllamaConfig()
        self.client: Optional[OllamaClient] = None
        self.prompt_builder = NPCPromptBuilder()
        self.conversation_cache: Dict[int, List[Dict]] = {}  # npc_id -> conversation history
    
    async def initialize(self):
        """Initialize the Ollama client"""
        self.client = OllamaClient(self.config)
        await self.client.__aenter__()
        
        # Test connection
        if not await self.client.test_connection():
            raise Exception("Cannot connect to Ollama. Make sure it's running on localhost:11434")
        
        print("✅ Connected to Ollama successfully!")
    
    async def cleanup(self):
        """Clean up resources"""
        if self.client:
            await self.client.__aexit__(None, None, None)
    
    async def generate_npc_response(self, npc_id: int, npc_name: str, npc_role: str,
                                  personality_traits: List[str], knowledge_domains: List[str],
                                  player_message: str, context: Dict[str, Any]) -> str:
        """Generate an intelligent NPC response using Ollama"""
        
        if not self.client:
            raise Exception("Ollama client not initialized. Call initialize() first.")
        
        try:
            # Build the system prompt for this NPC
            system_prompt = self.prompt_builder.build_system_prompt(
                npc_name, npc_role, personality_traits, knowledge_domains
            )
            
            # Build the user prompt with context
            user_prompt = self.prompt_builder.build_user_prompt(player_message, context)
            
            # Generate response using Ollama
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
npc_manager: Optional[OllamaNPCManager] = None

async def initialize_ollama_npcs(config: OllamaConfig = None) -> OllamaNPCManager:
    """Initialize the global Ollama NPC manager"""
    global npc_manager
    
    if npc_manager is None:
        npc_manager = OllamaNPCManager(config)
        await npc_manager.initialize()
    
    return npc_manager

async def cleanup_ollama_npcs():
    """Clean up the global Ollama NPC manager"""
    global npc_manager
    
    if npc_manager:
        await npc_manager.cleanup()
        npc_manager = None
