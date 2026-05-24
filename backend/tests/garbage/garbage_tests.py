from __future__ import annotations

import json
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
    line_cfg = garbage_cfg["line_length_variance"]
    bigram_cfg = garbage_cfg["bigram"]

    entropy = _shannon_entropy(ctx.text)
    if entropy > float(entropy_cfg["terminal_gt"]):
        ctx.score.garbage_score = int(entropy_cfg.get("terminal_score", max_score))
        _terminal(ctx, "pass2_entropy_terminal", max_score)
        return
    if entropy < float(entropy_cfg["low_lt"]):
        amount = int(entropy_cfg["low_add_human"])
        ctx.score.human_score += amount
        _record_score_contribution(
            ctx,
            score="human",
            amount=amount,
            source="pass2_entropy_low",
            detail={"entropy": entropy},
        )
    else:
        human_amount = int(entropy_cfg["mid_add_human"])
        ai_amount = int(entropy_cfg["mid_add_ai"])
        ctx.score.human_score += human_amount
        ctx.score.ai_score += ai_amount
        _record_score_contribution(
            ctx,
            score="human",
            amount=human_amount,
            source="pass2_entropy_mid",
            detail={"entropy": entropy},
        )
        _record_score_contribution(
            ctx,
            score="ai",
            amount=ai_amount,
            source="pass2_entropy_mid",
            detail={"entropy": entropy},
        )

    repeated_ratio = _max_run_ratio(ctx.text)
    if repeated_ratio > float(repeated_cfg["terminal_gt"]):
        ctx.score.garbage_score = int(repeated_cfg["terminal_score"])
        _terminal(ctx, "pass2_repeated_char_terminal", max_score)
        return
    if repeated_ratio > float(repeated_cfg["warning_gt"]):
        amount = int(repeated_cfg["warning_add_garbage"])
        ctx.score.garbage_score += amount
        _record_score_contribution(
            ctx,
            score="garbage",
            amount=amount,
            source="pass2_repeated_char_warning",
            detail={"repeated_ratio": repeated_ratio},
        )

    non_print_ratio = _non_printable_ratio(ctx.text)
    if non_print_ratio > float(non_print_cfg["terminal_gt"]):
        ctx.score.garbage_score = int(non_print_cfg["terminal_score"])
        _terminal(ctx, "pass2_non_printable_terminal", max_score)
        return
    if non_print_ratio > float(non_print_cfg["warning_gt"]):
        amount = int(non_print_cfg["warning_add_garbage"])
        ctx.score.garbage_score += amount
        _record_score_contribution(
            ctx,
            score="garbage",
            amount=amount,
            source="pass2_non_printable_warning",
            detail={"non_print_ratio": non_print_ratio},
        )

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
        ignore_proper_nouns=bool(salad_cfg.get("ignore_proper_nouns", False)),
    )

    # High uncommon ratio indicates likely gibberish / non-language content.
    if uncommon_ratio > float(salad_cfg["uncommon_terminal_gt"]):
        ctx.score.garbage_score = int(salad_cfg["terminal_score"])
        _terminal(ctx, "pass2_word_salad_terminal", max_score)
        return
    if uncommon_ratio > float(salad_cfg["uncommon_warning_gt"]):
        amount = int(salad_cfg["warning_add_garbage"])
        ctx.score.garbage_score += amount
        _record_score_contribution(
            ctx,
            score="garbage",
            amount=amount,
            source="pass2_word_salad_warning",
            detail={"uncommon_ratio": uncommon_ratio},
        )

    # Test 6: line-length variance
    sd = _line_length_sd(ctx.text, min_lines=int(line_cfg["min_lines"]))
    if sd is not None:
        if sd < float(line_cfg["low_lt"]):
            ai_amount = int(line_cfg["low_add_ai"])
            g_amount = int(line_cfg["low_add_garbage"])
            ctx.score.ai_score += ai_amount
            ctx.score.garbage_score += g_amount
            _record_score_contribution(
                ctx,
                score="ai",
                amount=ai_amount,
                source="pass2_line_length_low",
                detail={"line_length_sd": sd},
            )
            _record_score_contribution(
                ctx,
                score="garbage",
                amount=g_amount,
                source="pass2_line_length_low",
                detail={"line_length_sd": sd},
            )
        elif float(line_cfg["mid_gt"]) < sd < float(line_cfg["mid_lt"]):
            ai_amount = int(line_cfg["mid_add_ai"])
            hum_amount = int(line_cfg["mid_add_human"])
            ctx.score.ai_score += ai_amount
            ctx.score.human_score += hum_amount
            _record_score_contribution(
                ctx,
                score="ai",
                amount=ai_amount,
                source="pass2_line_length_mid",
                detail={"line_length_sd": sd},
            )
            _record_score_contribution(
                ctx,
                score="human",
                amount=hum_amount,
                source="pass2_line_length_mid",
                detail={"line_length_sd": sd},
            )
        elif sd > float(line_cfg["high_gt"]):
            g_amount = int(line_cfg["high_add_garbage"])
            ctx.score.garbage_score += g_amount
            _record_score_contribution(
                ctx,
                score="garbage",
                amount=g_amount,
                source="pass2_line_length_high",
                detail={"line_length_sd": sd},
            )

    # Test 7: character-bigram KL divergence
    bigram_path = resolve_from_project(project_root, str(bigram_cfg["bigram_path"]))
    reference_bigrams = _load_bigrams(bigram_path)
    kl = _bigram_kl_divergence(ctx.text, reference_bigrams)

    if kl > float(bigram_cfg["terminal_gt"]):
        ctx.score.garbage_score = int(bigram_cfg["terminal_score"])
        _terminal(ctx, "pass2_bigram_terminal", max_score)
        return
    elif kl > float(bigram_cfg["high_gt"]):
        amount = int(bigram_cfg["high_add_garbage"])
        ctx.score.garbage_score += amount
        _record_score_contribution(
            ctx,
            score="garbage",
            amount=amount,
            source="pass2_bigram_high",
            detail={"kl_divergence": kl},
        )
    elif kl > float(bigram_cfg["mid2_gt"]):
        g_amount = int(bigram_cfg["mid2_add_garbage"])
        ai_amount = int(bigram_cfg["mid2_add_ai"])
        ctx.score.garbage_score += g_amount
        ctx.score.ai_score += ai_amount
        _record_score_contribution(
            ctx,
            score="garbage",
            amount=g_amount,
            source="pass2_bigram_mid2",
            detail={"kl_divergence": kl},
        )
        _record_score_contribution(
            ctx,
            score="ai",
            amount=ai_amount,
            source="pass2_bigram_mid2",
            detail={"kl_divergence": kl},
        )
    elif kl > float(bigram_cfg["mid1_gt"]):
        g_amount = int(bigram_cfg["mid1_add_garbage"])
        ai_amount = int(bigram_cfg["mid1_add_ai"])
        ctx.score.garbage_score += g_amount
        ctx.score.ai_score += ai_amount
        _record_score_contribution(
            ctx,
            score="garbage",
            amount=g_amount,
            source="pass2_bigram_mid1",
            detail={"kl_divergence": kl},
        )
        _record_score_contribution(
            ctx,
            score="ai",
            amount=ai_amount,
            source="pass2_bigram_mid1",
            detail={"kl_divergence": kl},
        )
    elif kl < float(bigram_cfg["low_lt"]):
        ai_amount = int(bigram_cfg["low_add_ai"])
        hum_amount = int(bigram_cfg["low_add_human"])
        ctx.score.ai_score += ai_amount
        ctx.score.human_score += hum_amount
        _record_score_contribution(
            ctx,
            score="ai",
            amount=ai_amount,
            source="pass2_bigram_low",
            detail={"kl_divergence": kl},
        )
        _record_score_contribution(
            ctx,
            score="human",
            amount=hum_amount,
            source="pass2_bigram_low",
            detail={"kl_divergence": kl},
        )

    ctx.score.clamp(max_score)


