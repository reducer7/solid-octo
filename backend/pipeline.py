from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend.common.models import PipelineContext, RequestPayload, ScoreState
from backend.common.simhash import compute_simhash, simhash_to_hex
from backend.database.redis_store import ScoreStore
from backend.reporter.submission_log import append_submission_log
from backend.reporter.report_gen import generate_response
from backend.tests.garbage.garbage_tests import run_garbage_pass
from backend.tests.construction.construction_tests import run_construction_pass
from backend.tests.similarity.similar import run_similarity_pass


class PipelineError(ValueError):
    pass


def process_submission(
    raw_request: dict[str, Any],
    store: ScoreStore,
    config: dict[str, Any],
    project_root: Path,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root_cfg = config["root"]
    app_cfg = root_cfg["app"]
    redis_cfg = root_cfg["redis"]

    payload = _parse_request(raw_request, require_captcha=bool(app_cfg["require_captcha"]))
    text = _normalize_and_trim(payload.text, int(app_cfg["max_text_length"]))

    bits = int(app_cfg["simhash_bits"])
    computed = compute_simhash(text, bits=bits)
    computed_hex = simhash_to_hex(computed, bits)

    ctx = PipelineContext(
        text=text,
        computed_simhash=computed,
        computed_simhash_hex=computed_hex,
        submitted_simhash=payload.simhash,
        score=ScoreState(),
    )

    _notify(on_progress, "pass1_similarity")
    reused = run_similarity_pass(
        ctx=ctx,
        store=store,
        similarity_cfg=config["similarity"],
        redis_cfg=redis_cfg,
    )

    if not reused:
        _notify(on_progress, "pass2_garbage")
        run_garbage_pass(
            ctx=ctx,
            garbage_cfg=config["garbage"],
            max_score=int(app_cfg["scoring_max"]),
            project_root=project_root,
        )
        if not ctx.terminal:
            _notify(on_progress, "pass3_construction")
            run_construction_pass(
                ctx=ctx,
                construction_cfg=config["construction"],
                max_score=int(app_cfg["scoring_max"]),
                project_root=project_root,
            )
        _persist_new_result(
            ctx=ctx,
            store=store,
            app_cfg=app_cfg,
            redis_cfg=redis_cfg,
            similarity_cfg=config["similarity"],
        )

    response = generate_response(
        ctx=ctx,
        report_cfg=config["report"],
        fuzz_cfg=root_cfg["fuzz"],
        max_score=int(app_cfg["scoring_max"]),
    )
    _log_submission(ctx, raw_request, config["report"], project_root)
    return response


def _log_submission(
    ctx: PipelineContext,
    raw_request: dict[str, Any],
    report_cfg: dict[str, Any],
    project_root: Path,
) -> None:
    if not bool(report_cfg.get("submission_logging_enabled", False)):
        return

    triggered_tests = ["similarity"]
    if not ctx.reused_result:
        triggered_tests.append("garbage")
        if not ctx.terminal:
            triggered_tests.append("construction")

    append_submission_log(
        project_root=project_root,
        report_cfg=report_cfg,
        raw_request=raw_request,
        ctx=ctx,
        triggered_tests=triggered_tests,
    )


def _parse_request(raw_request: dict[str, Any], require_captcha: bool) -> RequestPayload:
    required = ("text", "datetimeUTC")
    missing = [key for key in required if key not in raw_request]
    if missing:
        raise PipelineError(f"Missing request keys: {', '.join(missing)}")

    _reject_honeypot_hits(raw_request)

    text = raw_request["text"]
    captcha_token = raw_request.get("captcha_token")
    datetime_utc = raw_request["datetimeUTC"]
    simhash = raw_request.get("simhash")

    if not isinstance(text, str) or not text.strip():
        raise PipelineError("text must be a non-empty string")
    if require_captcha and (not isinstance(captcha_token, str) or not captcha_token.strip()):
        raise PipelineError("captcha_token must be a non-empty string")
    if captcha_token is not None and not isinstance(captcha_token, str):
        raise PipelineError("captcha_token must be a string when provided")
    if not isinstance(datetime_utc, str) or not datetime_utc.strip():
        raise PipelineError("datetimeUTC must be a non-empty string")
    if simhash is not None and not isinstance(simhash, str):
        raise PipelineError("simhash must be a string when provided")

    return RequestPayload(
        text=text,
        captcha_token=captcha_token,
        datetimeUTC=datetime_utc,
        simhash=simhash,
    )


def _reject_honeypot_hits(raw_request: dict[str, Any]) -> None:
    honeypot_fields = ("hp_website", "hp_company")
    for key in honeypot_fields:
        value = raw_request.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise PipelineError(f"{key} must be a string when provided")
        if value.strip():
            raise PipelineError("bot trap triggered")


def _normalize_and_trim(text: str, max_chars: int) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return normalized[:max_chars]


def _persist_new_result(
    ctx: PipelineContext,
    store: ScoreStore,
    app_cfg: dict[str, Any],
    redis_cfg: dict[str, Any],
    similarity_cfg: dict[str, Any],
) -> None:
    dominant = max(
        [
            ("ai", ctx.score.ai_score),
            ("human", ctx.score.human_score),
            ("garbage", ctx.score.garbage_score),
        ],
        key=lambda item: item[1],
    )[0]

    record = {
        "ai_score": ctx.score.ai_score,
        "human_score": ctx.score.human_score,
        "garbage_score": ctx.score.garbage_score,
        "dominant": dominant,
        "created_at": int(time.time()),
        "simhash": ctx.computed_simhash_hex,
        "version": int(app_cfg["schema_version"]),
        "istest": False,
    }

    store.save_entry(ctx.computed_simhash_hex, record)

    lsh_cfg = similarity_cfg["lsh"]
    store.add_candidate(
        simhash_hex=ctx.computed_simhash_hex,
        index_key=redis_cfg["similarity_index_key"],
        fallback_key=redis_cfg["fallback_bucket_key"],
        use_redisbloom=bool(similarity_cfg["use_redisbloom"]),
        use_fallback=bool(similarity_cfg["use_fallback_search"]),
        lsh_bands=int(lsh_cfg["bands"]),
        lsh_bits=int(lsh_cfg["bits"]),
    )


def _notify(on_progress: Callable[[str], None] | None, step: str) -> None:
    if on_progress is not None:
        try:
            on_progress(step)
        except Exception:
            pass
