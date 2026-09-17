"""Small persisted preference store used only by the Web GUI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class WebGuiSettingsStore:
    """Persist the Web GUI toggles in an ignored project-local JSON sidecar."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None

    @classmethod
    def from_app(cls, app: Any) -> "WebGuiSettingsStore":
        storage = getattr(app, "config", {}).get("storage") or {}
        log_dir = storage.get("log_dir")
        if not log_dir:
            return cls(None)
        return cls(Path(str(log_dir)) / "web_gui_settings.log")

    def load(self) -> dict[str, bool]:
        if self.path is None or not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            key: value[key]
            for key in ("useFast", "intelligentOutput")
            if isinstance(value.get(key), bool)
        }

    def save(self, *, use_fast: bool, intelligent_output: bool) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = json.dumps(
            {"useFast": bool(use_fast), "intelligentOutput": bool(intelligent_output)},
            ensure_ascii=False,
            sort_keys=True,
        )
        try:
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, self.path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
