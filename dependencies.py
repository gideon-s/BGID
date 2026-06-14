"""FastAPI auth dependencies.

`get_current_user` guards REST routes (Bearer token). `get_current_admin`
additionally requires the admin role. `authenticate_ws` resolves a user from
the access token passed as a WebSocket query param (browsers can't set headers
on the WS handshake), since the gameplay channel must be authenticated too.
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.orm import Session

import models
from database import get_db
from security import decode_token

bearer_scheme = HTTPBearer()

_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


def _user_from_access_token(db: Session, token: str) -> Optional[models.User]:
    """Decode an access token and load the active user, or return None."""
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None
    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    user = _user_from_access_token(db, credentials.credentials)
    if user is None:
        raise _credentials_exception
    return user


def get_current_admin(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Admin privileges required")
    return current_user


def authenticate_ws(db: Session, token: Optional[str]) -> Optional[models.User]:
    """Resolve the user for a WebSocket connection from its `?token=` param.
    Returns None if the token is missing/invalid (caller closes the socket)."""
    if not token:
        return None
    return _user_from_access_token(db, token)
