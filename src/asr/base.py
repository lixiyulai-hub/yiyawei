"""ASR 引擎基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseASREngine(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> str:
        pass

    def transcribe_array(self, audio_data, sample_rate: int) -> str:
        """可选：直接从 numpy 数组识别。"""
        raise NotImplementedError
