"""Typed models returned by WhatsAppClient. Pure data, no HTTP."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

InstanceStatus = Literal[
    "created", "connecting", "qr_pending", "connected", "disconnected", "logged_out"
]


class Instance(BaseModel):
    instance_id: str
    status: InstanceStatus
    connected: bool
    created_at: str


class InstanceDetail(Instance):
    phone: str | None = None
    updated_at: str | None = None


class ConnectionStatus(BaseModel):
    instance_id: str
    status: InstanceStatus
    connected: bool
    phone: str | None = None
    updated_at: str | None = None


class QRCode(BaseModel):
    qr: str
    updated_at: str | None = None


class SentMessage(BaseModel):
    message_id: str
