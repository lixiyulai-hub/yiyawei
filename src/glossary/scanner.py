"""术语表扫描与规范化提示。"""

from __future__ import annotations

import json
import re
from pathlib import Path


class GlossaryScanner:
    def __init__(self, terms_path: str | Path | None = None):
        self.terms: dict[str, list[str]] = {}
        if terms_path:
            self.load(terms_path)

    def load(self, path: str | Path) -> None:
        p = Path(path)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                self.terms = json.load(f)

    def scan(self, text: str) -> list[tuple[str, str]]:
        """返回 (口语/误识别, 标准术语) 列表。"""
        found: list[tuple[str, str]] = []
        lower = text.lower()
        for canonical, variants in self.terms.items():
            for v in variants:
                if not v:
                    continue
                if v.lower() in lower or v in text:
                    found.append((v, canonical))
                    break
        return found

    def build_hints(self, text: str) -> str:
        matches = self.scan(text)
        if not matches:
            return ""
        lines = [f'- "{src}" → {dst}' for src, dst in matches]
        return "检测到以下术语，输出时请使用标准写法：\n" + "\n".join(lines)

    def normalize_text(self, text: str) -> str:
        """简单规则替换（LLM 前的轻量预处理）。"""
        result = text
        for canonical, variants in self.terms.items():
            for v in sorted(variants, key=len, reverse=True):
                if len(v) < 2:
                    continue
                pattern = re.compile(re.escape(v), re.IGNORECASE)
                result = pattern.sub(canonical, result)
        return result