def _terminal(ctx: PipelineContext, reason: str, max_score: int) -> None:
    ctx.skip_reason = reason
    ctx.terminal = True
    # Discard any partial ai/human scores accumulated before the terminal fired.
    ctx.score.ai_score = 0
    ctx.score.human_score = 0
    ctx.score_contributions = []
    ctx.score.clamp(max_score)


def _record_score_contribution(
    ctx: PipelineContext,
    score: str,
    amount: int,
    source: str,
    detail: dict[str, Any],
) -> None:
    ctx.score_contributions.append(
        {
            "score": score,
            "amount": amount,
            "source": source,
            "detail": detail,
        }
    )


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


def _line_length_sd(text: str, min_lines: int = 3) -> float | None:
    """Return the population SD of line lengths, or None if fewer than min_lines."""
    lines = text.splitlines()
    if len(lines) < min_lines:
        return None
    lengths = [len(line) for line in lines]
    mean = sum(lengths) / len(lengths)
    variance = sum((length - mean) ** 2 for length in lengths) / len(lengths)
    return math.sqrt(variance)


def _load_bigrams(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    return {k.upper(): float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def _bigram_kl_divergence(text: str, reference: dict[str, float]) -> float:
    """Compute KL(reference || observed) over the reference bigram set.

    Both distributions are normalised over the same reference vocabulary so
    that the comparison is fair regardless of how many non-reference bigrams
    appear in the text.  Returns 0.0 for a perfect match and increases as the
    relative proportions diverge from expected English.  Only uppercase letter
    pairs are considered.
    """
    if not reference:
        return 0.0

    upper = text.upper()
    letters = [ch for ch in upper if ch.isalpha()]
    if len(letters) < 2:
        return 0.0

    observed_counts: Counter[str] = Counter(
        letters[i] + letters[i + 1] for i in range(len(letters) - 1)
    )

    # Restrict to the reference vocabulary and normalise over it only.
    relevant_counts = {bg: observed_counts.get(bg, 0) for bg in reference}
    total_relevant = sum(relevant_counts.values())

    # No reference bigrams found at all — completely non-English.
    if total_relevant == 0:
        return float("inf")

    ref_total = sum(reference.values())
    n = len(reference)
    eps = 1e-9

    kl = 0.0
    for bigram, ref_freq in reference.items():
        p = ref_freq / ref_total
        q = (relevant_counts[bigram] + eps) / (total_relevant + eps * n)
        kl += p * math.log(p / q)

    return max(kl, 0.0)


def _load_word_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _uncommon_word_ratio(
    text: str,
    token_pattern: str,
    dictionary_words: set[str],
    ignore_proper_nouns: bool = False,
) -> float:
    raw_tokens = re.findall(token_pattern, text)
    if ignore_proper_nouns:
        raw_tokens = [token for token in raw_tokens if not _is_ignored_proper_noun_or_initialism(token)]

    tokens = [token.lower() for token in raw_tokens]
    if not tokens:
        return 1.0
    if not dictionary_words:
        return 0.0

    uncommon = sum(1 for token in tokens if token not in dictionary_words)
    return uncommon / len(tokens)


def _is_ignored_proper_noun_or_initialism(token: str) -> bool:
    if not token:
        return False

    letters_only = token.replace("'", "")
    if not letters_only:
        return False

    if letters_only.isupper() and len(letters_only) >= 2:
        return True

    return letters_only[0].isupper()
