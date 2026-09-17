"""Faithful, local-only layout for ASR transcripts."""

from __future__ import annotations

import re


_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?])(?=\s*)")
def format_asr_transcript(text: str) -> str:
    """Lay out an ASR transcript without changing its words or punctuation.

    The formatter only trims outer whitespace, preserves existing word spacing,
    and turns existing sentence boundaries into readable paragraphs. It never
    inserts corrective wording, prompts, or inferred punctuation.
    """

    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n+", normalized):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        source = "\n".join(lines)
        sentences = [
            sentence.strip()
            for sentence in _SENTENCE_BOUNDARY.split(source)
            if sentence.strip()
        ]
        paragraphs.extend(sentences or [source])
    return "\n\n".join(paragraphs)
