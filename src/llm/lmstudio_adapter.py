"""LM Studio OpenAI-compatible 适配器。"""

from __future__ import annotations

from typing import Any

import requests

from src.llm.base import BaseLLMAdapter


class LMStudioAdapter(BaseLLMAdapter):
    def generate(self, prompt: str, system: str = "", options: dict | None = None) -> str:
        opts = self._merged_options(options)
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": opts["temperature"],
            "top_p": opts["top_p"],
            "max_tokens": opts["max_tokens"],
            "stream": False,
        }
        timeout = self.config.get("timeout_sec", 120)
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message", {}).get("content") or "").strip()
