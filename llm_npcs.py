#!/usr/bin/env python3
"""
LLM-Powered NPC Framework
NPCs that can chat intelligently and react based on player stats
"""

import json
import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import random
import deepseek_integration

class NPCDisposition(Enum):
    """How the NPC feels about the player"""
    FRIENDLY = "friendly"
    NEUTRAL = "neutral"
    HOSTILE = "hostile"
    FEARFUL = "fearful"
    RESPECTFUL = "respectful"

class NPCRole(Enum):
    """Role of the NPC in the game"""
    MERCHANT = "merchant"
    QUEST_GIVER = "quest_giver"
    COMBAT_MOB = "combat_mob"
    INFORMANT = "informant"
    COMPANION = "companion"
    BOSS = "boss"

@dataclass
class NPCStats:
    """Base stats for NPCs"""
    health: int = 100
    max_health: int = 100
    level: int = 1
    attack: int = 10
    defense: int = 5
    intelligence: int = 10
    charisma: int = 10
    reputation: int = 0  # How well-known/respected they are

@dataclass
class NPCContext:
    """Context for NPC interactions"""
    player_level: int
    player_reputation: int
    player_health: int
    player_gold: int
    room_id: int
    time_of_day: str = "day"
    weather: str = "clear"
    recent_events: List[str] = field(default_factory=list)

