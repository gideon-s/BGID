"""Pydantic schemas for auth + character management."""
import re
from typing import Optional, List
from datetime import datetime

from pydantic import BaseModel, field_validator

import config
import classes


def _validate_password(v: str) -> str:
    if len(v) < config.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {config.PASSWORD_MIN_LENGTH} characters")
    if not re.search(r"[A-Za-z]", v) or not re.search(r"[0-9]", v):
        raise ValueError("Password must contain at least one letter and one number")
    return v


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip()
        if not (3 <= len(v) <= 50):
            raise ValueError("Username must be between 3 and 50 characters")
        if not re.match(r"^[A-Za-z0-9_-]+$", v):
            raise ValueError("Username may only contain letters, numbers, underscores, and hyphens")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        return _validate_password(v)


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------- Characters ----------
class CharacterCreate(BaseModel):
    name: str
    char_class: str = classes.DEFAULT_CLASS   # validated against classes.py below
    gender: str = "none"                       # female/male/none or a custom value

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = v.strip()
        if not (2 <= len(v) <= 100):
            raise ValueError("Character name must be between 2 and 100 characters")
        return v

    @field_validator("char_class")
    @classmethod
    def class_valid(cls, v: str) -> str:
        v = (v or classes.DEFAULT_CLASS).strip().lower()
        if v not in classes.SELECTABLE:
            raise ValueError(f"Pick a class: {', '.join(classes.SELECTABLE)}")
        return v

    @field_validator("gender")
    @classmethod
    def gender_valid(cls, v: str) -> str:
        v = (v or "none").strip()
        if len(v) > 50:
            raise ValueError("Gender must be at most 50 characters")
        return v or "none"


class CharacterOut(BaseModel):
    id: int
    name: str
    room_id: int
    level: int
    experience: int = 0
    health: int
    max_health: int
    char_class: str = "wanderer"
    gender: str = ""
    mana: int = 0
    max_mana: int = 0

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    user: UserResponse
    characters: List[CharacterOut]


class AuthResponse(BaseModel):
    user: UserResponse
    tokens: TokenResponse
