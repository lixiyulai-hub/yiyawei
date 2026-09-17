"""FunASR Paraformer 引擎（中文主链路）。"""

from __future__ import annotations

import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from src.asr.base import BaseASREngine


class FunASREngine(BaseASREngine):
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.model_name = config.get("model") or "paraformer-zh"
        self.language = config.get("language", "auto")
        self.requested_device = config.get("device", "cuda")
        self.device = _resolve_device(self.requested_device)
        if self.device != self.requested_device:
            self.config["fallback_used"] = True
            self.config["fallback_reason"] = f"{self.requested_device} unavailable"
        self.fallback_device = config.get("fallback_device", "cpu")
        self.trust_remote_code = bool(config.get("trust_remote_code", False))
        self.vad_model = config.get("vad_model")
        self.vad_kwargs = config.get("vad_kwargs")
        self.punc_model = config.get("punc_model")
        self.spk_model = config.get("spk_model")
        self.use_itn = bool(config.get("use_itn", True))
        self.batch_size_s = config.get("batch_size_s", 60)
        self.merge_vad = bool(config.get("merge_vad", True))
        self.merge_length_s = config.get("merge_length_s")
        self._model = None
        self._load_lock = threading.Lock()
        self.last_load_ms = 0
        self.last_infer_ms = 0

    def _load_model(self):
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            return self._load_model_unlocked()

    def _load_model_unlocked(self):
        try:
            from funasr import AutoModel
        except ImportError as e:
            raise ImportError(
                "funasr 未安装。请运行: pip install funasr modelscope"
            ) from e
        model_kwargs = self._build_model_kwargs()
        t0 = time.perf_counter()
        try:
            self._model = AutoModel(**model_kwargs)
        except Exception:
            if str(self.device).startswith("cuda") and self.fallback_device:
                self.device = self.fallback_device
                model_kwargs = self._build_model_kwargs()
                self._model = AutoModel(**model_kwargs)
                self.config["fallback_used"] = True
            else:
                raise
        self.last_load_ms = int((time.perf_counter() - t0) * 1000)
        return self._model

    def _build_model_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "device": self.device,
            "disable_update": True,
        }
        if self.trust_remote_code:
            kwargs["trust_remote_code"] = True
        if self.vad_model:
            kwargs["vad_model"] = self.vad_model
        if self.vad_kwargs:
            kwargs["vad_kwargs"] = self.vad_kwargs
        if self.punc_model:
            kwargs["punc_model"] = self.punc_model
        if self.spk_model:
            kwargs["spk_model"] = self.spk_model
        return kwargs

    def transcribe(self, audio_path: str) -> str:
        model = self._load_model()
        generate_kwargs: dict[str, Any] = {
            "input": audio_path,
            "cache": {},
            "language": self.language,
            "use_itn": self.use_itn,
            "batch_size_s": self.batch_size_s,
            "merge_vad": self.merge_vad,
        }
        if self.merge_length_s is not None:
            generate_kwargs["merge_length_s"] = self.merge_length_s
        t0 = time.perf_counter()
        result = model.generate(**generate_kwargs)
        self.last_infer_ms = int((time.perf_counter() - t0) * 1000)
        if not result:
            return ""
        return _clean_funasr_text(_extract_text(result))

    def warm(self) -> None:
        self._load_model()

    def transcribe_array(self, audio_data, sample_rate: int) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name
        try:
            audio = audio_data if isinstance(audio_data, np.ndarray) else np.array(audio_data)
            sf.write(path, audio, sample_rate)
            return self.transcribe(path)
        finally:
            Path(path).unlink(missing_ok=True)


def _extract_text(result: Any) -> str:
    if isinstance(result, list):
        parts: list[str] = []
        for item in result:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(result, dict):
        return str(result.get("text") or "")
    return str(result or "")


def _clean_funasr_text(text: str) -> str:
    result = text or ""
    result = re.sub(r"<\|[^|]+?\|>", "", result)
    return re.sub(r"\s+", " ", result).strip()


def _resolve_device(requested: str) -> str:
    if str(requested).startswith("cuda"):
        try:
            import torch

            if not torch.cuda.is_available():
                return "cpu"
        except Exception:
            return "cpu"
    return requested
