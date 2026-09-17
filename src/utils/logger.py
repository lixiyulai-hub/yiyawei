"""日志工具。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logger(name: str = "vpc", level: str = "INFO", log_dir: str | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(Path(log_dir) / "app.log", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
