from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.common.models import PipelineContext


def append_submission_log(
    project_root: Path,
    report_cfg: dict[str, Any],
    raw_request: dict[str, Any],
    ctx: PipelineContext,
    triggered_tests: list[str],
) -> None:
    log_path_value = str(report_cfg.get("submission_log_path", "backend/reporter/submission_log.jsonl"))
    log_path = Path(log_path_value)
    if not log_path.is_absolute():
        log_path = project_root / log_path

    log_path.parent.mkdir(parents=True, exist_ok=True)

    duplicate_of = _find_duplicate_entry(log_path, raw_request.get("text", ctx.text), ctx.computed_simhash_hex)

    entry = {
        "timestampUTC": datetime.now(timezone.utc).isoformat(),
        "input_text": raw_request.get("text", ctx.text),
        "triggered_tests": triggered_tests,
        "score_contributions": ctx.score_contributions,
        "score_totals": {
            "ai": ctx.score.ai_score,
            "human": ctx.score.human_score,
            "garbage": ctx.score.garbage_score,
        },
        "novel_text": ctx.novel_text,
        "reused_result": ctx.reused_result,
        "skip_reason": ctx.skip_reason,
        "simhash": ctx.computed_simhash_hex,
        "is_duplicate": duplicate_of is not None,
    }

    if duplicate_of is not None:
        entry["duplicate_of"] = {
            "timestampUTC": duplicate_of.get("timestampUTC"),
            "simhash": duplicate_of.get("simhash"),
        }

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _find_duplicate_entry(log_path: Path, input_text: str, simhash_hex: str) -> dict[str, Any] | None:
    if not log_path.exists():
        return None

    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("input_text") == input_text and entry.get("simhash") == simhash_hex:
            return entry

    return None