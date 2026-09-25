"""SDK exceptions mapped from stable API error codes."""

from __future__ import annotations


class WhatsAppSDKError(Exception):
    """Base error. Always carries the stable `code` from the API."""

    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class AuthenticationError(WhatsAppSDKError):
    pass


class InstanceNotFoundError(WhatsAppSDKError):
    pass


class NotConnectedError(WhatsAppSDKError):
    pass


class QRNotAvailableError(WhatsAppSDKError):
    pass


class ValidationError(WhatsAppSDKError):
    pass


class ServiceError(WhatsAppSDKError):
    pass


_CODE_MAP = {
    "unauthorized": AuthenticationError,
    "instance_not_found": InstanceNotFoundError,
    "not_connected": NotConnectedError,
    "qr_not_available": QRNotAvailableError,
    "validation_error": ValidationError,
    "invalid_input": ValidationError,
}


def error_from_response(code: str, message: str, status_code: int | None) -> WhatsAppSDKError:
    cls = _CODE_MAP.get(code, ServiceError)
    return cls(code, message, status_code)
