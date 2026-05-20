from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from backend.common.config_loader import resolve_from_project
from backend.common.models import PipelineContext


def run_garbage_pass(
    ctx: PipelineContext,
    garbage_cfg: dict[str, Any],
    max_score: int,
    project_root: Path,
) -> None:
    entropy_cfg = garbage_cfg["entropy"]
    repeated_cfg = garbage_cfg["repeated_char_density"]
    non_print_cfg = garbage_cfg["non_printable_density"]
    unicode_cfg = garbage_cfg["unicode_outliers"]
    salad_cfg = garbage_cfg["word_salad"]

    entropy = _shannon_entropy(ctx.text)
    if entropy > float(entropy_cfg["terminal_gt"]):
        ctx.score.garbage_score = int(entropy_cfg.get("terminal_score", max_score))
        _terminal(ctx, "pass2_entropy_terminal", max_score)
        return
    if entropy < float(entropy_cfg["low_lt"]):
        ctx.score.human_score += int(entropy_cfg["low_add_human"])
    else:
        ctx.score.human_score += int(entropy_cfg["mid_add_human"])
        ctx.score.ai_score += int(entropy_cfg["mid_add_ai"])

    repeated_ratio = _max_run_ratio(ctx.text)
    if repeated_ratio > float(repeated_cfg["terminal_gt"]):
        ctx.score.garbage_score = int(repeated_cfg["terminal_score"])
        _terminal(ctx, "pass2_repeated_char_terminal", max_score)
        return
    if repeated_ratio > float(repeated_cfg["warning_gt"]):
        ctx.score.garbage_score += int(repeated_cfg["warning_add_garbage"])

    non_print_ratio = _non_printable_ratio(ctx.text)
    if non_print_ratio > float(non_print_cfg["terminal_gt"]):
        ctx.score.garbage_score = int(non_print_cfg["terminal_score"])
        _terminal(ctx, "pass2_non_printable_terminal", max_score)
        return
    if non_print_ratio > float(non_print_cfg["warning_gt"]):
        ctx.score.garbage_score += int(non_print_cfg["warning_add_garbage"])

    outliers = _unicode_ratios(ctx.text)
    # Each category threshold is configurable to tune false-positive pressure.
    if outliers["other"] > float(unicode_cfg["other_gt"]):
        ctx.score.garbage_score = int(unicode_cfg["terminal_score"])
        _terminal(ctx, "pass2_unicode_other_terminal", max_score)
        return
    if outliers["punctuation"] > float(unicode_cfg["punct_gt"]):
        ctx.score.garbage_score = int(unicode_cfg["terminal_score"])
        _terminal(ctx, "pass2_unicode_punct_terminal", max_score)
        return
    if outliers["symbol"] > float(unicode_cfg["symbol_gt"]):
        ctx.score.garbage_score = int(unicode_cfg["terminal_score"])
        _terminal(ctx, "pass2_unicode_symbol_terminal", max_score)
        return
    if outliers["number"] > float(unicode_cfg["number_gt"]):
        ctx.score.garbage_score = int(unicode_cfg["terminal_score"])
        _terminal(ctx, "pass2_unicode_number_terminal", max_score)
        return

    dictionary_path = resolve_from_project(project_root, str(salad_cfg["dictionary_path"]))
    uncommon_ratio = _uncommon_word_ratio(
        text=ctx.text,
        token_pattern=str(salad_cfg["token_pattern"]),
        dictionary_words=_load_word_set(dictionary_path),
    )

    # High uncommon ratio indicates likely gibberish / non-language content.
    if uncommon_ratio > float(salad_cfg["uncommon_terminal_gt"]):
        ctx.score.garbage_score = int(salad_cfg["terminal_score"])
        _terminal(ctx, "pass2_word_salad_terminal", max_score)
        return
    if uncommon_ratio > float(salad_cfg["uncommon_warning_gt"]):
        ctx.score.garbage_score += int(salad_cfg["warning_add_garbage"])

    ctx.score.clamp(max_score)


def _terminal(ctx: PipelineContext, reason: str, max_score: int) -> None:
    ctx.skip_reason = reason
    ctx.terminal = True
    ctx.score.clamp(max_score)


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0

    counts = Counter(text)
    length = len(text)
    entropy = 0.0
    for count in counts.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def _max_run_ratio(text: str) -> float:
    if not text:
        return 0.0

    max_run = 1
    current_run = 1
    previous = text[0]

    for char in text[1:]:
        if char == previous:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 1
            previous = char

    return max_run / len(text)


def _non_printable_ratio(text: str) -> float:
    if not text:
        return 0.0

    control_chars = sum(1 for char in text if unicodedata.category(char) in {"Cc", "Cf"})
    return control_chars / len(text)


def _unicode_ratios(text: str) -> dict[str, float]:
    if not text:
        return {
            "letter": 0.0,
            "number": 0.0,
            "punctuation": 0.0,
            "symbol": 0.0,
            "other": 0.0,
        }

    total = len(text)
    counts = {
        "letter": 0,
        "number": 0,
        "punctuation": 0,
        "symbol": 0,
        "other": 0,
    }

    for char in text:
        category = unicodedata.category(char)
        head = category[0]
        if head == "L":
            counts["letter"] += 1
        elif head == "N":
            counts["number"] += 1
        elif head == "P":
            counts["punctuation"] += 1
        elif head == "S":
            counts["symbol"] += 1
        else:
            counts["other"] += 1

    return {name: value / total for name, value in counts.items()}


def _load_word_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _uncommon_word_ratio(text: str, token_pattern: str, dictionary_words: set[str]) -> float:
    tokens = [token.lower() for token in re.findall(token_pattern, text)]
    if not tokens:
        return 1.0
    if not dictionary_words:
        return 0.0

    uncommon = sum(1 for token in tokens if token not in dictionary_words)
    return uncommon / len(tokens)
