from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from backend.common.models import PipelineContext


def generate_response(
    ctx: PipelineContext,
    report_cfg: dict[str, Any],
    fuzz_cfg: dict[str, Any],
    max_score: int,
    include_spelling_debug: bool = False,
) -> dict[str, Any]:
    ai = ctx.score.ai_score
    human = ctx.score.human_score
    garbage = ctx.score.garbage_score

    if bool(report_cfg["fuzz_scores"]) and bool(fuzz_cfg["enabled"]):
        ai = _fuzz_score(ai, ctx.computed_simhash_hex, "ai", fuzz_cfg, max_score)
        human = _fuzz_score(human, ctx.computed_simhash_hex, "human", fuzz_cfg, max_score)
        garbage = _fuzz_score(garbage, ctx.computed_simhash_hex, "garbage", fuzz_cfg, max_score)

    payload: dict[str, Any] = {
        "ai_count": ai,
        "human_score": human,
        "garbage_score": garbage,
        "simhash": ctx.computed_simhash_hex,
        "score_contributions": ctx.score_contributions,
        "score_totals": {
            "ai": ctx.score.ai_score,
            "human": ctx.score.human_score,
            "garbage": ctx.score.garbage_score,
        },
    }

    if bool(report_cfg["include_novel_flag"]):
        payload["novel_text"] = ctx.novel_text
    if bool(report_cfg["include_reuse_flag"]):
        payload["reused_result"] = ctx.reused_result
    if ctx.skip_reason:
        payload["skip_reason"] = ctx.skip_reason
    if include_spelling_debug:
        payload["spelling_debug"] = ctx.spelling_debug

    return payload


def _fuzz_score(score: int, simhash_hex: str, label: str, fuzz_cfg: dict[str, Any], max_score: int) -> int:
    if score >= max_score:
        return score

    bucket_hours = int(fuzz_cfg["bucket_hours"])
    period = max(1, bucket_hours * 3600)
    bucket = int(datetime.now(timezone.utc).timestamp()) // period

    # Seeded jitter makes fingerprinting harder while keeping values stable in a time bucket.
    seed = f"{simhash_hex}:{label}:{bucket}".encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    max_jitter = int(fuzz_cfg["max_jitter"])
    spread = (2 * max_jitter) + 1
    jitter = (digest[0] % spread) - max_jitter

    return max(0, min(max_score, score + jitter))
