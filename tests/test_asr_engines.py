import sys
import types
from pathlib import Path

from src.asr.funasr_engine import (
    FunASREngine,
    _clean_funasr_text,
    _extract_text,
    _resolve_device,
)


ROOT = Path(__file__).resolve().parents[1]


def test_clean_funasr_text_removes_tags():
    text = _clean_funasr_text("<|zh|><|NEUTRAL|><|Speech|><|withitn|><|EMO_UNKNOWN|>你觉得我做得nice吗？")
    assert text == "你觉得我做得nice吗？"


def test_extract_text_from_funasr_result_list():
    text = _extract_text([{"text": "结论："}, {"text": "逻辑是通的。"}])
    assert text == "结论：逻辑是通的。"


def test_resolve_device_falls_back_when_torch_has_no_cuda(monkeypatch):
    fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert _resolve_device("cuda") == "cpu"


def test_model_kwargs_omit_trust_remote_code_by_default():
    kwargs = FunASREngine({"device": "cpu"})._build_model_kwargs()

    assert "trust_remote_code" not in kwargs


def test_model_kwargs_allow_explicit_trust_remote_code():
    kwargs = FunASREngine({"device": "cpu", "trust_remote_code": True})._build_model_kwargs()

    assert kwargs["trust_remote_code"] is True


def test_runtime_requirements_pin_funasr_1_3_14():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert [line.strip() for line in requirements if line.strip().lower().startswith("funasr")] == [
        "funasr==1.3.14"
    ]
