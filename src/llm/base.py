"""LLM 适配器基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMAdapter(ABC):
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.model = config.get("model", "")
        self.base_url = config.get("base_url", "")

    @abstractmethod
    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        pass

    def _merged_options(self, options: dict | None) -> dict[str, Any]:
        base = {
            "temperature": self.config.get("temperature", 0.1),
            "top_p": self.config.get("top_p", 0.8),
            "max_tokens": self.config.get("max_tokens", 600),
            "num_ctx": self.config.get("num_ctx", 4096),
            "keep_alive": self.config.get("keep_alive"),
        }
        if options:
            base.update(options)
        return base
