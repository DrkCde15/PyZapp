"""AI persistence: per-instance config, conversation history, reply state.

Lives in the same SQLite file as instance metadata (one table per concern).
Memory-only when db_path is None, mirroring InstanceStore semantics.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from app.ai.providers import ChatMessage


@dataclass
class AIConfig:
    instance_id: str
    enabled: bool
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # per-instance override; falls back to env
    system_prompt: str | None = None
    max_history: int = 20
    cooldown_s: int = 0


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_config (
    instance_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    provider TEXT NOT NULL,
    model TEXT,
    base_url TEXT,
    api_key TEXT,
    system_prompt TEXT,
    max_history INTEGER NOT NULL DEFAULT 20,
    cooldown_s INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    chat TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_messages_chat
    ON ai_messages (instance_id, chat, id);
CREATE TABLE IF NOT EXISTS ai_state (
    instance_id TEXT NOT NULL,
    chat TEXT NOT NULL,
    last_reply_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (instance_id, chat)
);
"""


class AIStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None
        self._configs: dict[str, AIConfig] = {}
        self._messages: dict[tuple[str, str], list[ChatMessage]] = {}
        self._state: dict[tuple[str, str], float] = {}
        if db_path is not None:
            path = Path(db_path)
            if path.parent != Path("."):
                path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- config ---------------------------------------------------------
    async def save_config(self, cfg: AIConfig) -> AIConfig:
        async with self._lock:
            if self._conn is not None:
                self._conn.execute(
                    """INSERT OR REPLACE INTO ai_config
                       (instance_id, enabled, provider, model, base_url, api_key,
                        system_prompt, max_history, cooldown_s)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cfg.instance_id, int(cfg.enabled), cfg.provider, cfg.model,
                        cfg.base_url, cfg.api_key, cfg.system_prompt,
                        cfg.max_history, cfg.cooldown_s,
                    ),
                )
                self._conn.commit()
            else:
                self._configs[cfg.instance_id] = cfg
            return cfg

    async def get_config(self, instance_id: str) -> AIConfig | None:
        async with self._lock:
            if self._conn is not None:
                row = self._conn.execute(
                    "SELECT instance_id, enabled, provider, model, base_url, api_key,"
                    " system_prompt, max_history, cooldown_s FROM ai_config"
                    " WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
                return AIConfig(row[0], bool(row[1]), row[2], row[3], row[4], row[5], row[6], row[7], row[8]) if row else None
            return self._configs.get(instance_id)

    async def delete_config(self, instance_id: str) -> bool:
        async with self._lock:
            if self._conn is not None:
                cur = self._conn.execute("DELETE FROM ai_config WHERE instance_id = ?", (instance_id,))
                self._conn.commit()
                return cur.rowcount > 0
            return self._configs.pop(instance_id, None) is not None

    # -- history ----------------------------------------------------------
    async def append(self, instance_id: str, chat: str, role: str, content: str, max_history: int = 20) -> None:
        async with self._lock:
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO ai_messages (instance_id, chat, role, content, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (instance_id, chat, role, content, time.time()),
                )
                # Prune beyond the window.
                self._conn.execute(
                    """DELETE FROM ai_messages WHERE id NOT IN (
                           SELECT id FROM ai_messages
                           WHERE instance_id = ? AND chat = ?
                           ORDER BY id DESC LIMIT ?)""",
                    (instance_id, chat, max_history),
                )
                self._conn.commit()
            else:
                key = (instance_id, chat)
                self._messages.setdefault(key, []).append(ChatMessage(role, content))
                self._messages[key] = self._messages[key][-max_history:]

    async def history(self, instance_id: str, chat: str) -> list[ChatMessage]:
        async with self._lock:
            if self._conn is not None:
                rows = self._conn.execute(
                    "SELECT role, content FROM ai_messages"
                    " WHERE instance_id = ? AND chat = ? ORDER BY id",
                    (instance_id, chat),
                ).fetchall()
                return [ChatMessage(r[0], r[1]) for r in rows]
            return list(self._messages.get((instance_id, chat), []))

    # -- reply state --------------------------------------------------------
    async def last_reply_at(self, instance_id: str, chat: str) -> float:
        async with self._lock:
            if self._conn is not None:
                row = self._conn.execute(
                    "SELECT last_reply_at FROM ai_state WHERE instance_id = ? AND chat = ?",
                    (instance_id, chat),
                ).fetchone()
                return row[0] if row else 0.0
            return self._state.get((instance_id, chat), 0.0)

    async def mark_replied(self, instance_id: str, chat: str) -> None:
        now = time.time()
        async with self._lock:
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO ai_state (instance_id, chat, last_reply_at)"
                    " VALUES (?, ?, ?)",
                    (instance_id, chat, now),
                )
                self._conn.commit()
            else:
                self._state[(instance_id, chat)] = now
