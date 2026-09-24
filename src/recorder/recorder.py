"""按住/松开录音。"""

from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        dtype: str = "float32",
        max_duration_sec: int = 120,
        device: int | str | None = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.max_duration_sec = max_duration_sec
        self.device = device
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._recording = False
        self._start_time = 0.0
        self._last_voice_time = 0.0
        self._last_level = 0.0
        self._voice_seen = False
        self._noise_floor = 0.0
        self._activity_threshold = 0.015
        self._calibration_sec = 0.35
        self._speech_margin_sec = 0.18
        self._active_streak = 0

    def configure_voice_activity(
        self,
        *,
        level_threshold: float = 0.015,
        calibration_sec: float = 0.35,
        speech_margin_sec: float = 0.18,
    ) -> None:
        """Configure noise calibration and trimming without starting a stream."""
        with self._lock:
            self._activity_threshold = max(0.0001, float(level_threshold))
            self._calibration_sec = max(0.0, float(calibration_sec))
            self._speech_margin_sec = max(0.0, float(speech_margin_sec))

    def _callback(self, indata, frames, time_info, status):
        if status:
            pass
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())
                level = float(np.sqrt(np.mean(np.square(indata)))) if indata.size else 0.0
                self._last_level = level

    def start(self) -> None:
        with self._lock:
            self._frames = []
            self._recording = True
            self._start_time = time.time()
            self._last_voice_time = self._start_time
            self._last_level = 0.0
            self._voice_seen = False
            self._noise_floor = 0.0
            self._active_streak = 0
        if self._stream is None or not self._stream.active:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()

    def stop(self) -> np.ndarray | None:
        with self._lock:
            self._recording = False
        if not self._frames:
            return None
        audio = np.concatenate(self._frames, axis=0)
        elapsed = time.time() - self._start_time
        if elapsed > self.max_duration_sec:
            max_samples = int(self.max_duration_sec * self.sample_rate)
            audio = audio[:max_samples]
        with self._lock:
            voice_seen = self._voice_seen
            threshold = self._effective_threshold_locked()
            margin_sec = self._speech_margin_sec
        if not voice_seen:
            return None
        return self._trim_silence(audio.squeeze(), threshold, margin_sec)

    def get_elapsed_sec(self) -> float:
        with self._lock:
            if not self._recording:
                return 0.0
            return time.time() - self._start_time

    def update_voice_activity(self, level_threshold: float) -> tuple[float, float, bool]:
        now = time.time()
        with self._lock:
            if not self._recording:
                return 0.0, self._last_level, self._voice_seen
            self._activity_threshold = max(0.0001, float(level_threshold))
            elapsed = now - self._start_time
            if not self._voice_seen and elapsed <= self._calibration_sec:
                if self._noise_floor <= 0.0:
                    self._noise_floor = self._last_level
                else:
                    self._noise_floor = (self._noise_floor * 0.8) + (self._last_level * 0.2)
            threshold = self._effective_threshold_locked()
            # Once speech is detected, use a lower release threshold so a
            # quieter syllable does not start the full auto-stop timer.
            active_threshold = (
                threshold
                if not self._voice_seen
                else max(0.003, threshold * 0.45)
            )
            if self._last_level >= active_threshold:
                self._active_streak += 1
            else:
                self._active_streak = 0
            if self._active_streak >= 2 or (
                not self._voice_seen and self._last_level >= threshold * 2.0
            ):
                self._voice_seen = True
                self._last_voice_time = now
            return now - self._last_voice_time, self._last_level, self._voice_seen

    def _effective_threshold_locked(self) -> float:
        if self._noise_floor <= 0.0:
            return self._activity_threshold
        return max(self._activity_threshold, self._noise_floor * 2.5)

    def _trim_silence(
        self,
        audio: np.ndarray,
        threshold: float,
        margin_sec: float,
    ) -> np.ndarray | None:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return None
        window = max(1, int(self.sample_rate * 0.02))
        count = (samples.size + window - 1) // window
        levels = np.zeros(count, dtype=np.float32)
        for index in range(count):
            chunk = samples[index * window : (index + 1) * window]
            if chunk.size:
                levels[index] = float(np.sqrt(np.mean(np.square(chunk))))
        active = np.flatnonzero(levels >= threshold)
        if active.size == 0:
            return None
        margin = int(max(0.0, margin_sec) * self.sample_rate)
        start = max(0, int(active[0]) * window - margin)
        end = min(samples.size, (int(active[-1]) + 1) * window + margin)
        return samples[start:end]

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class HoldToRecordController:
    """按住开始、松开结束的录音控制器。"""

    def __init__(
        self,
        recorder: AudioRecorder,
        on_complete: Callable[[np.ndarray], None],
        on_start: Callable[[], None] | None = None,
    ):
        self.recorder = recorder
        self.on_complete = on_complete
        self.on_start = on_start
        self._held = False

    def on_press(self) -> None:
        if self._held:
            return
        self._held = True
        if self.on_start:
            self.on_start()
        self.recorder.start()

    def on_release(self) -> None:
        if not self._held:
            return
        self._held = False
        audio = self.recorder.stop()
        if audio is not None and len(audio) > 0:
            self.on_complete(audio)
