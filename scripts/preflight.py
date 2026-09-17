#!/usr/bin/env python3
"""Preflight checks for Yiyawei."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config


def ok(label: str, detail: str = "") -> bool:
    print(f"[OK]   {label}{': ' + detail if detail else ''}")
    return True


def warn(label: str, detail: str = "") -> bool:
    print(f"[WARN] {label}{': ' + detail if detail else ''}")
    return False


def fail(label: str, detail: str = "") -> bool:
    print(f"[FAIL] {label}{': ' + detail if detail else ''}")
    return False


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def check_python() -> bool:
    version = ".".join(str(p) for p in sys.version_info[:3])
    if sys.version_info >= (3, 10):
        return ok("Python", version)
    return fail("Python", f"{version}; 需要 3.10+")


def check_imports() -> bool:
    required = [
        "yaml",
        "requests",
        "keyboard",
        "sounddevice",
        "soundfile",
        "numpy",
        "pyperclip",
        "pyautogui",
        "pydantic",
    ]
    passed = True
    for name in required:
        passed = (ok(f"package {name}") if has_module(name) else fail(f"package {name}", "not installed")) and passed
    return passed


def check_asr_profile_dependencies(config: dict[str, Any]) -> bool:
    profile = dict(config.get("asr") or {})
    engine = (profile.get("engine") or "funasr").lower()
    if engine == "funasr":
        missing = [name for name in ("funasr", "modelscope", "torch", "torchaudio") if not has_module(name)]
        if missing:
            return fail("ASR profile", f"FunASR Paraformer missing packages: {', '.join(missing)}")
        return ok("ASR profile", f"FunASR Paraformer: {profile.get('model', 'paraformer-zh')}")
    return fail("ASR profile", f"unknown engine={engine}")


def check_audio(config: dict[str, Any], record_seconds: float = 0.0) -> bool:
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as exc:
        return fail("audio check", str(exc))

    rec_cfg = config.get("recorder") or {}
    configured_device = rec_cfg.get("device")
    sample_rate = int(rec_cfg.get("sample_rate", 16000))
    channels = int(rec_cfg.get("channels", 1))
    dtype = rec_cfg.get("dtype", "float32")

    try:
        devices = sd.query_devices()
    except Exception as exc:
        return fail("input device list", str(exc))

    input_devices = []
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) > 0:
            input_devices.append((index, device))

    if not input_devices:
        return fail("input devices", "no input devices found")

    print("\nInput devices:")
    for index, device in input_devices:
        marker = ""
        if configured_device == index or str(configured_device) == str(index):
            marker = "  <-- config"
        print(
            f"  [{index}] {device.get('name')} | channels={device.get('max_input_channels')} | "
            f"default_sr={int(device.get('default_samplerate', 0))}{marker}"
        )

    try:
        default_input = sd.query_devices(kind="input")
        ok("default input device", default_input.get("name", "unknown"))
    except Exception as exc:
        warn("default input device", str(exc))

    if configured_device not in (None, ""):
        try:
            sd.query_devices(configured_device, kind="input")
            ok("recorder.device", str(configured_device))
        except Exception as exc:
            return fail("recorder.device", f"{configured_device} unavailable: {exc}")

    if record_seconds <= 0:
        return True

    try:
        frames = int(sample_rate * record_seconds)
        print(f"\nRecord test: {record_seconds:.1f}s. Speak into the microphone now...")
        audio = sd.rec(
            frames,
            samplerate=sample_rate,
            channels=channels,
            dtype=dtype,
            device=configured_device,
        )
        sd.wait()
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
        if peak > 0.005:
            return ok("record test", f"peak={peak:.4f}, rms={rms:.4f}")
        return warn("record test", f"very low level peak={peak:.4f}, rms={rms:.4f}")
    except Exception as exc:
        return fail("record test", str(exc))


def check_ollama(config: dict[str, Any]) -> bool:
    llm_cfg = config.get("llm") or {}
    provider = (llm_cfg.get("provider") or "").lower()
    if provider != "ollama":
        return warn("Ollama", f"llm.provider={provider or '<empty>'}; skipped")

    try:
        import requests
    except Exception as exc:
        return fail("Ollama", str(exc))

    base_url = (llm_cfg.get("base_url") or "http://localhost:11434").rstrip("/")
    model = llm_cfg.get("model") or ""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        return fail("Ollama service", f"{base_url} unavailable: {exc}")

    data = resp.json()
    models = [item.get("name", "") for item in data.get("models", [])]
    ok("Ollama service", base_url)
    if model in models:
        return ok("Ollama model", model)
    sample = ", ".join(models[:8]) if models else "no models returned"
    return fail("Ollama model", f"{model} not found; local models: {sample}")


def check_llm_smoke(config: dict[str, Any]) -> bool:
    try:
        from src.auditor.processor import AuditorProcessor
        from src.glossary.scanner import GlossaryScanner
        from src.llm import create_llm_adapter
        from src.safety.risk_checker import RiskChecker
    except Exception as exc:
        return fail("LLM smoke", str(exc))
    llm_cfg = config.get("llm") or {}
    try:
        adapter = create_llm_adapter(llm_cfg)
        glossary = GlossaryScanner((config.get("glossary") or {}).get("path"))
        risk_checker = RiskChecker(enabled=(config.get("safety") or {}).get("enabled", True))
        processor = AuditorProcessor(
            adapter,
            glossary,
            risk_checker,
            enable_filler_cleaning=(config.get("text_processing") or {}).get("enable_filler_cleaning", True),
        )
        t0 = time.perf_counter()
        result = processor.process(
            "帮我看一下登录页，不对不是登录页，是注册页。先检查按钮状态和表单校验，不要直接改代码。",
            mode="cursor_prompt",
        )
        elapsed = int((time.perf_counter() - t0) * 1000)
        if result.final_text.strip():
            return ok("LLM smoke", f"{elapsed}ms; final_text={result.final_text[:80]}")
        return fail("LLM smoke", "空响应")
    except Exception as exc:
        return fail("LLM smoke", str(exc))


def check_cuda() -> bool:
    if not has_module("torch"):
        return warn("CUDA", "torch not installed; skipped")
    try:
        import torch

        if torch.cuda.is_available():
            return ok("CUDA via Torch", torch.cuda.get_device_name(0))
        version = getattr(torch, "__version__", "")
        return warn("CUDA", f"torch detected no CUDA device ({version}); ASR will use CPU")
    except Exception as exc:
        return warn("CUDA", str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Yiyawei preflight")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--record-test", type=float, default=0.0, help="短录音测试秒数，例如 2")
    parser.add_argument("--llm-smoke", action="store_true", help="向本地 LLM 发一条最小请求")
    parser.add_argument("--json", action="store_true", help="输出配置摘要 JSON")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.json:
        summary = {
            "root": str(ROOT),
            "recorder": config.get("recorder"),
            "asr": config.get("asr"),
            "llm": {k: v for k, v in (config.get("llm") or {}).items() if k != "api_key"},
            "hotkeys": config.get("hotkeys"),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print("Yiyawei preflight")
    print(f"ROOT: {ROOT}\n")

    checks = [
        check_python(),
        check_imports(),
        check_asr_profile_dependencies(config),
        check_audio(config, args.record_test),
        check_ollama(config),
    ]
    check_cuda()
    if args.llm_smoke:
        checks.append(check_llm_smoke(config))

    print("\nNext steps:")
    print("  1. If the default microphone is wrong, set recorder.device in config.yaml to the input index.")
    print("  2. After Ollama/model is available, run: python app.py --text \"帮我整理这句话\"")
    print("  3. Final P0 test: focus Cursor/terminal input -> hold hotkey and speak -> release -> wait for paste.")

    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
