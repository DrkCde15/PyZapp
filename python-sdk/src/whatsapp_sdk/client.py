"""WhatsAppClient: thin, typed HTTP client for the PyZapp API.

No WhatsApp/Baileys logic lives here — only request shaping,
error mapping and typed responses.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
import qrcode

from whatsapp_sdk.exceptions import WhatsAppSDKError, error_from_response
from whatsapp_sdk.models import (
    AIConfig,
    ConnectionStatus,
    Instance,
    InstanceDetail,
    QRCode,
    SentMessage,
)


class WhatsAppClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str = "",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout,
            transport=transport,
        )

    # -- context manager -------------------------------------------------
    def __enter__(self) -> WhatsAppClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- core ------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.ConnectError as exc:
            raise WhatsAppSDKError("connection_failed", f"Cannot reach API: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise WhatsAppSDKError("timeout", f"API request timed out: {exc}") from exc

        try:
            body = resp.json()
        except ValueError as exc:
            raise WhatsAppSDKError("invalid_response", f"API returned non-JSON: {resp.status_code}") from exc

        if resp.status_code >= 400 or not body.get("success", False):
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise error_from_response(
                err.get("code", "unknown_error"),
                err.get("message", f"API error: {resp.status_code}"),
                resp.status_code,
            )
        return body.get("data")

    # -- instances --------------------------------------------------------
    def create_instance(self) -> Instance:
        """Create a WhatsApp instance and start connecting (QR follows)."""
        return Instance.model_validate(self._request("POST", "/instances"))

    def list_instances(self) -> list[Instance]:
        return [Instance.model_validate(i) for i in self._request("GET", "/instances")]

    def get_instance(self, instance_id: str) -> InstanceDetail:
        return InstanceDetail.model_validate(self._request("GET", f"/instances/{instance_id}"))

    def delete_instance(self, instance_id: str) -> None:
        self._request("DELETE", f"/instances/{instance_id}")

    # -- connection -------------------------------------------------------
    def connect(self, instance_id: str) -> ConnectionStatus:
        """Trigger a (re)connect. Used after disconnect/logged_out."""
        return ConnectionStatus.model_validate(
            self._request("POST", f"/instances/{instance_id}/connect")
        )

    def get_qr(self, instance_id: str) -> QRCode:
        """Raw QR string — render it (e.g. `qrcode` lib) and scan with WhatsApp."""
        return QRCode.model_validate(self._request("GET", f"/instances/{instance_id}/qr"))

    def print_qr(self, instance_id: str) -> str:
        """Fetch the QR and print it as ASCII in the terminal. Returns the raw string."""
        qr = self.get_qr(instance_id).qr
        code = qrcode.QRCode()
        code.add_data(qr)
        code.print_ascii()
        return qr

    def get_status(self, instance_id: str) -> ConnectionStatus:
        return ConnectionStatus.model_validate(
            self._request("GET", f"/instances/{instance_id}/status")
        )

    # -- messaging ---------------------------------------------------------
    def send_message(self, instance_id: str, phone: str, text: str) -> SentMessage:
        """Send a text message. `phone` in E.164, e.g. +5511999999999."""
        return SentMessage.model_validate(
            self._request(
                "POST",
                f"/instances/{instance_id}/messages",
                json={"phone": phone, "text": text},
            )
        )

    def send_image(
        self,
        instance_id: str,
        phone: str,
        image: bytes | str,
        caption: str = "",
        mimetype: str | None = None,
    ) -> SentMessage:
        """Send an image (JPEG/PNG/WebP). `image` = bytes or file path."""
        return self._send_media(instance_id, phone, "image", image, caption=caption, mimetype=mimetype)

    def send_audio(
        self,
        instance_id: str,
        phone: str,
        audio: bytes | str,
        mimetype: str | None = None,
        voice_note: bool = False,
    ) -> SentMessage:
        """Send audio. `voice_note=True` renders it as a voice message."""
        return self._send_media(
            instance_id, phone, "audio", audio, mimetype=mimetype, voice_note=voice_note
        )

    def send_document(
        self,
        instance_id: str,
        phone: str,
        document: bytes | str,
        filename: str | None = None,
        mimetype: str | None = None,
        caption: str = "",
    ) -> SentMessage:
        """Send a document. `filename` defaults to the file's basename when a path is given."""
        return self._send_media(
            instance_id, phone, "document", document,
            filename=filename, mimetype=mimetype, caption=caption,
        )

    def _send_media(
        self,
        instance_id: str,
        phone: str,
        media_type: str,
        data: bytes | str,
        caption: str = "",
        mimetype: str | None = None,
        filename: str | None = None,
        voice_note: bool = False,
    ) -> SentMessage:
        raw, resolved_name = _read_media(data)
        return SentMessage.model_validate(
            self._request(
                "POST",
                f"/instances/{instance_id}/media",
                json={
                    "phone": phone,
                    "media_type": media_type,
                    "data": base64.b64encode(raw).decode(),
                    "mimetype": mimetype or _guess_mimetype(resolved_name, media_type),
                    "caption": caption,
                    "filename": filename or resolved_name,
                    "voice_note": voice_note,
                },
            )
        )

    def request_pairing_code(self, instance_id: str, phone: str) -> str:
        """Issue an 8-digit code to type on the phone instead of scanning a QR."""
        data = self._request(
            "POST",
            f"/instances/{instance_id}/pairing-code",
            json={"phone": phone},
        )
        return data["pairing_code"]

    def set_webhook(self, instance_id: str, url: str, secret: str | None = None) -> None:
        """Configure where inbound message events are delivered for this instance."""
        self._request(
            "PUT",
            f"/instances/{instance_id}/webhook",
            json={"url": url, "secret": secret},
        )

    # -- AI auto-reply ------------------------------------------------------
    def set_ai(
        self,
        instance_id: str,
        provider: str,
        model: str | None = None,
        system_prompt: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        max_history: int = 20,
        cooldown_s: int = 0,
        enabled: bool = True,
    ) -> AIConfig:
        """Enable AI auto-reply. Provider: openai | groq | openrouter | ollama | gemini | anthropic."""
        return AIConfig.model_validate(
            self._request(
                "PUT",
                f"/instances/{instance_id}/ai",
                json={
                    "enabled": enabled,
                    "provider": provider,
                    "model": model,
                    "base_url": base_url,
                    "api_key": api_key,
                    "system_prompt": system_prompt,
                    "max_history": max_history,
                    "cooldown_s": cooldown_s,
                },
            )
        )

    def get_ai(self, instance_id: str) -> AIConfig:
        return AIConfig.model_validate(self._request("GET", f"/instances/{instance_id}/ai"))

    def disable_ai(self, instance_id: str) -> None:
        self._request("DELETE", f"/instances/{instance_id}/ai")


def _read_media(data: bytes | str) -> tuple[bytes, str | None]:
    """Accept raw bytes or a file path. Returns (bytes, filename-or-None)."""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data), None
    path = Path(data)
    return path.read_bytes(), path.name


def _guess_mimetype(filename: str | None, media_type: str) -> str | None:
    if filename:
        guessed, _ = mimetypes.guess_type(filename)
        if guessed:
            return guessed
    return {"image": "image/jpeg", "audio": "audio/ogg; codecs=opus"}.get(media_type)
