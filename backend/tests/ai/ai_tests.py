from __future__ import annotations

import re
from typing import Any

from backend.common.models import PipelineContext

# ---- public entry point -----------------------------------------------------

def run_ai_pass(
    ctx: PipelineContext,
    ai_cfg: dict[str, Any],
    max_score: int,
) -> None:
    key_cfg = ai_cfg["key_markers"]
    grammar_cfg = ai_cfg["grammar"]
    constructed_cfg = ai_cfg["constructed_sentences"]
    parallel_cfg = ai_cfg["perfect_parallelism"]
    hedge_cfg = ai_cfg["balance_hedges"]
    over_explain_cfg = ai_cfg["over_explanation"]
    no_personal_cfg = ai_cfg["no_personal_experience"]
    connector_cfg = ai_cfg["ai_connectors"]
    intensifier_cfg = ai_cfg["overused_intensifiers"]
    list_intro_cfg = ai_cfg["list_introductions"]

    _test_key_markers(ctx, key_cfg, ctx.text)
    _test_grammar(ctx, grammar_cfg, ctx.text)
    _test_constructed_sentences(ctx, constructed_cfg, ctx.text)
    _test_perfect_parallelism(ctx, parallel_cfg, ctx.text)
    _test_balance_hedges(ctx, hedge_cfg, ctx.text)
    _test_over_explanation(ctx, over_explain_cfg, ctx.text)
    _test_no_personal_experience(ctx, no_personal_cfg, ctx.text)
    _test_ai_connectors(ctx, connector_cfg, ctx.text)
    _test_overused_intensifiers(ctx, intensifier_cfg, ctx.text)
    _test_list_introductions(ctx, list_intro_cfg, ctx.text)

    ctx.score.clamp(max_score)


# ---- test 1: key markers ----------------------------------------------------

# Matching typographer left/right double-quote characters.
_TYPO_DOUBLE_OPEN = "\u201c"   # "
_TYPO_DOUBLE_CLOSE = "\u201d"  # "

# Typographer single left/right quote characters.
_SINGLE_CURLY_RE = re.compile(r"[\u2018\u2019]")

# Matches a single matched typographer double-quote pair and its contents.
_TYPO_DOUBLE_PAIR_RE = re.compile(
    r"\u201c[^\u201c\u201d]*\u201d"
)

# Parenthetical asides — non-empty balanced parens.
_ASIDE_RE = re.compile(r"\([^)]+\)")


