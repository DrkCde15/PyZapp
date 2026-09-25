"""SDK tests: client behavior over a mocked HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest

from whatsapp_sdk import (
    AuthenticationError,
    InstanceNotFoundError,
    NotConnectedError,
    QRNotAvailableError,
    ValidationError,
    WhatsAppClient,
    WhatsAppSDKError,
)
from whatsapp_sdk.models import Instance


def make_client(handler) -> WhatsAppClient:
    return WhatsAppClient(
        base_url="http://test",
        api_key="key",
        transport=httpx.MockTransport(handler),
    )


def ok(data, status=200):
    return httpx.Response(status, json={"success": True, "data": data})


def fail(code, message, status=400):
    return httpx.Response(status, json={"success": False, "error": {"code": code, "message": message}})


def test_requires_api_key():
    with pytest.raises(ValueError):
        WhatsAppClient(base_url="http://test", api_key="")


def test_create_instance():
    def handler(request: httpx.Request):
        assert request.headers["X-API-Key"] == "key"
        assert request.method == "POST" and request.url.path == "/instances"
        return ok({"instance_id": "abc", "status": "qr_pending", "connected": False, "created_at": "t"})

    inst = make_client(handler).create_instance()
    assert isinstance(inst, Instance)
    assert inst.instance_id == "abc"
    assert inst.connected is False


def test_send_message():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert body == {"phone": "+5511999999999", "text": "Olá!"}
        return ok({"message_id": "MID1"}, status=201)

    sent = make_client(handler).send_message("abc", "+5511999999999", "Olá!")
    assert sent.message_id == "MID1"


def test_get_qr():
    def handler(_request: httpx.Request):
        return ok({"qr": "QRDATA", "updated_at": None})

    qr = make_client(handler).get_qr("abc")
    assert qr.qr == "QRDATA"


def test_error_mapping():
    cases = [
        ("unauthorized", AuthenticationError, 401),
        ("instance_not_found", InstanceNotFoundError, 404),
        ("not_connected", NotConnectedError, 409),
        ("qr_not_available", QRNotAvailableError, 409),
        ("validation_error", ValidationError, 422),
        ("baileys_unreachable", WhatsAppSDKError, 502),
    ]
    for code, exc_type, status in cases:
        def handler(_request: httpx.Request, code=code, status=status):
            return fail(code, "boom", status)

        with pytest.raises(exc_type) as exc_info:
            make_client(handler).get_instance("abc")
        assert exc_info.value.code == code


def test_connection_failure_maps_to_sdk_error():
    def handler(_request: httpx.Request):
        raise httpx.ConnectError("refused")

    with pytest.raises(WhatsAppSDKError) as exc_info:
        make_client(handler).list_instances()
    assert exc_info.value.code == "connection_failed"


def test_context_manager_closes():
    def handler(_request: httpx.Request):
        return ok([])

    with make_client(handler) as client:
        assert client.list_instances() == []


def test_request_pairing_code():
    def handler(request: httpx.Request):
        assert request.url.path.endswith("/pairing-code")
        return ok({"pairing_code": "ABCD-1234"})

    assert make_client(handler).request_pairing_code("abc", "+5511999999999") == "ABCD-1234"


def test_set_webhook():
    seen = {}

    def handler(request: httpx.Request):
        assert request.method == "PUT" and request.url.path.endswith("/webhook")
        seen.update(json.loads(request.content))
        return ok({"instance_id": "abc", "configured": True})

    make_client(handler).set_webhook("abc", "https://example.com/wa", secret="s3cret")
    assert seen == {"url": "https://example.com/wa", "secret": "s3cret"}


def test_ai_crud():
    def handler(request: httpx.Request):
        if request.method == "PUT":
            return ok({
                "instance_id": "abc", "enabled": True, "provider": "groq",
                "model": "llama-3.3-70b-versatile", "base_url": None,
                "api_key_configured": False, "system_prompt": "Seja breve.",
                "max_history": 20, "cooldown_s": 0,
            })
        if request.method == "GET":
            return ok({"instance_id": "abc", "enabled": False})
        assert request.method == "DELETE"
        return ok({"instance_id": "abc", "enabled": False})

    c = make_client(handler)
    cfg = c.set_ai("abc", provider="groq", system_prompt="Seja breve.")
    assert cfg.provider == "groq" and cfg.enabled is True
    assert c.get_ai("abc").enabled is False
    c.disable_ai("abc")


def test_print_qr(capsys):
    def handler(_request: httpx.Request):
        return ok({"qr": "QRDATA", "updated_at": None})

    raw = make_client(handler).print_qr("abc")
    assert raw == "QRDATA"
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) > 3  # actual ASCII matrix printed


def test_send_media(tmp_path):
    seen = {}

    def handler(request: httpx.Request):
        assert request.method == "POST" and request.url.path.endswith("/media")
        seen.update(json.loads(request.content))
        return ok({"message_id": "MID-M"}, status=201)

    c = make_client(handler)
    img = tmp_path / "foto.png"
    img.write_bytes(b"\x89PNGdata")

    sent = c.send_image("abc", "+5511999999999", str(img), caption="olha")
    assert sent.message_id == "MID-M"
    assert seen["media_type"] == "image"
    assert seen["mimetype"] == "image/png"  # guessed from extension
    assert seen["caption"] == "olha"
    assert seen["filename"] == "foto.png"
    import base64

    assert base64.b64decode(seen["data"]) == b"\x89PNGdata"

    c.send_audio("abc", "+5511999999999", b"oggbytes", voice_note=True)
    assert seen["media_type"] == "audio" and seen["voice_note"] is True

    c.send_document("abc", "+5511999999999", b"%PDF", filename="doc.pdf",
                    mimetype="application/pdf")
    assert seen["media_type"] == "document" and seen["filename"] == "doc.pdf"