class BaseLLMNPC:
    """Base class for LLM-powered NPCs"""
    
    def __init__(self, npc_id: int, name: str, description: str, 
                 disposition: NPCDisposition, role: NPCRole, stats: NPCStats):
        self.npc_id = npc_id
        self.name = name
        self.description = description
        self.disposition = disposition
        self.role = role
        self.stats = stats
        self.conversation_history: List[Dict] = []
        self.personality_traits: List[str] = []
        self.knowledge_domains: List[str] = []
        self.current_room_id: int = 1
        
    async def generate_response(self, player_message: str, context: NPCContext) -> str:
        """
        Generate an intelligent response based on:
        - Player message
        - Player stats
        - NPC personality
        - Current context
        - Conversation history
        """
        # Try to use the LLM (DeepSeek) first, fallback to rule-based if not available
        try:
            manager = deepseek_integration.npc_manager
            if manager and manager.client:
                # Use DeepSeek for intelligent responses
                response = await manager.generate_npc_response(
                    npc_id=self.npc_id,
                    npc_name=self.name,
                    npc_role=self.role.value,
                    personality_traits=self.personality_traits,
                    knowledge_domains=self.knowledge_domains,
                    player_message=player_message,
                    context={
                        'player_level': context.player_level,
                        'player_reputation': context.player_reputation,
                        'player_health': context.player_health,
                        'player_gold': context.player_gold,
                        'room_id': context.room_id,
                        'time_of_day': context.time_of_day,
                        'weather': context.weather
                    }
                )
                self._update_conversation_history(player_message, response, context)
                return response
        except Exception as e:
            print(f"DeepSeek not available, using rule-based responses: {e}")
        
        # Fallback to rule-based responses
        response = await self._rule_based_response(player_message, context)
        self._update_conversation_history(player_message, response, context)
        return response
    
    async def _rule_based_response(self, player_message: str, context: NPCContext) -> str:
        """Rule-based response system (placeholder for LLM)"""
        message_lower = player_message.lower()
        
        # Greeting responses
        if any(word in message_lower for word in ['hello', 'hi', 'hey', 'greetings']):
            return self._generate_greeting(context)
        
        # Question responses
        if '?' in player_message:
            return self._generate_question_response(player_message, context)
        
        # Role-specific responses
        if self.role == NPCRole.MERCHANT:
            return self._generate_merchant_response(player_message, context)
        elif self.role == NPCRole.QUEST_GIVER:
            return self._generate_quest_response(player_message, context)
        elif self.role == NPCRole.COMBAT_MOB:
            return self._generate_combat_response(player_message, context)
        
        # Default response
        return self._generate_default_response(context)
    
    def _generate_greeting(self, context: NPCContext) -> str:
        """Generate a contextual greeting"""
        if self.disposition == NPCDisposition.FRIENDLY:
            if context.player_reputation > 50:
                return f"Ah, {context.player_level}! It's always a pleasure to see a hero of your caliber!"
            else:
                return f"Hello there, traveler! Welcome to our humble establishment."
        elif self.disposition == NPCDisposition.HOSTILE:
            return f"Hmph. What do you want, weakling?"
        elif self.disposition == NPCDisposition.FEARFUL:
            if context.player_level > self.stats.level + 5:
                return f"*nervously* Oh... oh my... a level {context.player_level} adventurer..."
            else:
                return f"*cautiously* Hello... can I help you?"
        
        return f"Greetings, traveler."
    
    def _generate_question_response(self, question: str, context: NPCContext) -> str:
        """Generate a response to a question"""
        question_lower = question.lower()
        
        if 'name' in question_lower:
            return f"My name is {self.name}. I'm a {self.role.value.replace('_', ' ')} in these parts."
        
        if 'help' in question_lower or 'what can you do' in question_lower:
            return self._describe_capabilities(context)
        
        if 'quest' in question_lower or 'mission' in question_lower:
            if self.role == NPCRole.QUEST_GIVER:
                return "I do have some tasks that need doing, if you're interested in helping out."
            else:
                return "I'm not really the quest-giving type, but I'm sure someone around here could use your help."
        
        return "That's an interesting question. Let me think about it..."
    
    def _generate_merchant_response(self, message: str, context: NPCContext) -> str:
        """Generate merchant-specific responses"""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ['buy', 'purchase', 'shop', 'trade']):
            if context.player_gold > 0:
                return "Ah, a customer! I have some fine wares that might interest you. What are you looking for?"
            else:
                return "I'd be happy to show you my wares, but it looks like you might be a bit short on gold."
        
        if 'sell' in message_lower:
            return "I'm always interested in buying quality items from adventurers. What do you have to offer?"
        
        return "Welcome to my shop! Feel free to browse my selection."
    
    def _generate_quest_response(self, message: str, context: NPCContext) -> str:
        """Generate quest-giver responses"""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ['quest', 'mission', 'help', 'task']):
            if context.player_level >= 5:
                return "Ah, you look capable enough! I do have a dangerous mission that needs a brave soul like yourself."
            else:
                return "You seem eager to help, but I'm afraid the tasks I have might be too dangerous for someone of your experience."
        
        return "If you're looking for adventure, you've come to the right place!"
    
    def _generate_combat_response(self, message: str, context: NPCContext) -> str:
        """Generate combat mob responses"""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ['attack', 'fight', 'battle']):
            if context.player_level > self.stats.level:
                return f"*growls menacingly* You think you can take me on, level {context.player_level}? We'll see about that!"
            else:
                return f"*laughs darkly* A level {context.player_level} challenging me? This will be fun!"
        
        return "*snarls* What do you want, meat?"
    
    def _generate_default_response(self, context: NPCContext) -> str:
        """Generate a default response based on context"""
        if self.disposition == NPCDisposition.FRIENDLY:
            responses = [
                "Is there anything I can help you with?",
                "Feel free to ask if you need anything!",
                "I'm here if you need assistance."
            ]
        elif self.disposition == NPCDisposition.HOSTILE:
            responses = [
                "What do you want?",
                "I don't have time for this.",
                "Get to the point or get lost."
            ]
        else:
            responses = [
                "I'm listening.",
                "Go on...",
                "What can I do for you?"
            ]
        
        return random.choice(responses)
    
    def _describe_capabilities(self, context: NPCContext) -> str:
        """Describe what the NPC can do"""
        if self.role == NPCRole.MERCHANT:
            return "I'm a merchant by trade. I buy and sell goods, and I'm always looking for quality items."
        elif self.role == NPCRole.QUEST_GIVER:
            return "I have information and tasks for adventurers. If you're looking for adventure, I can point you in the right direction."
        elif self.role == NPCRole.COMBAT_MOB:
            return "I'm a warrior. I fight for what I believe in, and I don't back down from a challenge."
        elif self.role == NPCRole.INFORMANT:
            return "I know things. Secrets, rumors, information that might be valuable to the right person."
        
        return "I'm just a simple NPC trying to get by in this world."
    
    def _update_conversation_history(self, player_message: str, npc_response: str, context: NPCContext):
        """Update conversation history for context"""
        conversation_entry = {
            'timestamp': asyncio.get_event_loop().time(),
            'player_message': player_message,
            'npc_response': npc_response,
            'context': {
                'player_level': context.player_level,
                'player_reputation': context.player_reputation,
                'room_id': context.room_id
            }
        }
        
        self.conversation_history.append(conversation_entry)
        
        # Keep only last 10 conversations
        if len(self.conversation_history) > 10:
            self.conversation_history.pop(0)
    
    def get_disposition_towards_player(self, context: NPCContext) -> NPCDisposition:
        """Calculate current disposition based on context and history"""
        base_disposition = self.disposition
        
        # Modify based on player reputation
        if context.player_reputation > 50:
            if base_disposition == NPCDisposition.NEUTRAL:
                return NPCDisposition.FRIENDLY
            elif base_disposition == NPCDisposition.FEARFUL:
                return NPCDisposition.RESPECTFUL
        
        # Modify based on level difference
        level_diff = context.player_level - self.stats.level
        if level_diff > 10:
            if base_disposition == NPCDisposition.HOSTILE:
                return NPCDisposition.FEARFUL
            elif base_disposition == NPCDisposition.NEUTRAL:
                return NPCDisposition.RESPECTFUL
        
        return base_disposition
    
    def should_attack_player(self, context: NPCContext) -> bool:
        """Determine if NPC should attack the player"""
        if self.role != NPCRole.COMBAT_MOB and self.role != NPCRole.BOSS:
            return False
        
        current_disposition = self.get_disposition_towards_player(context)
        if current_disposition == NPCDisposition.HOSTILE:
            return True
        
        # Random chance based on disposition
        if current_disposition == NPCDisposition.NEUTRAL:
            return random.random() < 0.1  # 10% chance
        
        return False

