"""Planner model providers behind one tiny interface.

The planner asks a provider to complete a prompt; the provider hides whether
that's Anthropic, a local Ollama model, or nothing at all. ``make_provider``
returns ``None`` when no model is configured/available, which is the signal for
the planner to fall back to its deterministic built-in plan — so planning runs
cold with no API key.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.config import Settings


@runtime_checkable
class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str) -> str:
        """Return the model's text completion for the given prompts."""


class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        from anthropic import Anthropic  # lazy: only import when actually used

        self._client = Anthropic(api_key=api_key)
        self.name = "anthropic"
        self.model = model

    def complete(self, system: str, user: str) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in message.content if block.type == "text")


class OllamaProvider:
    def __init__(self, host: str, model: str) -> None:
        self._host = host.rstrip("/")
        self.name = "ollama"
        self.model = model

    def complete(self, system: str, user: str) -> str:
        import httpx

        resp = httpx.post(
            f"{self._host}/api/generate",
            json={"model": self.model, "system": system, "prompt": user, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["response"]


def make_provider(settings: Settings) -> Provider | None:
    """Build the configured provider, or None to use the deterministic planner."""
    if settings.model_provider == "anthropic":
        if not settings.anthropic_api_key:
            return None
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    if settings.model_provider == "ollama":
        return OllamaProvider(settings.ollama_host, settings.ollama_model)
    return None
