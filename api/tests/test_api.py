"""API tests: auth, validation, instance lifecycle (Baileys faked)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import BaileysError
from app.main import create_app


class FakeBaileys:
    """In-memory double of the internal contract."""

    def __init__(self) -> None:
        self.instances: dict[str, dict] = {}

    async def aclose(self) -> None:
        pass

    async def health(self) -> dict:
        return {"status": "ok", "service": "baileys"}

    async def create_instance(self, instance_id: str) -> dict:
        self.instances[instance_id] = {"instance_id": instance_id, "status": "qr_pending"}
        return {"instance_id": instance_id, "status": "qr_pending", "connected": False}

    async def list_instances(self) -> list[dict]:
        return list(self.instances.values())

    async def get_status(self, instance_id: str) -> dict:
        try:
            snap = self.instances[instance_id]
        except KeyError:
            raise BaileysError("instance_not_found", "not found", 404) from None
        return {**snap, "connected": snap["status"] == "connected", "phone": None, "updated_at": None}

    async def get_qr(self, instance_id: str) -> dict:
        snap = await self.get_status(instance_id)
        if snap["status"] != "qr_pending":
            raise BaileysError("qr_not_available", "no QR", 409)
        return {"qr": "FAKE-QR", "updated_at": None}

    async def connect(self, instance_id: str) -> dict:
        return await self.get_status(instance_id)

    async def send_message(self, instance_id: str, to: str, text: str) -> dict:
        snap = await self.get_status(instance_id)
        if snap["status"] != "connected":
            raise BaileysError("not_connected", "not connected", 409)
        return {"message_id": "MID123"}

    async def send_media(self, instance_id: str, payload: dict) -> dict:
        await self.get_status(instance_id)
        return {"message_id": "MID-MEDIA"}

    async def request_pairing_code(self, instance_id: str, phone: str) -> dict:
        await self.get_status(instance_id)
        return {"pairing_code": "ABCD-1234"}

    async def set_webhook(self, instance_id: str, url: str, secret: str | None) -> dict:
        await self.get_status(instance_id)
        self.instances[instance_id]["webhook"] = url
        return {"url": url, "configured": True}

    async def delete_instance(self, instance_id: str) -> dict:
        self.instances.pop(instance_id, None)
        return {"instance_id": instance_id}


@pytest.fixture()
def client():
    settings = Settings(api_key="test-key", environment="development")
    app = create_app(settings)
    with TestClient(app) as c:
        c.app.state.baileys = FakeBaileys()
        yield c


def auth_headers():
    return {"X-API-Key": "test-key"}


def test_health_is_public(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["service"] == "api"
    assert body["data"]["baileys"] == "ok"


def test_missing_api_key_is_401(client):
    assert client.get("/instances").status_code == 401
    assert client.get("/instances").json()["error"]["code"] == "unauthorized"


def test_wrong_api_key_is_401(client):
    assert client.get("/instances", headers={"X-API-Key": "nope"}).status_code == 401


def test_create_and_get_instance(client):
    created = client.post("/instances", headers=auth_headers())
    assert created.status_code == 201
    instance_id = created.json()["data"]["instance_id"]

    got = client.get(f"/instances/{instance_id}", headers=auth_headers())
    assert got.status_code == 200
    assert got.json()["data"]["instance_id"] == instance_id

    listed = client.get("/instances", headers=auth_headers()).json()["data"]
    assert [i["instance_id"] for i in listed] == [instance_id]


def test_get_unknown_instance_is_404(client):
    resp = client.get("/instances/does-not-exist", headers=auth_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "instance_not_found"


def test_qr_flow_and_conflict(client):
    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    qr = client.get(f"/instances/{instance_id}/qr", headers=auth_headers())
    assert qr.status_code == 200
    assert qr.json()["data"]["qr"] == "FAKE-QR"


def test_send_requires_valid_phone(client):
    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    bad = client.post(
        f"/instances/{instance_id}/messages",
        headers=auth_headers(),
        json={"phone": "not-a-phone", "text": "hi"},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"


def test_send_when_not_connected_is_409(client):
    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    resp = client.post(
        f"/instances/{instance_id}/messages",
        headers=auth_headers(),
        json={"phone": "+5511999999999", "text": "hi"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_connected"


def test_delete_instance(client):
    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    deleted = client.delete(f"/instances/{instance_id}", headers=auth_headers())
    assert deleted.status_code == 200
    assert client.get(f"/instances/{instance_id}", headers=auth_headers()).status_code == 404


def test_pairing_code(client):
    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    resp = client.post(
        f"/instances/{instance_id}/pairing-code",
        headers=auth_headers(),
        json={"phone": "+5511999999999"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["pairing_code"] == "ABCD-1234"


def test_pairing_code_rejects_bad_phone(client):
    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    resp = client.post(
        f"/instances/{instance_id}/pairing-code",
        headers=auth_headers(),
        json={"phone": "abc"},
    )
    assert resp.status_code == 422


def test_set_webhook(client):
    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    resp = client.put(
        f"/instances/{instance_id}/webhook",
        headers=auth_headers(),
        json={"url": "https://example.com/wa", "secret": "s3cret"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["configured"] is True


def test_set_webhook_rejects_non_http(client):
    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    resp = client.put(
        f"/instances/{instance_id}/webhook",
        headers=auth_headers(),
        json={"url": "ftp://example.com/wa"},
    )
    assert resp.status_code == 422


def test_send_media(client):
    import base64

    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    data = base64.b64encode(b"fakepng").decode()
    resp = client.post(
        f"/instances/{instance_id}/media",
        headers=auth_headers(),
        json={"phone": "+5511999999999", "media_type": "image", "data": data,
              "mimetype": "image/png", "caption": "olha"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["message_id"] == "MID-MEDIA"


def test_send_media_rejects_bad_payload(client):
    instance_id = client.post("/instances", headers=auth_headers()).json()["data"]["instance_id"]
    url = f"/instances/{instance_id}/media"
    bad_type = client.post(url, headers=auth_headers(),
                           json={"phone": "+5511999999999", "media_type": "video",
                                 "data": "aGk=", "mimetype": "video/mp4"})
    assert bad_type.status_code == 422
    bad_data = client.post(url, headers=auth_headers(),
                           json={"phone": "+5511999999999", "media_type": "image",
                                 "data": "%%%", "mimetype": "image/png"})
    assert bad_data.status_code == 422