def _test_key_markers(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    # Em dash (U+2014 —)
    em_count = text.count("\u2014")
    _add_capped(ctx, "ai", em_count, int(cfg["em_dash_max"]), "pass4_em_dash", {"count": em_count})

    # Colon
    colon_count = text.count(":")
    _add_capped(ctx, "ai", colon_count, int(cfg["colon_max"]), "pass4_colon", {"count": colon_count})

    # Parenthetical asides
    aside_count = len(_ASIDE_RE.findall(text))
    _add_capped(ctx, "ai", aside_count, int(cfg["aside_max"]), "pass4_aside", {"count": aside_count})

    # En dash (U+2013 –)
    en_count = text.count("\u2013")
    _add_capped(ctx, "ai", en_count, int(cfg["en_dash_max"]), "pass4_en_dash", {"count": en_count})

    # Matching typographer double-quote pairs ("...")
    typo_pair_count = len(_TYPO_DOUBLE_PAIR_RE.findall(text))
    _add_capped(
        ctx, "ai", typo_pair_count, int(cfg["typo_double_quote_max"]),
        "pass4_typo_double_quote", {"count": typo_pair_count},
    )

    # Single curly/typographer quotes — strip matched double-quote pair content
    # first so that inner single curly quotes are not double-counted against the
    # "matching typographer's double quotes" category above.
    stripped = _TYPO_DOUBLE_PAIR_RE.sub("", text)
    single_count = len(_SINGLE_CURLY_RE.findall(stripped))
    _add_capped(
        ctx, "ai", single_count, int(cfg["single_curly_max"]),
        "pass4_single_curly_quote", {"count": single_count},
    )


# ---- test 2: grammar --------------------------------------------------------

# Outer delimiter patterns for double quotes: typographer or straight ASCII.
_DOUBLE_OUTER = r'(?:[\u201c"])'
_DOUBLE_CLOSE = r'(?:[\u201d"])'

# Nested-quote pattern: double-quoted region that contains at least one
# single-quoted sub-region (straight or curly single quotes).
# The "before single quote" class stops at *any* quote char so the greedy
# match cannot consume the inner single quotes.
_NESTED_QUOTE_RE = re.compile(
    r'(?:[\u201c"])(?:[^\u201c\u201d\u2018\u2019"\']*(?:[\u2018\u2019\'])(?:[^\u2018\u2019\']+)'
    r'(?:[\u2018\u2019\'])[^\u201c\u201d"]*)(?:[\u201d"])',
    re.UNICODE,
)

# Plural possessive: word already ending in 's' followed immediately by an
# apostrophe (straight or curly right) NOT further followed by another 's'.
# Examples: customers', teachers', Jones' — but NOT it's, he's, boss's.
_PLURAL_POSSESSIVE_RE = re.compile(
    r"\b\w+s['\u2019](?!s\b)",
    re.UNICODE,
)


def _test_grammar(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    # Correctly nested quotes: "this is a 'quote'"
    nested = _NESTED_QUOTE_RE.findall(text)
    if nested:
        amount = min(len(nested) * int(cfg["nested_quote_add"]), int(cfg["nested_quote_max"]))
        ctx.score.ai_score += amount
        _record_score_contribution(
            ctx, "ai", amount, "pass4_nested_quotes", {"count": len(nested)},
        )

    # Correct use of plural possessives: customers', teachers'
    plural_pos = _PLURAL_POSSESSIVE_RE.findall(text)
    if plural_pos:
        amount = min(len(plural_pos) * int(cfg["plural_possessive_add"]), int(cfg["plural_possessive_max"]))
        ctx.score.ai_score += amount
        _record_score_contribution(
            ctx, "ai", amount, "pass4_plural_possessive", {"count": len(plural_pos)},
        )


# ---- test 3: constructed sentences -----------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)
_FIRST_PERSON_RE = re.compile(r"\b(i|me|my|mine|we|our|us)\b", re.IGNORECASE)
_QUOTE_OR_QUESTION_RE = re.compile(r"[\u201c\u201d\"]|\?")
_COLON_OR_SEMI_RE = re.compile(r"[:;]")


def _test_constructed_sentences(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    count = _count_regex_patterns(text, cfg["patterns"])
    if count <= 0:
        return

    amount = min(count * int(cfg["add_ai"]), int(cfg["max_add"]))
    ctx.score.ai_score += amount
    _record_score_contribution(
        ctx,
        "ai",
        amount,
        "pass4_constructed_sentences",
        {"count": count},
    )


# ---- test 4: perfect parallelism -------------------------------------------

_PARALLEL_PATTERNS = (
    re.compile(r"\b(?:to\s+\w+\s*,\s*){2,}to\s+\w+\b", re.IGNORECASE),
    re.compile(r"\b(?:\w+ing\s*,\s*){2,}\w+ing\b", re.IGNORECASE),
    re.compile(r"\b(?:\w+ly\s*,\s*){2,}\w+ly\b", re.IGNORECASE),
)


def _test_perfect_parallelism(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    count = 0
    for pattern in _PARALLEL_PATTERNS:
        count += len(pattern.findall(text))

    if count <= 0:
        return

    amount = min(count * int(cfg["add_ai"]), int(cfg["max_add"]))
    ctx.score.ai_score += amount
    _record_score_contribution(
        ctx,
        "ai",
        amount,
        "pass4_perfect_parallelism",
        {"count": count},
    )


# ---- test 5: overused balance hedges ---------------------------------------

def _test_balance_hedges(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    count = _count_regex_patterns(text, cfg["patterns"])
    if count <= 0:
        return

    amount = min(count * int(cfg["add_ai"]), int(cfg["max_add"]))
    ctx.score.ai_score += amount
    _record_score_contribution(
        ctx,
        "ai",
        amount,
        "pass4_balance_hedge",
        {"count": count},
    )


# ---- test 6: over explanation ----------------------------------------------

def _test_over_explanation(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    sentences = _split_sentences(text)
    if not sentences:
        return

    common_terms = [str(term).lower() for term in cfg.get("common_terms", [])]
    guard_terms = [str(term).lower() for term in cfg.get("domain_guard_terms", [])]
    strong_patterns = [re.compile(p) for p in cfg.get("strong_patterns", [])]
    weak_patterns = [re.compile(p) for p in cfg.get("weak_patterns", [])]

    min_words = int(cfg.get("min_sentence_words", 8))
    max_words = int(cfg.get("max_sentence_words", 32))

    strong_hits = 0
    weak_hits = 0

    for sentence in sentences:
        sentence_l = sentence.lower()
        word_count = len(_WORD_RE.findall(sentence_l))
        if word_count < min_words or word_count > max_words:
            continue
        if _QUOTE_OR_QUESTION_RE.search(sentence):
            continue
        if any(term in sentence_l for term in guard_terms):
            continue
        if not any(term in sentence_l for term in common_terms):
            continue

        local_strong = any(pattern.search(sentence) for pattern in strong_patterns)
        local_weak = any(pattern.search(sentence) for pattern in weak_patterns)
        if local_strong:
            strong_hits += 1
        elif local_weak:
            weak_hits += 1

    raw_count = 0
    if strong_hits > 0:
        raw_count += strong_hits
    if weak_hits >= 2:
        raw_count += weak_hits // 2
    if raw_count <= 0:
        return

    amount = min(raw_count * int(cfg["add_ai"]), int(cfg["max_add"]))
    ctx.score.ai_score += amount
    _record_score_contribution(
        ctx,
        "ai",
        amount,
        "pass4_over_explanation",
        {"strong_hits": strong_hits, "weak_hits": weak_hits, "raw_count": raw_count},
    )


# ---- test 7: no personal experience ----------------------------------------

def _test_no_personal_experience(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    words = _WORD_RE.findall(text)
    sentences = _split_sentences(text)
    if len(words) < int(cfg.get("min_total_words", 60)):
        return
    if len(sentences) < int(cfg.get("min_sentences", 3)):
        return

    memory_hits = _count_regex_patterns(text, cfg.get("memory_patterns", []))
    sensory_hits = _count_regex_patterns(text, cfg.get("sensory_patterns", []))
    metaphor_hits = _count_regex_patterns(text, cfg.get("metaphor_patterns", []))
    if memory_hits > 0 or sensory_hits > 0 or metaphor_hits > 0:
        return

    first_person_hits = len(_FIRST_PERSON_RE.findall(text))
    if first_person_hits > int(cfg.get("max_first_person", 0)):
        return

    impersonal_hits = _count_regex_patterns(text, cfg.get("impersonal_patterns", []))
    if impersonal_hits < int(cfg.get("min_impersonal_hits", 2)):
        return

    connector_hits = _count_regex_patterns(
        text,
        [
            r"(?i)\bnotably\b",
            r"(?i)\bcrucially\b",
            r"(?i)\bin essence\b",
            r"(?i)\bin many ways\b",
        ],
    )

    raw_count = 1
    if impersonal_hits >= int(cfg.get("min_impersonal_hits", 2)) + 2:
        raw_count += 1
    if connector_hits >= 2:
        raw_count += 1

    amount = min(raw_count * int(cfg["add_ai"]), int(cfg["max_add"]))
    ctx.score.ai_score += amount
    _record_score_contribution(
        ctx,
        "ai",
        amount,
        "pass4_no_personal_experience",
        {
            "impersonal_hits": impersonal_hits,
            "memory_hits": memory_hits,
            "sensory_hits": sensory_hits,
            "metaphor_hits": metaphor_hits,
            "first_person_hits": first_person_hits,
            "connector_hits": connector_hits,
            "raw_count": raw_count,
        },
    )


# ---- test 8: AI specific connectors ----------------------------------------

def _test_ai_connectors(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    count = _count_regex_patterns(text, cfg["patterns"])
    if count <= 0:
        return

    amount = min(count * int(cfg["add_ai"]), int(cfg["max_add"]))
    ctx.score.ai_score += amount
    _record_score_contribution(
        ctx,
        "ai",
        amount,
        "pass4_ai_connector",
        {"count": count},
    )


# ---- test 9: overused intensifiers -----------------------------------------

def _test_overused_intensifiers(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    count = _count_regex_patterns(text, cfg["patterns"])
    if count <= 0:
        return

    amount = min(count * int(cfg["add_ai"]), int(cfg["max_add"]))
    ctx.score.ai_score += amount
    _record_score_contribution(
        ctx,
        "ai",
        amount,
        "pass4_overused_intensifier",
        {"count": count},
    )


# ---- test 10: overused list introductions ----------------------------------

def _test_list_introductions(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    count = 0
    for pattern in cfg.get("patterns", []):
        regex = re.compile(pattern)
        for match in regex.finditer(text):
            tail = text[match.end(): match.end() + 24]
            if _COLON_OR_SEMI_RE.search(tail):
                count += 1

    if count <= 0:
        return

    amount = min(count * int(cfg["add_ai"]), int(cfg["max_add"]))
    ctx.score.ai_score += amount
    _record_score_contribution(
        ctx,
        "ai",
        amount,
        "pass4_list_introduction",
        {"count": count},
    )


# ---- helpers ----------------------------------------------------------------

def _add_capped(
    ctx: PipelineContext,
    score_name: str,
    raw_count: int,
    max_add: int,
    source: str,
    detail: dict[str, Any],
) -> None:
    """Add min(raw_count, max_add) to ctx.score, recording a contribution only
    when the raw count is non-zero."""
    if raw_count <= 0:
        return
    amount = min(raw_count, max_add)
    ctx.score.ai_score += amount
    _record_score_contribution(ctx, score_name, amount, source, detail)


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


def _count_regex_patterns(text: str, patterns: list[str]) -> int:
    total = 0
    for pattern in patterns:
        total += len(re.findall(pattern, text))
    return total


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text.strip()) if part.strip()]
