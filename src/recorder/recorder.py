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
        return audio.squeeze()

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
            if self._last_level >= level_threshold:
                self._last_voice_time = now
                self._voice_seen = True
            return now - self._last_voice_time, self._last_level, self._voice_seen

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
