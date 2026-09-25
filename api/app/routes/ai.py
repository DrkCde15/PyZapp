"""AI configuration routes + internal inbound-event intake."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.ai.providers import PROVIDERS
from app.ai.store import AIConfig
from app.auth import require_api_key, require_internal_key
from app.errors import ApiError, InstanceNotFoundError, ok_envelope
from app.logging_utils import logger
from app.schemas import AIConfigData, AIConfigRequest, InboundEvent

router = APIRouter()


def _to_data(cfg: AIConfig) -> dict:
    return AIConfigData(
        instance_id=cfg.instance_id,
        enabled=cfg.enabled,
        provider=cfg.provider,
        model=cfg.model,
        base_url=cfg.base_url,
        api_key_configured=bool(cfg.api_key),
        system_prompt=cfg.system_prompt,
        max_history=cfg.max_history,
        cooldown_s=cfg.cooldown_s,
    ).model_dump()


async def _require_instance(request: Request, instance_id: str) -> None:
    if await request.app.state.store.get(instance_id) is None:
        raise InstanceNotFoundError(instance_id)


@router.put("/instances/{instance_id}/ai", dependencies=[Depends(require_api_key)])
async def set_ai(instance_id: str, payload: AIConfigRequest, request: Request):
    await _require_instance(request, instance_id)
    provider = payload.provider.lower()
    if provider not in PROVIDERS:
        raise ApiError(
            "validation_error",
            f"Unknown provider '{payload.provider}'. Available: {sorted(PROVIDERS)}",
            422,
        )
    cfg = await request.app.state.ai_store.save_config(
        AIConfig(
            instance_id=instance_id,
            enabled=payload.enabled,
            provider=provider,
            model=payload.model or PROVIDERS[provider].default_model,
            base_url=payload.base_url,
            api_key=payload.api_key,
            system_prompt=payload.system_prompt,
            max_history=payload.max_history,
            cooldown_s=payload.cooldown_s,
        )
    )
    logger.info("event=ai_configured instance_id=%s provider=%s", instance_id, provider)
    return ok_envelope(_to_data(cfg))


@router.get("/instances/{instance_id}/ai", dependencies=[Depends(require_api_key)])
async def get_ai(instance_id: str, request: Request):
    await _require_instance(request, instance_id)
    cfg = await request.app.state.ai_store.get_config(instance_id)
    if cfg is None:
        return ok_envelope({"instance_id": instance_id, "enabled": False})
    return ok_envelope(_to_data(cfg))


@router.delete("/instances/{instance_id}/ai", dependencies=[Depends(require_api_key)])
async def delete_ai(instance_id: str, request: Request):
    await _require_instance(request, instance_id)
    await request.app.state.ai_store.delete_config(instance_id)
    logger.info("event=ai_disabled instance_id=%s", instance_id)
    return ok_envelope({"instance_id": instance_id, "enabled": False})


@router.post("/internal/events", dependencies=[Depends(require_internal_key)])
async def inbound_event(payload: InboundEvent, request: Request):
    """Baileys-service fans inbound messages here for AI auto-reply."""
    if payload.event != "message.received" or not payload.text.strip():
        return ok_envelope({"replied": False})
    reply_id = await request.app.state.responder.handle_inbound(
        payload.instance_id,
        payload.from_,
        payload.text,
        payload.message_id,
        has_media=payload.media is not None,
    )
    return ok_envelope({"replied": reply_id is not None, "message_id": reply_id})
