"""AI tests: providers registry, responder logic, routes (all faked)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai.providers import PROVIDERS, build_provider
from app.ai.responder import AIResponder
from app.ai.store import AIConfig, AIStore
from app.config import Settings
from app.main import create_app


class FakeProvider:
    def __init__(self, reply="fake reply"):
        self.reply = reply
        self.calls: list = []

    async def generate(self, system, history, user_text):
        self.calls.append((system, list(history), user_text))
        return self.reply.strip()  # real providers strip output


def make_responder(reply="fake reply", **cfg_kwargs):
    sent = []
    store = AIStore()
    provider = FakeProvider(reply)

    async def fake_send(instance_id, to, text):
        sent.append((instance_id, to, text))
        return "MID-AI"

    responder = AIResponder(store, {}, fake_send)
    responder._provider_for = lambda cfg: provider  # noqa: SLF001
    defaults = {"instance_id": "i1", "enabled": True, "provider": "openai"}
    responder._cfg = AIConfig(**{**defaults, **cfg_kwargs})
    return responder, store, sent, provider


async def _enable(responder, store):
    await store.save_config(responder._cfg)


def test_provider_registry_covers_all_backends():
    assert set(PROVIDERS) == {"openai", "groq", "openrouter", "ollama", "gemini", "anthropic"}
    assert PROVIDERS["ollama"].needs_key is False
    with pytest.raises(ValueError):
        build_provider("nope", "key")
    with pytest.raises(ValueError):
        build_provider("openai", None)


@pytest.mark.asyncio()
async def test_reply_flow_stores_history():
    responder, store, sent, provider = make_responder()
    await _enable(responder, store)
    mid = await responder.handle_inbound("i1", "5511", "hello")
    assert mid == "MID-AI"
    assert sent == [("i1", "5511", "fake reply")]
    hist = await store.history("i1", "5511")
    assert [(m.role, m.content) for m in hist] == [("user", "hello"), ("assistant", "fake reply")]
    assert provider.calls[0][2] == "hello"


@pytest.mark.asyncio()
async def test_second_turn_sees_history():
    responder, store, sent, provider = make_responder()
    await _enable(responder, store)
    await responder.handle_inbound("i1", "5511", "first")
    await responder.handle_inbound("i1", "5511", "second")
    assert len(provider.calls[1][1]) == 2  # user+assistant from turn 1


@pytest.mark.asyncio()
async def test_disabled_optout_empty_and_cooldown():
    responder, store, sent, _ = make_responder(enabled=False)
    await _enable(responder, store)
    assert await responder.handle_inbound("i1", "5511", "hi") is None

    responder2, store2, sent2, _ = make_responder()
    await store2.save_config(responder2._cfg)
    assert await responder2.handle_inbound("i1", "5511", "SAIR") is None
    assert sent2 == []

    responder3, store3, sent3, _ = make_responder(reply="  ")
    await store3.save_config(responder3._cfg)
    assert await responder3.handle_inbound("i1", "5511", "hi") is None
    assert sent3 == []

    responder4, store4, sent4, _ = make_responder(cooldown_s=3600)
    await store4.save_config(responder4._cfg)
    assert await responder4.handle_inbound("i1", "5511", "one") == "MID-AI"
    assert await responder4.handle_inbound("i1", "5511", "two") is None
    assert len(sent4) == 1


@pytest.mark.asyncio()
async def test_unknown_instance_is_ignored():
    responder, store, sent, _ = make_responder()
    assert await responder.handle_inbound("ghost", "5511", "hi") is None
    assert sent == []


# -- routes ---------------------------------------------------------------

TABLE = None


class FakeBaileys:
    """Minimal double: only what the AI route tests need."""

    def __init__(self) -> None:
        self.instances: dict[str, dict] = {}

    async def aclose(self) -> None:
        pass

    async def create_instance(self, instance_id: str) -> dict:
        self.instances[instance_id] = {"instance_id": instance_id, "status": "qr_pending"}
        return {"instance_id": instance_id, "status": "qr_pending", "connected": False}

    async def list_instances(self) -> list[dict]:
        return list(self.instances.values())


@pytest.fixture()
def client():
    settings = Settings(api_key="test-key", environment="development", internal_api_key="test-internal")
    app = create_app(settings)
    with TestClient(app) as c:
        c.app.state.baileys = FakeBaileys()
        c.app.state.ai_store = AIStore()

        async def fake_send(instance_id, to, text):
            return "MID-AI"

        c.app.state.responder = AIResponder(c.app.state.ai_store, {}, fake_send)
        c.app.state.responder._provider_for = lambda cfg: FakeProvider()  # noqa: SLF001
        yield c


def auth():
    return {"X-API-Key": "test-key"}


def internal():
    return {"X-Internal-Key": "test-internal"}


def _make_instance(client):
    return client.post("/instances", headers=auth()).json()["data"]["instance_id"]


def test_ai_crud(client):
    iid = _make_instance(client)
    assert client.get(f"/instances/{iid}/ai", headers=auth()).json()["data"] == {
        "instance_id": iid,
        "enabled": False,
    }
    put = client.put(
        f"/instances/{iid}/ai",
        headers=auth(),
        json={"provider": "groq", "system_prompt": "Seja breve.", "cooldown_s": 10},
    )
    assert put.status_code == 200
    data = put.json()["data"]
    assert data["provider"] == "groq" and data["cooldown_s"] == 10
    assert data["api_key_configured"] is False

    bad = client.put(f"/instances/{iid}/ai", headers=auth(), json={"provider": "nope"})
    assert bad.status_code == 422

    assert client.delete(f"/instances/{iid}/ai", headers=auth()).status_code == 200


def test_internal_event_triggers_reply(client):
    iid = _make_instance(client)
    client.put(f"/instances/{iid}/ai", headers=auth(), json={"provider": "ollama"})
    resp = client.post(
        "/internal/events",
        headers=internal(),
        json={"event": "message.received", "instance_id": iid, "from": "5511", "text": "oi"},
    )
    assert resp.json()["data"] == {"replied": True, "message_id": "MID-AI"}


def test_internal_event_requires_key(client):
    resp = client.post(
        "/internal/events", json={"event": "x", "instance_id": "i", "from": "1", "text": "hi"}
    )
    assert resp.status_code == 401
