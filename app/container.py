"""Dependency container wired at application startup."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from sqlmodel import Session

from app.adapters.llm.openrouter import LLMClient, OpenRouterClient
from app.settings import Settings


@dataclass
class Container:
    settings: Settings
    session_factory: Callable[[], Session]
    llm_client: LLMClient = field(init=False)

    def __post_init__(self) -> None:
        s = self.settings
        self.llm_client = OpenRouterClient(
            api_key=s.openrouter_api_key,
            base_url=s.openrouter_base_url,
            model_id=s.llm_model_id,
        )
