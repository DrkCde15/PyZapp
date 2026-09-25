"""API-key auth for public endpoints."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    settings = request.app.state.settings
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="unauthorized")


async def require_internal_key(
    request: Request,
    x_internal_key: str | None = Header(default=None),
) -> None:
    """Baileys-service calling back into /internal/* (same shared secret)."""
    settings = request.app.state.settings
    if not settings.internal_api_key:
        if settings.environment == "production":
            raise HTTPException(status_code=500, detail="misconfigured")
        return
    if not x_internal_key or x_internal_key != settings.internal_api_key:
        raise HTTPException(status_code=401, detail="unauthorized")
