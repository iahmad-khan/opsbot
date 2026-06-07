from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from opsbot.config.settings import get_settings

router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


@router.post("/auth/token", response_model=TokenResponse)
async def dashboard_login(req: LoginRequest) -> TokenResponse:
    """Exchange the dashboard password for a short-lived JWT.

    Set DASHBOARD_SECRET in the environment to enable auth. When the variable
    is not set this endpoint returns 403 so the frontend knows auth is disabled.
    """
    s = get_settings()
    if not s.dashboard_secret:
        raise HTTPException(status_code=403, detail="Dashboard authentication is not configured.")
    if not secrets.compare_digest(req.password.encode(), s.dashboard_secret.encode()):
        raise HTTPException(status_code=401, detail="Invalid password.")

    expire = timedelta(minutes=s.jwt_expire_minutes)
    payload = {
        "sub": "dashboard",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + expire,
    }
    token = jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)
    return TokenResponse(access_token=token, expires_in=int(expire.total_seconds()))
