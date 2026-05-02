"""OpenRouter LLM adapter behind a simple protocol."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from openai import OpenAI


@runtime_checkable
class LLMClient(Protocol):
    """Minimal interface for LLM calls used throughout the app."""

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.4,
    ) -> str:
        """Return the assistant message content as a plain string."""
        ...


class OpenRouterClient:
    """Concrete implementation backed by OpenRouter."""

    def __init__(self, api_key: str, base_url: str, model_id: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model_id = model_id

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.4,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self._model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content
