"""WhatsAppClient: thin, typed HTTP client for the PyZapp API.

No WhatsApp/Baileys logic lives here — only request shaping,
error mapping and typed responses.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx
import qrcode

from whatsapp_sdk.exceptions import WhatsAppSDKError, error_from_response
from whatsapp_sdk.models import ConnectionStatus, Instance, InstanceDetail, QRCode, SentMessage


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
