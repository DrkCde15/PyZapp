"""Public surface of the SDK."""

from whatsapp_sdk.client import WhatsAppClient
from whatsapp_sdk.exceptions import (
    AuthenticationError,
    InstanceNotFoundError,
    NotConnectedError,
    QRNotAvailableError,
    ServiceError,
    ValidationError,
    WhatsAppSDKError,
)
from whatsapp_sdk.models import ConnectionStatus, Instance, InstanceDetail, QRCode, SentMessage

__all__ = [
    "WhatsAppClient",
    "WhatsAppSDKError",
    "AuthenticationError",
    "InstanceNotFoundError",
    "NotConnectedError",
    "QRNotAvailableError",
    "ValidationError",
    "ServiceError",
    "Instance",
    "InstanceDetail",
    "ConnectionStatus",
    "QRCode",
    "SentMessage",
]
