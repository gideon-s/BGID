"""Auth + character-management routes.

  POST /auth/register   -> create account, returns {user, tokens}
  POST /auth/login      -> returns {user, tokens}
  POST /auth/refresh    -> rotate refresh token, returns fresh tokens
  POST /auth/logout     -> revoke a refresh token
  GET  /auth/me         -> current user + their characters

  GET    /characters    -> my characters
  POST   /characters    -> create a character (spawns in the starting room)
  DELETE /characters/{id}
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

import models
import auth_schemas as aschemas
import auth_service
from database import get_db
from dependencies import get_current_user
from security import decode_token, create_access_token, create_refresh_token

router = APIRouter()
auth_router = APIRouter(prefix="/auth", tags=["Auth"])
char_router = APIRouter(prefix="/characters", tags=["Characters"])


@auth_router.post("/register", response_model=aschemas.AuthResponse,
                  status_code=status.HTTP_201_CREATED)
def register(data: aschemas.RegisterRequest, db: Session = Depends(get_db)):
    user, tokens = auth_service.register_user(db, data)
    return aschemas.AuthResponse(user=aschemas.UserResponse.model_validate(user), tokens=tokens)


@auth_router.post("/login", response_model=aschemas.AuthResponse)
def login(data: aschemas.LoginRequest, db: Session = Depends(get_db)):
    user, tokens = auth_service.login_user(db, data)
    return aschemas.AuthResponse(user=aschemas.UserResponse.model_validate(user), tokens=tokens)


@auth_router.post("/refresh", response_model=aschemas.TokenResponse)
def refresh(data: aschemas.RefreshRequest, db: Session = Depends(get_db)):
    err = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired refresh token")
    try:
        payload = decode_token(data.refresh_token)
        if payload.get("type") != "refresh":
            raise err
        user_id = payload.get("sub")
        jti = payload.get("jti", "")
        exp = payload.get("exp", 0)
        if not user_id:
            raise err
    except JWTError:
        raise err

    if jti and auth_service.is_revoked(db, jti):
        raise err
    # Single-use rotation: revoke the presented refresh token before minting a
    # replacement, so an old refresh token can't spawn parallel sessions.
    if jti:
        auth_service.revoke(db, jti, datetime.fromtimestamp(exp, tz=timezone.utc))

    return aschemas.TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(str(user_id))[0],
    )


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: aschemas.RefreshRequest,
           current_user: models.User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    """Revoke the supplied refresh token. Access tokens remain valid until
    their short TTL expires (no per-request DB hit on the hot path)."""
    try:
        payload = decode_token(data.refresh_token)
        jti = payload.get("jti", "")
        exp = payload.get("exp", 0)
        if jti:
            auth_service.revoke(db, jti, datetime.fromtimestamp(exp, tz=timezone.utc))
    except JWTError:
        pass  # already-invalid token: nothing to revoke


@auth_router.get("/me", response_model=aschemas.MeResponse)
def me(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    chars = auth_service.CharacterService.list_for_user(db, current_user)
    return aschemas.MeResponse(
        user=aschemas.UserResponse.model_validate(current_user),
        characters=[aschemas.CharacterOut.model_validate(c) for c in chars],
    )


@char_router.get("", response_model=list[aschemas.CharacterOut])
def list_characters(current_user: models.User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return auth_service.CharacterService.list_for_user(db, current_user)


@char_router.post("", response_model=aschemas.CharacterOut,
                  status_code=status.HTTP_201_CREATED)
def create_character(data: aschemas.CharacterCreate,
                     current_user: models.User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    return auth_service.CharacterService.create(db, current_user, data.name)


@char_router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(player_id: int,
                     current_user: models.User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    auth_service.CharacterService.delete(db, current_user, player_id)


router.include_router(auth_router)
router.include_router(char_router)
