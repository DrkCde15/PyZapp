"""Instance management routes. Thin: validate, delegate, respond."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from app.auth import require_api_key
from app.errors import InstanceNotFoundError, ok_envelope
from app.logging_utils import logger, mask_phone
from app.schemas import (
    InstanceDetail,
    InstanceSummary,
    MessageResult,
    PairingCodeData,
    PairingCodeRequest,
    QrData,
    SendMessageRequest,
    StatusData,
    WebhookRequest,
)
from app.services.baileys import BaileysClient

router = APIRouter(dependencies=[Depends(require_api_key)])


def _baileys(request: Request) -> BaileysClient:
    return request.app.state.baileys


@router.post("/instances", status_code=201)
async def create_instance(request: Request):
    instance_id = uuid.uuid4().hex
    snapshot = await _baileys(request).create_instance(instance_id)
    meta = await request.app.state.store.add(instance_id)
    logger.info("event=instance_created instance_id=%s status=%s", instance_id, snapshot.get("status"))
    return ok_envelope(
        InstanceSummary(
            instance_id=instance_id,
            status=snapshot.get("status", "connecting"),
            connected=snapshot.get("connected", False),
            created_at=meta["created_at"],
        ).model_dump()
    )


@router.get("/instances")
async def list_instances(request: Request):
    snapshots = await _baileys(request).list_instances()
    by_id = {s["instance_id"]: s for s in snapshots if "instance_id" in s}
    await request.app.state.store.sync_ids(list(by_id))
    items = []
    for meta in await request.app.state.store.list():
        snap = by_id.get(meta["instance_id"], {})
        items.append(
            InstanceSummary(
                instance_id=meta["instance_id"],
                status=snap.get("status", "disconnected"),
                connected=snap.get("connected", False),
                created_at=meta["created_at"],
            ).model_dump()
        )
    return ok_envelope(items)


@router.get("/instances/{instance_id}")
async def get_instance(instance_id: str, request: Request):
    meta = await request.app.state.store.get(instance_id)
    if meta is None:
        raise InstanceNotFoundError(instance_id)
    snap = await _baileys(request).get_status(instance_id)
    return ok_envelope(
        InstanceDetail(
            instance_id=instance_id,
            status=snap.get("status", "disconnected"),
            connected=snap.get("connected", False),
            created_at=meta["created_at"],
            phone=snap.get("phone"),
            updated_at=snap.get("updated_at"),
        ).model_dump()
    )


@router.delete("/instances/{instance_id}")
async def delete_instance(instance_id: str, request: Request):
    meta = await request.app.state.store.get(instance_id)
    if meta is None:
        raise InstanceNotFoundError(instance_id)
    await _baileys(request).delete_instance(instance_id)
    await request.app.state.store.remove(instance_id)
    logger.info("event=instance_deleted instance_id=%s", instance_id)
    return ok_envelope({"instance_id": instance_id})


@router.post("/instances/{instance_id}/connect", status_code=202)
async def connect_instance(instance_id: str, request: Request):
    if await request.app.state.store.get(instance_id) is None:
        raise InstanceNotFoundError(instance_id)
    snap = await _baileys(request).connect(instance_id)
    return ok_envelope(
        StatusData(
            instance_id=instance_id,
            status=snap.get("status", "connecting"),
            connected=snap.get("connected", False),
            phone=snap.get("phone"),
            updated_at=snap.get("updated_at"),
        ).model_dump()
    )


@router.get("/instances/{instance_id}/qr")
async def get_qr(instance_id: str, request: Request):
    if await request.app.state.store.get(instance_id) is None:
        raise InstanceNotFoundError(instance_id)
    data = await _baileys(request).get_qr(instance_id)
    return ok_envelope(QrData(qr=data["qr"], updated_at=data.get("updated_at")).model_dump())


@router.get("/instances/{instance_id}/status")
async def get_status(instance_id: str, request: Request):
    if await request.app.state.store.get(instance_id) is None:
        raise InstanceNotFoundError(instance_id)
    snap = await _baileys(request).get_status(instance_id)
    return ok_envelope(
        StatusData(
            instance_id=instance_id,
            status=snap.get("status", "disconnected"),
            connected=snap.get("connected", False),
            phone=snap.get("phone"),
            updated_at=snap.get("updated_at"),
        ).model_dump()
    )


@router.post("/instances/{instance_id}/messages", status_code=201)
async def send_message(instance_id: str, payload: SendMessageRequest, request: Request):
    if await request.app.state.store.get(instance_id) is None:
        raise InstanceNotFoundError(instance_id)
    data = await _baileys(request).send_message(instance_id, payload.phone, payload.text)
    logger.info(
        "event=message_sent instance_id=%s to=%s message_id=%s",
        instance_id,
        mask_phone(payload.phone),
        data.get("message_id"),
    )
    return ok_envelope(MessageResult(message_id=data.get("message_id", "")).model_dump())


@router.post("/instances/{instance_id}/pairing-code")
async def request_pairing_code(instance_id: str, payload: PairingCodeRequest, request: Request):
    if await request.app.state.store.get(instance_id) is None:
        raise InstanceNotFoundError(instance_id)
    data = await _baileys(request).request_pairing_code(instance_id, payload.phone)
    logger.info(
        "event=pairing_code_issued instance_id=%s to=%s",
        instance_id,
        mask_phone(payload.phone),
    )
    return ok_envelope(PairingCodeData(pairing_code=data.get("pairing_code", "")).model_dump())


@router.put("/instances/{instance_id}/webhook")
async def set_webhook(instance_id: str, payload: WebhookRequest, request: Request):
    if await request.app.state.store.get(instance_id) is None:
        raise InstanceNotFoundError(instance_id)
    await _baileys(request).set_webhook(instance_id, payload.url, payload.secret)
    logger.info("event=webhook_configured instance_id=%s", instance_id)
    return ok_envelope({"instance_id": instance_id, "url": payload.url, "configured": True})
