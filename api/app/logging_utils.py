"""Structured logging without secrets. Mirrors the Node service fields."""

from __future__ import annotations

import logging
import sys

MASKED = "***"


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) <= 4:
        return MASKED
    return f"{digits[:2]}****{digits[-2:]}"


def setup_logging(level: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s service=api level=%(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root = logging.getLogger("pyzapp")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    return root


logger = logging.getLogger("pyzapp")
