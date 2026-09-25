"""Request/response schemas with validation at the boundary."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.errors import InstanceStatus

PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def normalize_phone(value: str) -> str:
    # Accept common user formatting: spaces, dashes, parentheses.
    cleaned = re.sub(r"[\s\-().]", "", value)
    if not PHONE_RE.match(cleaned):
        raise ValueError("phone must be E.164 digits with country code, e.g. +5511999999999")
    return cleaned


class SendMessageRequest(BaseModel):
    phone: str = Field(..., description="Destination in E.164, e.g. +5511999999999")
    text: str = Field(..., min_length=1, max_length=4096)

    _normalize_phone = field_validator("phone", mode="before")(normalize_phone)


class SendMediaRequest(BaseModel):
    phone: str = Field(..., description="Destination in E.164, e.g. +5511999999999")
    media_type: str = Field(..., description="image | audio | document")
    data: str = Field(..., description="File bytes encoded in base64 (max ~16MB)")
    mimetype: str | None = Field(default=None, description="e.g. image/jpeg, audio/ogg; codecs=opus")
    caption: str | None = Field(default=None, max_length=1024)
    filename: str | None = Field(default=None, description="Required for document")
    voice_note: bool = Field(default=False, description="Audio sent as voice message")

    _normalize_phone = field_validator("phone", mode="before")(normalize_phone)

    @field_validator("media_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in ("image", "audio", "document"):
            raise ValueError("media_type must be image, audio or document")
        return value

    @field_validator("data")
    @classmethod
    def _base64_sized(cls, value: str) -> str:
        import base64

        if not value.strip():
            raise ValueError("data must be a non-empty base64 string")
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception:
            raise ValueError("data is not valid base64") from None
        if len(raw) == 0 or len(raw) > 12 * 1024 * 1024:
            raise ValueError("decoded media must be 1 byte–12MB")
        return value


class PairingCodeRequest(BaseModel):
    phone: str = Field(..., description="Phone that will type the code, E.164")

    _normalize_phone = field_validator("phone", mode="before")(normalize_phone)


class PairingCodeData(BaseModel):
    pairing_code: str


class WebhookRequest(BaseModel):
    url: str = Field(..., description="https URL receiving inbound message events")
    secret: str | None = Field(default=None, max_length=256)

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("webhook url must use http(s)")
        return value


class InstanceSummary(BaseModel):
    instance_id: str
    status: InstanceStatus
    connected: bool
    created_at: str


class InstanceDetail(InstanceSummary):
    phone: str | None = None
    updated_at: str | None = None


class QrData(BaseModel):
    qr: str
    updated_at: str | None = None


class StatusData(BaseModel):
    instance_id: str
    status: InstanceStatus
    connected: bool
    phone: str | None = None
    updated_at: str | None = None


class MessageResult(BaseModel):
    message_id: str


class HealthData(BaseModel):
    status: str = "ok"
    service: str = "api"
    baileys: str = "ok"
    baileys_detail: Any | None = None


class AIConfigRequest(BaseModel):
    enabled: bool = True
    provider: str = Field(..., description="openai | groq | openrouter | ollama | gemini | anthropic")
    model: str | None = None
    base_url: str | None = Field(default=None, description="Override (self-hosted gateway)")
    api_key: str | None = Field(default=None, description="Per-instance key; falls back to env")
    system_prompt: str | None = Field(default=None, max_length=4000)
    max_history: int = Field(default=20, ge=1, le=100)
    cooldown_s: int = Field(default=0, ge=0, le=3600)


class AIConfigData(BaseModel):
    instance_id: str
    enabled: bool
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_configured: bool = False
    system_prompt: str | None = None
    max_history: int = 20
    cooldown_s: int = 0


class InboundEvent(BaseModel):
    event: str = "message.received"
    instance_id: str
    message_id: str | None = None
    from_: str = Field(..., alias="from")
    text: str = ""
    timestamp: int | float | None = None
    media: dict | None = Field(
        default=None,
        description="{type, mimetype, filename, caption, data(base64)} when present",
    )
