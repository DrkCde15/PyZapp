"""AI provider abstraction.

Two implementations cover every requested backend:
  - OpenAICompatibleProvider: OpenAI, Groq, OpenRouter, Ollama, Gemini
    (via its OpenAI-compatible endpoint). Same wire protocol, different
    base URL / key / model.
  - AnthropicProvider: native Anthropic Messages API.

Adding a new backend = one entry in PROVIDERS (or a new class if the
protocol differs). Nothing else changes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class ProviderSpec:
    kind: str  # "openai-compatible" | "anthropic"
    base_url: str = ""
    needs_key: bool = True
    default_model: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        kind="openai-compatible",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
    ),
    "groq": ProviderSpec(
        kind="openai-compatible",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
    ),
    "openrouter": ProviderSpec(
        kind="openai-compatible",
        base_url="https://openrouter.ai/api/v1",
        default_model="openrouter/auto",
        extra_headers={"X-Title": "PyZapp"},
    ),
    "ollama": ProviderSpec(
        kind="openai-compatible",
        base_url="http://localhost:11434/v1",
        needs_key=False,
        default_model="llama3.1",
    ),
    "gemini": ProviderSpec(
        kind="openai-compatible",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-flash",
    ),
    "anthropic": ProviderSpec(
        kind="anthropic",
        default_model="claude-sonnet-4-20250514",
    ),
}


class AIProvider(Protocol):
    async def generate(
        self, system: str | None, history: list[ChatMessage], user_text: str
    ) -> str: ...


class OpenAICompatibleProvider:
    """One client for every OpenAI-compatible backend (cloud or local)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        from openai import OpenAI

        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key or "not-needed",  # e.g. local Ollama
            default_headers=extra_headers or None,
        )
        self._model = model

    async def generate(
        self, system: str | None, history: list[ChatMessage], user_text: str
    ) -> str:
        messages = [
            {"role": m.role, "content": m.content}
            for m in history
            if m.role in ("user", "assistant")
        ]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        messages.append({"role": "user", "content": user_text})
        # The SDK is synchronous: run off the event loop.
        resp = await asyncio.to_thread(
            self._client.chat.completions.create,
            model=self._model,
            messages=messages,
        )
        return (resp.choices[0].message.content or "").strip()


class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model

    async def generate(
        self, system: str | None, history: list[ChatMessage], user_text: str
    ) -> str:
        messages = [
            {"role": m.role, "content": m.content}
            for m in [*history, ChatMessage("user", user_text)]
            if m.role in ("user", "assistant")
        ]
        kwargs: dict = {
            "model": self._model,
            "max_tokens": 1024,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        resp = await asyncio.to_thread(self._client.messages.create, **kwargs)
        return "".join(b.text for b in resp.content if b.type == "text").strip()


def build_provider(
    name: str,
    api_key: str | None,
    model: str | None = None,
    base_url: str | None = None,
) -> AIProvider:
    """Factory. `base_url` overrides the default (e.g. self-hosted gateway)."""
    key = name.lower()
    try:
        spec = PROVIDERS[key]
    except KeyError:
        raise ValueError(f"Unknown AI provider '{name}'. Available: {sorted(PROVIDERS)}") from None
    resolved_model = model or spec.default_model
    if spec.needs_key and not api_key:
        raise ValueError(f"Provider '{name}' requires an API key")
    if spec.kind == "anthropic":
        return AnthropicProvider(api_key or "", resolved_model)
    return OpenAICompatibleProvider(
        base_url or spec.base_url, api_key or "", resolved_model, spec.extra_headers
    )
