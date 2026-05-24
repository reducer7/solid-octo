from __future__ import annotations

import re
from typing import Any

from spellchecker import SpellChecker

from backend.common.models import PipelineContext

# ---------------------------------------------------------------------------
# Compiled regex constants
# ---------------------------------------------------------------------------

_POSSESSIVE_ERROR_RE = re.compile(r"\b(your's|their's|our's|its')\b", re.IGNORECASE)

_HOMOPHONE_ERROR_RE = re.compile(
    r"\byour\s+(?:going|doing|coming|welcome|not|never|right|wrong|kidding)\b"
    r"|\btheir\s+(?:going|doing|coming|not)\b",
    re.IGNORECASE,
)

# Lowercase letter immediately after a sentence-ending punctuation + space.
# Python's re module supports fixed-width lookbehinds: ". " is exactly 2 chars.
_LOWERCASE_AFTER_SENT_RE = re.compile(r"(?<=[.!?] )[a-z]")

# Mid-word camelCase: a word that starts with a lowercase letter followed by uppercase.
_MID_WORD_CAPS_RE = re.compile(r"\b[a-z][A-Z]\w*\b")

# Space before comma or semicolon.
_SPACE_BEFORE_COMMA_RE = re.compile(r"\s[,;]")

# No space after comma or semicolon (allow digits and newlines as valid exceptions).
_NO_SPACE_AFTER_COMMA_RE = re.compile(r"[,;][^\s\d\n]")

# Repeated adjacent words (the the, and and, etc.).
_REPEATED_WORD_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)

# "a" before a vowel-starting word (excl. "one", "once" which start with /w/).
_A_BEFORE_VOWEL_RE = re.compile(
    r"\ba\s+(?!one\b|once\b)[aeiou]\w+\b",
    re.IGNORECASE,
)

# "an" before a consonant-starting word (b-d, f-g, j-n, p-t, v-z — excludes silent h).
_AN_BEFORE_CONSONANT_RE = re.compile(
    r"\ban\s+[b-df-gj-np-tv-z]\w*\b",
    re.IGNORECASE,
)

# List-marker patterns (for mixed-style detection).
_BULLET_LINE_RE = re.compile(r"^\s*[-*\u2022]\s", re.MULTILINE)
_NUMBERED_LINE_RE = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
_LETTERED_LINE_RE = re.compile(r"^\s*[a-zA-Z][.)]\s", re.MULTILINE)
_ANGLE_LINE_RE = re.compile(r"^\s*>\s", re.MULTILINE)

# Sentence splitter for rhythm test.
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")

# Candidate word tokenizer for spelling checks.
_SPELL_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")

# Repeated character run for slang/elongation detection (e.g. "reeeally").
_ELONGATION_RE = re.compile(r"(.)\1{2,}", re.IGNORECASE)

_SPELL_CHECKER = SpellChecker()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_human_pass(
    ctx: PipelineContext,
    human_cfg: dict[str, Any],
    max_score: int,
    collect_spelling_debug: bool = False,
) -> None:
    _test_key_markers(ctx, human_cfg["key_markers"], ctx.text)
    _test_grammar(ctx, human_cfg["grammar"], ctx.text)
    _test_micro_hesitations(ctx, human_cfg["micro_hesitation"], ctx.text)
    _test_sentence_rhythm(ctx, human_cfg["rhythm"], ctx.text)
    _test_spelling_mistakes(
        ctx,
        human_cfg["spelling"],
        ctx.text,
        collect_debug=collect_spelling_debug,
    )
    ctx.score.clamp(max_score)


# ---------------------------------------------------------------------------
# Test 1 — Key markers
# ---------------------------------------------------------------------------


