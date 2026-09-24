from __future__ import annotations

import sys
import types

import numpy as np
import pytest

if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = types.SimpleNamespace(InputStream=object)

from src.recorder.recorder import AudioRecorder


def test_trim_silence_removes_startup_and_trailing_noise() -> None:
    recorder = AudioRecorder(sample_rate=1000)
    audio = np.concatenate(
        [
            np.zeros(250, dtype=np.float32),
            np.full(500, 0.1, dtype=np.float32),
            np.zeros(250, dtype=np.float32),
        ]
    )

    trimmed = recorder._trim_silence(audio, threshold=0.02, margin_sec=0.0)

    assert trimmed is not None
    assert 500 <= len(trimmed) <= 520
    assert np.count_nonzero(trimmed[:20]) <= 10
    assert float(np.max(trimmed)) == pytest.approx(0.1)


def test_update_voice_activity_calibrates_noise_and_requires_repeated_activity() -> None:
    recorder = AudioRecorder(sample_rate=1000)
    recorder._recording = True
    recorder._start_time = 0.0
    recorder._calibration_sec = 0.35
    recorder._last_level = 0.01

    recorder._last_level = 0.01
    recorder._start_time = 100.0
    recorder._last_voice_time = 100.0
    recorder.update_voice_activity(0.015)
    assert recorder._voice_seen is False

    recorder._last_level = 0.05
    recorder._start_time = 99.0
    recorder.update_voice_activity(0.015)
    assert recorder._voice_seen is True


def test_stop_returns_none_when_only_startup_noise_was_captured() -> None:
    recorder = AudioRecorder(sample_rate=1000)
    recorder._recording = False
    recorder._voice_seen = False
    recorder._frames = [np.zeros((100, 1), dtype=np.float32)]

    assert recorder.stop() is None


def test_update_voice_activity_keeps_quiet_speech_alive_after_detection(
    monkeypatch,
) -> None:
    recorder = AudioRecorder(sample_rate=1000)
    recorder._recording = True
    recorder._start_time = 100.0
    recorder._last_voice_time = 100.0
    clock = iter((100.4, 100.52, 101.0))
    monkeypatch.setattr("src.recorder.recorder.time.time", lambda: next(clock))

    recorder._last_level = 0.02
    _, _, voice_seen = recorder.update_voice_activity(0.015)
    assert voice_seen is False
    recorder._last_level = 0.02
    _, _, voice_seen = recorder.update_voice_activity(0.015)
    assert voice_seen is True

    # Below the startup threshold, but still a plausible quiet syllable.
    recorder._last_level = 0.008
    silent_for, _, voice_seen = recorder.update_voice_activity(0.015)
    assert voice_seen is True
    assert silent_for == 0.0
