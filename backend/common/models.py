from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ScoreState:
    ai_score: int = 0
    human_score: int = 0
    garbage_score: int = 0

    def clamp(self, max_score: int) -> None:
        self.ai_score = max(0, min(max_score, self.ai_score))
        self.human_score = max(0, min(max_score, self.human_score))
        self.garbage_score = max(0, min(max_score, self.garbage_score))


@dataclass
class PipelineContext:
    text: str
    computed_simhash: int
    computed_simhash_hex: str
    submitted_simhash: str | None
    score: ScoreState
    novel_text: bool = True
    reused_result: bool = False
    skip_reason: str | None = None
    terminal: bool = False


@dataclass
class RequestPayload:
    text: str
    captcha_token: str
    datetimeUTC: str
    simhash: str | None


def score_from_entry(entry: dict[str, Any]) -> ScoreState:
    return ScoreState(
        ai_score=int(entry.get("ai_score", 0)),
        human_score=int(entry.get("human_score", 0)),
        garbage_score=int(entry.get("garbage_score", 0)),
    )
