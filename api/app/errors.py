"""Public error envelope + domain exceptions."""

from __future__ import annotations

from typing import Any, Literal


def error_envelope(code: str, message: str) -> dict[str, Any]:
    return {"success": False, "error": {"code": code, "message": message}}


def ok_envelope(data: Any = None) -> dict[str, Any]:
    return {"success": True, "data": data}


class ApiError(Exception):
    """Raised inside routes/services; mapped to the public envelope."""

    def __init__(self, code: str, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class InstanceNotFoundError(ApiError):
    def __init__(self, instance_id: str) -> None:
        super().__init__("instance_not_found", f"Instance '{instance_id}' not found", 404)


class BaileysUnreachableError(ApiError):
    def __init__(self) -> None:
        super().__init__("baileys_unreachable", "WhatsApp service is unreachable", 502)


class BaileysError(ApiError):
    """Error propagated from baileys-service, keeping its stable code."""

    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(code, message, status_code)


InstanceStatus = Literal[
    "created", "connecting", "qr_pending", "connected", "disconnected", "logged_out"
]
