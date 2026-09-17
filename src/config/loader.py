"""配置加载。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _resolve_paths(data)


def _resolve_paths(data: dict[str, Any]) -> dict[str, Any]:
    storage = data.get("storage") or {}
    db_path = storage.get("db_path", "data/sessions.db")
    log_dir = storage.get("log_dir", "data/logs")
    storage["db_path"] = str((ROOT / db_path).resolve())
    storage["log_dir"] = str((ROOT / log_dir).resolve())

    glossary = data.get("glossary") or {}
    gpath = glossary.get("path", "src/glossary/tech_terms.json")
    glossary["path"] = str((ROOT / gpath).resolve())
    data["glossary"] = glossary

    data["text_processing"] = data.get("text_processing") or {}
    data["asr"] = data.get("asr") or {}

    data["storage"] = storage
    data["_root"] = str(ROOT)
    return data
