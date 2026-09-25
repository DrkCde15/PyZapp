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