# Example NPC implementations
class MerchantNPC(BaseLLMNPC):
    """Merchant NPC that buys and sells goods"""
    
    def __init__(self, npc_id: int, name: str, description: str):
        stats = NPCStats(
            health=80,
            max_health=80,
            level=3,
            attack=5,
            defense=3,
            intelligence=15,
            charisma=18,
            reputation=25
        )
        super().__init__(npc_id, name, description, NPCDisposition.FRIENDLY, NPCRole.MERCHANT, stats)
        self.personality_traits = ["greedy", "friendly", "knowledgeable"]
        self.knowledge_domains = ["trade", "economics", "local gossip"]

class QuestGiverNPC(BaseLLMNPC):
    """NPC that gives quests to players"""
    
    def __init__(self, npc_id: int, name: str, description: str):
        stats = NPCStats(
            health=100,
            max_health=100,
            level=5,
            attack=8,
            defense=6,
            intelligence=16,
            charisma=14,
            reputation=40
        )
        super().__init__(npc_id, name, description, NPCDisposition.FRIENDLY, NPCRole.QUEST_GIVER, stats)
        self.personality_traits = ["wise", "helpful", "experienced"]
        self.knowledge_domains = ["quests", "lore", "adventure"]

class CombatMobNPC(BaseLLMNPC):
    """Hostile NPC that attacks players"""
    
    def __init__(self, npc_id: int, name: str, description: str, level: int = 3):
        stats = NPCStats(
            health=100,
            max_health=100,
            level=level,
            attack=15,
            defense=8,
            intelligence=8,
            charisma=5,
            reputation=0
        )
        super().__init__(npc_id, name, description, NPCDisposition.HOSTILE, NPCRole.COMBAT_MOB, stats)
        self.personality_traits = ["aggressive", "territorial", "fearless"]
        self.knowledge_domains = ["combat", "territory", "threats"]
