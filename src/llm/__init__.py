"""LLM 工厂。"""

from __future__ import annotations

from typing import Any

from src.llm.base import BaseLLMAdapter
from src.llm.lmstudio_adapter import LMStudioAdapter
from src.llm.ollama_adapter import OllamaAdapter
from src.llm.openai_compatible_adapter import OpenAICompatibleAdapter


def create_llm_adapter(config: dict[str, Any]) -> BaseLLMAdapter:
    provider = (config.get("provider") or "ollama").lower()
    if provider == "ollama":
        return OllamaAdapter(config)
    if provider == "lmstudio":
        return LMStudioAdapter(config)
    if provider in ("openai_compatible", "openai", "compatible"):
        return OpenAICompatibleAdapter(config)
    raise ValueError(f"Unknown LLM provider: {provider}")
