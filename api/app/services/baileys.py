"""HTTP client for the internal baileys-service.

Single responsibility: translate between our domain errors and the
internal JSON contract. No business logic lives here.
"""

from __future__ import annotations

import httpx

from app.errors import BaileysError, BaileysUnreachableError


class BaileysClient:
    def __init__(self, base_url: str, internal_api_key: str, timeout_s: float = 15.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            headers={"X-Internal-Key": internal_api_key} if internal_api_key else {},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise BaileysUnreachableError() from exc
        try:
            body = resp.json()
        except ValueError as exc:
            raise BaileysError("baileys_error", f"Invalid response from WhatsApp service: {resp.status_code}", 502) from exc
        if resp.status_code >= 400 or not body.get("success", False):
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise BaileysError(
                err.get("code", "baileys_error"),
                err.get("message", f"WhatsApp service error: {resp.status_code}"),
                resp.status_code if resp.status_code < 500 else 502,
            )
        return body.get("data", {})

    async def health(self) -> dict:
        try:
            resp = await self._client.get("/health")
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BaileysUnreachableError() from exc

    async def create_instance(self, instance_id: str) -> dict:
        return await self._request("POST", "/internal/instances", json={"instance_id": instance_id})

    async def list_instances(self) -> list[dict]:
        data = await self._request("GET", "/internal/instances")
        return data if isinstance(data, list) else []

    async def get_status(self, instance_id: str) -> dict:
        return await self._request("GET", f"/internal/instances/{instance_id}/status")

    async def get_qr(self, instance_id: str) -> dict:
        return await self._request("GET", f"/internal/instances/{instance_id}/qr")

    async def connect(self, instance_id: str) -> dict:
        return await self._request("POST", f"/internal/instances/{instance_id}/connect")

    async def send_message(self, instance_id: str, to: str, text: str) -> dict:
        return await self._request(
            "POST", f"/internal/instances/{instance_id}/messages", json={"to": to, "text": text}
        )

    async def send_media(self, instance_id: str, payload: dict) -> dict:
        return await self._request(
            "POST", f"/internal/instances/{instance_id}/media", json=payload
        )

    async def request_pairing_code(self, instance_id: str, phone: str) -> dict:
        return await self._request(
            "POST", f"/internal/instances/{instance_id}/pairing-code", json={"phone": phone}
        )

    async def set_webhook(self, instance_id: str, url: str, secret: str | None) -> dict:
        return await self._request(
            "PUT", f"/internal/instances/{instance_id}/webhook", json={"url": url, "secret": secret}
        )

    async def delete_instance(self, instance_id: str) -> dict:
        return await self._request("DELETE", f"/internal/instances/{instance_id}")
