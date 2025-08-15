"""
Utility functions and constants for the RPG Game API
"""
from typing import Dict, Any, Optional
from datetime import datetime
import json

# Game Constants
ABILITY_NAMES = ["str", "dex", "con", "intel", "wis", "cha"]
ABILITY_DISPLAY_NAMES = {
    "str": "Strength",
    "dex": "Dexterity", 
    "con": "Constitution",
    "intel": "Intelligence",
    "wis": "Wisdom",
    "cha": "Charisma"
}

# Utility Functions
def calculate_ability_modifier(ability_score: int) -> int:
    """Calculate ability modifier from ability score"""
    return (ability_score - 10) // 2

def format_datetime(dt: datetime) -> str:
    """Format datetime to ISO string"""
    return dt.isoformat() if dt else None

def safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    """Safely get attribute from object"""
    return getattr(obj, attr, default)

def dict_from_model(model: Any, exclude: Optional[list] = None) -> Dict[str, Any]:
    """Convert SQLAlchemy model to dictionary, excluding specified fields"""
    if exclude is None:
        exclude = []
    
    result = {}
    for column in model.__table__.columns:
        if column.name not in exclude:
            value = getattr(model, column.name)
            if isinstance(value, datetime):
                result[column.name] = format_datetime(value)
            else:
                result[column.name] = value
    
    return result

def validate_ability_scores(scores: Dict[str, int]) -> bool:
    """Validate ability scores are within valid range"""
    from config import MIN_ABILITY_SCORE, MAX_ABILITY_SCORE
    
    for score in scores.values():
        if not (MIN_ABILITY_SCORE <= score <= MAX_ABILITY_SCORE):
            return False
    return True

def format_currency(amount: int) -> str:
    """Format currency amount"""
    if amount == 0:
        return "0 gold"
    elif amount == 1:
        return "1 gold piece"
    else:
        return f"{amount} gold pieces"

def sanitize_input(text: str, max_length: int = 1000) -> str:
    """Sanitize user input text"""
    if not text:
        return ""
    
    # Remove potentially dangerous characters
    sanitized = text.strip()
    
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    
    return sanitized

def log_action(action: str, player_id: int, details: str = "") -> None:
    """Log player actions for debugging"""
    timestamp = datetime.now().isoformat()
    log_entry = f"[{timestamp}] Player {player_id}: {action}"
    if details:
        log_entry += f" - {details}"
    print(log_entry)  # In production, use proper logging
