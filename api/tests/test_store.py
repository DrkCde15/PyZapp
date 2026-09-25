"""Store tests: memory backend + SQLite backend (stdlib sqlite3)."""

from __future__ import annotations

import pytest

from app.store import InstanceStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "sqlite":
        s = InstanceStore(tmp_path / "test.db")
    else:
        s = InstanceStore()
    yield s
    s.close()


@pytest.mark.asyncio()
async def test_add_get_list_remove(store):
    item = await store.add("a")
    assert item["instance_id"] == "a" and item["created_at"]

    assert (await store.get("a"))["instance_id"] == "a"
    assert await store.get("missing") is None

    await store.add("b")
    assert [i["instance_id"] for i in await store.list()] == ["a", "b"]

    assert await store.remove("a") is True
    assert await store.remove("a") is False
    assert [i["instance_id"] for i in await store.list()] == ["b"]


@pytest.mark.asyncio()
async def test_sync_ids_adopts_without_overwriting(store):
    await store.add("known")
    before = await store.get("known")
    await store.sync_ids(["known", "new"])
    assert await store.get("known") == before
    assert (await store.get("new"))["instance_id"] == "new"


@pytest.mark.asyncio()
async def test_sqlite_survives_reopen(tmp_path):
    db = tmp_path / "persist.db"
    s1 = InstanceStore(db)
    item = await s1.add("keep")
    s1.close()

    s2 = InstanceStore(db)  # simulates an API restart
    assert await s2.get("keep") == item
    s2.close()
