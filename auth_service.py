"""Auth + character business logic (sync SQLAlchemy).

Adapted from dreamcrawler's app/services/auth.py for BGID's sync session and
integer ids. Username is the login identity; email is optional/unverified.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

import config
import models
import auth_schemas as aschemas
from security import (
    hash_password, verify_password, needs_rehash,
    create_access_token, create_refresh_token,
)


def _issue_tokens(user: models.User) -> aschemas.TokenResponse:
    return aschemas.TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(str(user.id))[0],
    )


def _resolve_role(db: Session, username: str) -> str:
    """Admin if the username is in ADMIN_USERNAMES, or if no admin exists yet
    (the first account bootstraps an admin so the world is manageable)."""
    if username.lower() in config.ADMIN_USERNAMES:
        return "admin"
    has_admin = db.query(models.User).filter(models.User.role == "admin").first()
    if has_admin is None:
        return "admin"
    return "player"


def register_user(db: Session, data: aschemas.RegisterRequest) -> tuple[models.User, aschemas.TokenResponse]:
    existing = db.query(models.User).filter(models.User.username == data.username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This username is already taken")
    user = models.User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        role=_resolve_role(db, data.username),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This username is already taken")
    db.refresh(user)
    return user, _issue_tokens(user)


def login_user(db: Session, data: aschemas.LoginRequest) -> tuple[models.User, aschemas.TokenResponse]:
    user = db.query(models.User).filter(models.User.username == data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This account has been deactivated")
    # Transparent rehash if Argon2 params were upgraded.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user, _issue_tokens(user)


# ---------- Refresh-token revocation (DB blacklist) ----------
def is_revoked(db: Session, jti: str) -> bool:
    return db.query(models.RevokedToken).filter(models.RevokedToken.jti == jti).first() is not None


def revoke(db: Session, jti: str, expires_at: datetime) -> None:
    if not jti or is_revoked(db, jti):
        return
    db.add(models.RevokedToken(jti=jti, expires_at=expires_at))
    db.commit()


# ---------- Characters ----------
class CharacterService:
    @staticmethod
    def list_for_user(db: Session, user: models.User) -> list[models.Player]:
        return (db.query(models.Player)
                .filter(models.Player.user_id == user.id)
                .order_by(models.Player.id)
                .all())

    @staticmethod
    def create(db: Session, user: models.User, name: str) -> models.Player:
        count = db.query(models.Player).filter(models.Player.user_id == user.id).count()
        if count >= config.MAX_CHARACTERS_PER_ACCOUNT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"You may own at most {config.MAX_CHARACTERS_PER_ACCOUNT} characters",
            )
        if db.query(models.Player).filter(models.Player.name == name).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="That character name is already taken")
        room = (db.query(models.Room).filter_by(id=config.STARTING_ROOM_ID).first()
                or db.query(models.Room).first())
        if not room:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="No rooms exist yet; seed the world first")
        player = models.Player(name=name, user_id=user.id, room_id=room.id)
        db.add(player)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="That character name is already taken")
        db.refresh(player)
        return player

    @staticmethod
    def owned_or_404(db: Session, user: models.User, player_id: int) -> models.Player:
        """Return the player IFF it belongs to this user, else 403/404."""
        player = db.query(models.Player).filter(models.Player.id == player_id).first()
        if not player:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
        if player.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="That character does not belong to you")
        return player

    @staticmethod
    def delete(db: Session, user: models.User, player_id: int) -> None:
        player = CharacterService.owned_or_404(db, user, player_id)
        db.delete(player)
        db.commit()
