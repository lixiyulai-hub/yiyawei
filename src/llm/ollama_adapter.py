"""Ollama 本地 LLM 适配器。"""

from __future__ import annotations

import json
from typing import Any

import requests

from src.llm.base import BaseLLMAdapter


class OllamaAdapter(BaseLLMAdapter):
    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        opts = self._merged_options(options)
        url = f"{self.base_url.rstrip('/')}/api/chat"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [],
            "stream": False,
            "options": {
                "temperature": opts["temperature"],
                "top_p": opts["top_p"],
                "num_ctx": opts["num_ctx"],
                "num_predict": opts["max_tokens"],
            },
        }
        if opts.get("keep_alive"):
            payload["keep_alive"] = opts["keep_alive"]
        if system:
            payload["messages"].append({"role": "system", "content": system})
        payload["messages"].append({"role": "user", "content": prompt})

        timeout = self.config.get("timeout_sec", 120)
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        message = data.get("message") or {}
        return (message.get("content") or "").strip()
