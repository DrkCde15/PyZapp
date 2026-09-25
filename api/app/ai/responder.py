"""Auto-responder: inbound WhatsApp text -> provider -> reply.

Safety rules (anti-loop / anti-spam):
  - only 1:1 chats (Baileys already filters groups/status upstream)
  - empty provider output is never sent
  - per-chat cooldown between replies
  - opt-out words skip the reply (SAIR/STOP/PARAR by default)
"""

from __future__ import annotations

import logging

from app.ai.providers import AIProvider, ChatMessage, build_provider
from app.ai.store import AIConfig, AIStore
from app.logging_utils import mask_phone

logger = logging.getLogger("pyzapp")

OPT_OUT_WORDS = {"sair", "stop", "parar", "cancelar"}

# Env fallback per provider, e.g. OPENAI_API_KEY, GROQ_API_KEY, ...
PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama": None,  # local, key optional
}


class AIResponder:
    def __init__(
        self,
        store: AIStore,
        env: dict[str, str],
        send_message,
    ) -> None:
        """
        send_message: async (instance_id, to_phone, text) -> message_id.
        Injected so routes wire the real Baileys client and tests use a fake.
        """
        self._store = store
        self._env = env
        self._send = send_message

    def _provider_for(self, cfg: AIConfig) -> AIProvider:
        key = cfg.api_key
        if not key:
            env_name = PROVIDER_ENV_KEYS.get(cfg.provider.lower())
            key = self._env.get(env_name) if env_name else None
        return build_provider(cfg.provider, key, cfg.model, cfg.base_url)

    async def handle_inbound(
        self, instance_id: str, chat: str, text: str, message_id: str | None = None
    ) -> str | None:
        """Process one inbound text. Returns the reply message_id, or None."""
        cfg = await self._store.get_config(instance_id)
        if cfg is None or not cfg.enabled:
            return None
        if not text.strip():
            return None
        if text.strip().lower() in OPT_OUT_WORDS:
            logger.info("event=ai_opt_out instance_id=%s from=%s", instance_id, mask_phone(chat))
            return None

        if cfg.cooldown_s > 0:
            import time

            elapsed = time.time() - await self._store.last_reply_at(instance_id, chat)
            if elapsed < cfg.cooldown_s:
                logger.info("event=ai_cooldown_skip instance_id=%s from=%s", instance_id, mask_phone(chat))
                return None

        try:
            provider = self._provider_for(cfg)
        except ValueError as exc:
            logger.error("event=ai_misconfigured instance_id=%s error=%s", instance_id, exc)
            return None

        history = await self._store.history(instance_id, chat)
        try:
            reply = await provider.generate(cfg.system_prompt, history, text)
        except Exception as exc:  # noqa: BLE001 - provider outage must not break ingestion
            logger.error(
                "event=ai_failed instance_id=%s from=%s error=%s",
                instance_id, mask_phone(chat), type(exc).__name__,
            )
            return None
        if not reply:
            logger.info("event=ai_empty_reply instance_id=%s", instance_id)
            return None

        await self._store.append(instance_id, chat, "user", text, cfg.max_history)
        await self._store.append(instance_id, chat, "assistant", reply, cfg.max_history)
        sent_id = await self._send(instance_id, chat, reply)
        await self._store.mark_replied(instance_id, chat)
        logger.info(
            "event=ai_replied instance_id=%s from=%s message_id=%s",
            instance_id, mask_phone(chat), sent_id,
        )
        return sent_id
