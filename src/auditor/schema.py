"""审计输出 JSON Schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ModeType = Literal[
    "ai_chat",
    "cursor_prompt",
    "normal_dictation",
    "terminal_command",
    "git_message",
]

RiskLevel = Literal["low", "medium", "high"]


class CorrectionItem(BaseModel):
    from_: str = Field(alias="from")
    to: str
    reason: str = ""

    model_config = {"populate_by_name": True}


class AuditResult(BaseModel):
    final_text: str = ""
    mode: ModeType = "cursor_prompt"
    intent_summary: str = ""
    semantic_diagnosis: list[str] = Field(default_factory=list)
    output_requirements: list[str] = Field(default_factory=list)
    deleted_segments: list[str] = Field(default_factory=list)
    corrections: list[CorrectionItem] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    uncertain_terms: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    need_confirm: bool = False

    def to_dict(self) -> dict:
        d = self.model_dump(by_alias=True)
        return d
