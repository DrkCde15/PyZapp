"""Instance metadata registry.

Holds only metadata (id, created_at). Connection state always comes
live from baileys-service.

Backend is chosen in the constructor:
  - InstanceStore()               -> in-memory (tests, ephemeral dev)
  - InstanceStore(db_path="...")  -> SQLite file (survives API restarts)

Routes depend only on the method signatures, so swapping SQLite for
PostgreSQL later touches just this file.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS instances (
    instance_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
)
"""


class InstanceStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = asyncio.Lock()
        self._items: dict[str, dict] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            path = Path(db_path)
            if path.parent != Path("."):
                path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.execute(_SCHEMA)
            self._conn.commit()

    @property
    def persistent(self) -> bool:
        return self._conn is not None

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def add(self, instance_id: str) -> dict:
        async with self._lock:
            item = {"instance_id": instance_id, "created_at": utcnow_iso()}
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO instances (instance_id, created_at) VALUES (?, ?)",
                    (instance_id, item["created_at"]),
                )
                self._conn.commit()
            else:
                self._items[instance_id] = item
            return dict(item)

    async def get(self, instance_id: str) -> dict | None:
        async with self._lock:
            if self._conn is not None:
                row = self._conn.execute(
                    "SELECT instance_id, created_at FROM instances WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
                return {"instance_id": row[0], "created_at": row[1]} if row else None
            item = self._items.get(instance_id)
            return dict(item) if item else None

    async def list(self) -> list[dict]:
        async with self._lock:
            if self._conn is not None:
                rows = self._conn.execute(
                    "SELECT instance_id, created_at FROM instances ORDER BY created_at"
                ).fetchall()
                return [{"instance_id": r[0], "created_at": r[1]} for r in rows]
            return [dict(v) for v in self._items.values()]

    async def remove(self, instance_id: str) -> bool:
        async with self._lock:
            if self._conn is not None:
                cur = self._conn.execute(
                    "DELETE FROM instances WHERE instance_id = ?", (instance_id,)
                )
                self._conn.commit()
                return cur.rowcount > 0
            return self._items.pop(instance_id, None) is not None

    async def sync_ids(self, ids: list[str]) -> None:
        """Adopt ids known by baileys-service (e.g. after API restart)."""
        async with self._lock:
            if self._conn is not None:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO instances (instance_id, created_at) VALUES (?, ?)",
                    [(i, utcnow_iso()) for i in ids],
                )
                self._conn.commit()
            else:
                for instance_id in ids:
                    self._items.setdefault(
                        instance_id,
                        {"instance_id": instance_id, "created_at": utcnow_iso()},
                    )
