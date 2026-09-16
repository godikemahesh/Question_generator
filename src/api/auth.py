"""
Admin Authentication Module (JWT + Bcrypt).
Pre-seeded for maheshgodike17@gmail.com / Maheshg17#
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
import jwt
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config.settings import JWT_SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Seeded admin password hash for Maheshg17#
SEEDED_PASSWORD_HASH = "$2b$12$5mwTsiG0F/GSA/B1OHjmLOTOKnXmobDv19GhIfDFsJcI73aMHj0t6"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        # Fallback check against ADMIN_PASSWORD from settings
        return plain_password == ADMIN_PASSWORD


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=24))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm="HS256")


def get_current_admin(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """
    Validate admin JWT token from Bearer header or cookie.
    """
    token = None

    # Check Authorization header first
    if auth and auth.credentials:
        token = auth.credentials

    # Check cookie fallback
    if not token and "access_token" in request.cookies:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
        )

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        email: str = payload.get("sub")
        if email != ADMIN_EMAIL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unauthorized admin account.",
            )
        return {"email": email, "role": payload.get("role", "admin")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )
