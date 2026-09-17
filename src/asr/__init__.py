"""ASR 工厂（产品主链路使用 FunASR Paraformer）。"""

from __future__ import annotations

from typing import Any

from src.asr.base import BaseASREngine


def create_asr_engine(config: dict[str, Any]) -> BaseASREngine:
    engine = (config.get("engine") or "funasr").lower()
    if engine == "funasr":
        from src.asr.funasr_engine import FunASREngine

        return FunASREngine(config)
    raise ValueError(f"Unsupported ASR engine: {engine}. This build uses FunASR Paraformer only.")
