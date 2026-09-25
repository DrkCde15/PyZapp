"""Public health check (no auth): API + downstream Baileys reachability."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.errors import BaileysUnreachableError, ok_envelope
from app.schemas import HealthData

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    try:
        detail = await request.app.state.baileys.health()
        baileys = "ok"
    except BaileysUnreachableError:
        detail = None
        baileys = "unreachable"
    return ok_envelope(
        HealthData(service="api", baileys=baileys, baileys_detail=detail).model_dump()
    )