def _test_key_markers(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    # Double-hyphen first; single-hyphen is anything left after stripping --.
    double_hyphen_count = text.count("--")
    _add_capped_human(
        ctx, double_hyphen_count, cfg["double_hyphen_max"],
        "pass5_double_hyphen",
        f"double-hyphen occurrences: {double_hyphen_count}",
    )

    stripped = text.replace("--", "  ")
    single_hyphen_count = stripped.count("-")
    _add_capped_human(
        ctx, single_hyphen_count, cfg["single_hyphen_max"],
        "pass5_single_hyphen",
        f"standalone hyphen occurrences: {single_hyphen_count}",
    )

    straight_quote_count = text.count('"')
    _add_capped_human(
        ctx, straight_quote_count, cfg["straight_quote_max"],
        "pass5_straight_quote",
        f"ASCII double-quote occurrences: {straight_quote_count}",
    )

    triple_dot_count = len(re.findall(r"\.{3}", text))
    _add_capped_human(
        ctx, triple_dot_count, cfg["triple_dot_max"],
        "pass5_triple_dot",
        f"triple-dot occurrences: {triple_dot_count}",
    )

    # Double-dot: use lookahead to exclude triple-dots.
    double_dot_count = len(re.findall(r"\.{2}(?!\.)", text))
    double_dot_contrib = double_dot_count * cfg["double_dot_add"]
    _add_capped_human(
        ctx, double_dot_contrib, cfg["double_dot_max"],
        "pass5_double_dot",
        f"double-dot occurrences: {double_dot_count}",
    )

    semicolon_count = text.count(";")
    _add_capped_human(
        ctx, semicolon_count, cfg["semicolon_max"],
        "pass5_semicolon",
        f"semicolon occurrences: {semicolon_count}",
    )

    paren_imbalance = abs(text.count("(") - text.count(")"))
    unclosed_quote = text.count('"') % 2
    unclosed_count = paren_imbalance + unclosed_quote
    _add_capped_human(
        ctx, unclosed_count, cfg["unclosed_bracket_max"],
        "pass5_unclosed_bracket",
        f"unmatched brackets/quotes: {unclosed_count}",
    )


# ---------------------------------------------------------------------------
# Test 2 — Grammar
# ---------------------------------------------------------------------------


def _test_grammar(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    lines = text.splitlines()

    possessive_count = len(_POSSESSIVE_ERROR_RE.findall(text))
    _add_capped_human(
        ctx, possessive_count, cfg["possessive_error_max"],
        "pass5_possessive_error",
        f"possessive errors: {possessive_count}",
    )

    homophone_count = len(_HOMOPHONE_ERROR_RE.findall(text))
    _add_capped_human(
        ctx, homophone_count, cfg["homophone_error_max"],
        "pass5_homophone_error",
        f"homophone errors: {homophone_count}",
    )

    cap_count = (
        len(_LOWERCASE_AFTER_SENT_RE.findall(text))
        + len(_MID_WORD_CAPS_RE.findall(text))
    )
    _add_capped_human(
        ctx, cap_count, cfg["capitalization_max"],
        "pass5_capitalization",
        f"capitalization errors: {cap_count}",
    )

    spacing_count = (
        len(_SPACE_BEFORE_COMMA_RE.findall(text))
        + len(_NO_SPACE_AFTER_COMMA_RE.findall(text))
    )
    _add_capped_human(
        ctx, spacing_count, cfg["spacing_max"],
        "pass5_spacing",
        f"spacing errors: {spacing_count}",
    )

    repeated_count = len(_REPEATED_WORD_RE.findall(text))
    _add_capped_human(
        ctx, repeated_count, cfg["repeated_word_max"],
        "pass5_repeated_word",
        f"repeated word pairs: {repeated_count}",
    )

    a_an_count = (
        len(_A_BEFORE_VOWEL_RE.findall(text))
        + len(_AN_BEFORE_CONSONANT_RE.findall(text))
    )
    _add_capped_human(
        ctx, a_an_count, cfg["a_an_error_max"],
        "pass5_a_an_error",
        f"a/an article errors: {a_an_count}",
    )

    _check_paragraph_boundaries(ctx, cfg, lines)
    _check_list_formatting(ctx, cfg, text)


def _check_paragraph_boundaries(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    lines: list[str],
) -> None:
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) < 2:
        return

    has_blank = any(not ln.strip() for ln in lines)
    if has_blank:
        return

    # Multiple non-empty lines, no blank separators — count lines after the
    # first that start with a capital letter (likely paragraph starts).
    boundary_count = sum(
        1 for ln in non_empty[1:]
        if ln.strip() and ln.strip()[0].isupper()
    )
    _add_capped_human(
        ctx, boundary_count, cfg["paragraph_boundary_max"],
        "pass5_paragraph_boundary",
        f"missing blank-line paragraph boundaries: {boundary_count}",
    )


def _check_list_formatting(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    styles_found = sum([
        bool(_BULLET_LINE_RE.search(text)),
        bool(_NUMBERED_LINE_RE.search(text)),
        bool(_LETTERED_LINE_RE.search(text)),
        bool(_ANGLE_LINE_RE.search(text)),
    ])
    if styles_found >= 2:
        _add_capped_human(
            ctx, styles_found - 1, cfg["list_formatting_max"],
            "pass5_list_formatting",
            f"mixed list-marker styles: {styles_found}",
        )


# ---------------------------------------------------------------------------
# Test 3 — Micro-hesitations
# ---------------------------------------------------------------------------


def _test_micro_hesitations(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    total_matches = 0
    for raw_pattern in cfg["patterns"]:
        compiled = re.compile(raw_pattern, re.IGNORECASE)
        total_matches += len(compiled.findall(text))

    _add_capped_human(
        ctx, total_matches, cfg["max_add"],
        "pass5_micro_hesitation",
        f"micro-hesitation phrases: {total_matches}",
    )


# ---------------------------------------------------------------------------
# Test 4 — Sentence rhythm
# ---------------------------------------------------------------------------


def _test_sentence_rhythm(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    raw_sentences = _SENTENCE_SPLIT_RE.split(text)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    if len(sentences) < cfg["min_sentences"]:
        return

    short_threshold = cfg["short_threshold"]
    long_threshold = cfg["long_threshold"]

    n_short = sum(
        1 for s in sentences if len(s.split()) <= short_threshold
    )
    n_long = sum(
        1 for s in sentences if len(s.split()) >= long_threshold
    )

    amount = min(n_short, n_long, cfg["max_add"])
    _add_capped_human(
        ctx, amount, cfg["max_add"],
        "pass5_uneven_rhythm",
        f"short/long sentence mix: {n_short} short, {n_long} long",
    )


# ---------------------------------------------------------------------------
# Test 15 — Spelling mistakes
# ---------------------------------------------------------------------------


def _test_spelling_mistakes(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
    collect_debug: bool = False,
) -> None:
    min_token_len = int(cfg.get("min_token_len", 3))
    count_elongations = bool(cfg.get("count_elongations", True))
    elongation_repeat_min = int(cfg.get("elongation_repeat_min", 3))
    allowed_tokens = {str(token).lower() for token in cfg.get("allowed_extra_tokens", [])}

    candidates: list[str] = []
    candidate_occurrences: list[dict[str, Any]] = []
    debug_ranges: list[dict[str, Any]] = []
    elongation_hits = 0

    for match in _SPELL_TOKEN_RE.finditer(text):
        raw = match.group(0)
        token = raw.strip("'\"").replace("-", "")
        if not token:
            continue
        if len(token) < min_token_len:
            continue

        # Balanced policy: likely proper nouns/names (capitalized) are ignored.
        if token[0].isupper() and not token.isupper():
            continue

        lowered = token.lower()
        if lowered in allowed_tokens:
            continue

        if count_elongations:
            max_run = _max_repeat_run(lowered)
            if max_run >= elongation_repeat_min:
                elongation_hits += 1
                if collect_debug:
                    debug_ranges.append(
                        {
                            "start": int(match.start()),
                            "end": int(match.end()),
                            "token": raw,
                            "kind": "elongated",
                        }
                    )
                continue

        candidates.append(lowered)
        candidate_occurrences.append(
            {
                "normalized": lowered,
                "start": int(match.start()),
                "end": int(match.end()),
                "token": raw,
            }
        )

    unknown_words = _SPELL_CHECKER.unknown(candidates)
    if collect_debug and unknown_words:
        debug_ranges.extend(
            {
                "start": occ["start"],
                "end": occ["end"],
                "token": occ["token"],
                "kind": "unknown",
            }
            for occ in candidate_occurrences
            if occ["normalized"] in unknown_words
        )

    if collect_debug:
        ctx.spelling_debug = debug_ranges

    miss_count = len(unknown_words) + elongation_hits

    amount = min(miss_count * int(cfg.get("add_human", 1)), int(cfg.get("max_add", 8)))
    if amount <= 0:
        return

    sample_unknown = sorted(list(unknown_words))[:5]
    detail = (
        f"spelling issues: {miss_count} "
        f"(unknown={len(unknown_words)}, elongated={elongation_hits}, sample={sample_unknown})"
    )
    ctx.score.human_score += amount
    _record_score_contribution(ctx, "human", amount, "pass5_spelling_mistake", detail)


def _max_repeat_run(token: str) -> int:
    max_run = 1
    current = 1
    for i in range(1, len(token)):
        if token[i] == token[i - 1]:
            current += 1
            if current > max_run:
                max_run = current
        else:
            current = 1
    return max_run


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _add_capped_human(
    ctx: PipelineContext,
    raw_count: int,
    max_add: int,
    source: str,
    detail: str,
) -> None:
    if raw_count <= 0:
        return
    amount = min(raw_count, max_add)
    ctx.score.human_score += amount
    _record_score_contribution(ctx, "human", amount, source, detail)


def _record_score_contribution(
    ctx: PipelineContext,
    score: str,
    amount: int,
    source: str,
    detail: str,
) -> None:
    ctx.score_contributions.append(
        {"score": score, "amount": amount, "source": source, "detail": detail}
    )
