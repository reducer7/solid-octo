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
_SPELL_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’‘\-]*")

# Repeated character run for slang/elongation detection (e.g. "reeeally").
_ELONGATION_RE = re.compile(r"(.)\1{2,}", re.IGNORECASE)

_STOPWORD_TOKENS = {
    "a", "an", "and", "any", "as", "at", "back", "be", "been", "but", "by",
    "for", "from", "had", "has", "have", "he", "her", "here", "him", "his",
    "i", "if", "in", "into", "is", "it", "its", "me", "my", "no", "not", "of",
    "oh", "on", "or", "our", "she", "so", "that", "the", "their", "them", "then",
    "there", "they", "this", "to", "up", "us", "was", "we", "were", "what", "where",
    "who", "why", "with", "you", "your", "anyway",
}

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
    _test_grounded_novelty(ctx, human_cfg["grounded_novelty"])
    _test_local_contradictions(ctx, human_cfg["local_contradictions"], ctx.text)
    _test_temporal_drift(ctx, human_cfg["temporal_drift"], ctx.text)
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
# Test 5 — Grounded novelty score
# ---------------------------------------------------------------------------


def _test_grounded_novelty(
    ctx: PipelineContext,
    cfg: dict[str, Any],
) -> None:
    doc = ctx.parsed_doc
    if doc is None:
        return

    sensory_terms = {str(item).lower() for item in cfg.get("sensory_terms", [])}
    proprioceptive_terms = {str(item).lower() for item in cfg.get("proprioceptive_terms", [])}
    spatial_prepositions = {str(item).lower() for item in cfg.get("spatial_prepositions", [])}
    concrete_nouns = {str(item).lower() for item in cfg.get("concrete_nouns", [])}
    abstract_nouns = {str(item).lower() for item in cfg.get("abstract_nouns", [])}
    novelty_terms = {str(item).lower() for item in cfg.get("novelty_terms", [])}

    content_tokens = [tok for tok in doc if tok.is_alpha and not tok.is_stop]
    if len(content_tokens) < int(cfg.get("min_content_tokens", 0)):
        return

    sensory_hits = 0
    proprio_hits = 0
    spatial_hits = 0
    concrete_hits = 0
    abstract_hits = 0
    novelty_hits = 0

    for token in doc:
        if not token.is_alpha:
            continue

        lemma = token.lemma_.lower()
        text = token.text.lower()

        if lemma in sensory_terms or text in sensory_terms:
            sensory_hits += 1
        if lemma in proprioceptive_terms or text in proprioceptive_terms:
            proprio_hits += 1
        if token.pos_ == "ADP" and text in spatial_prepositions:
            spatial_hits += 1
        if token.pos_ in ("NOUN", "PROPN") and (lemma in concrete_nouns or text in concrete_nouns):
            concrete_hits += 1
        if token.pos_ in ("NOUN", "PROPN") and (lemma in abstract_nouns or text in abstract_nouns):
            abstract_hits += 1
        if lemma in novelty_terms or text in novelty_terms:
            novelty_hits += 1

    content_count = len(content_tokens)
    grounding_ratio = (sensory_hits + proprio_hits + spatial_hits + concrete_hits) / content_count
    novelty_ratio = (abstract_hits + novelty_hits) / content_count

    if grounding_ratio >= float(cfg.get("low_grounding_ratio_lt", 0.0)):
        return
    if novelty_ratio < float(cfg.get("high_novelty_ratio_gte", 1.0)):
        return

    detail = {
        "grounding_ratio": round(grounding_ratio, 4),
        "novelty_ratio": round(novelty_ratio, 4),
        "sensory_hits": sensory_hits,
        "proprio_hits": proprio_hits,
        "spatial_hits": spatial_hits,
        "concrete_hits": concrete_hits,
        "abstract_hits": abstract_hits,
        "novelty_hits": novelty_hits,
        "content_tokens": content_count,
    }
    _add_capped_score(
        ctx,
        score="ai",
        raw_count=int(cfg.get("add_ai", 0)),
        max_add=int(cfg.get("max_add", 0)),
        source="pass5_grounded_novelty",
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Test 6 — Local contradictions
# ---------------------------------------------------------------------------


def _test_local_contradictions(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    total_matches = 0
    for raw_pattern in cfg["patterns"]:
        compiled = re.compile(raw_pattern, re.IGNORECASE)
        total_matches += len(compiled.findall(text))

    raw_count = total_matches * int(cfg.get("add_human", 1))
    _add_capped_human(
        ctx,
        raw_count,
        int(cfg.get("max_add", 0)),
        "pass5_local_contradiction",
        f"local contradiction markers: {total_matches}",
    )


# ---------------------------------------------------------------------------
# Test 7 — Temporal drift
# ---------------------------------------------------------------------------


def _test_temporal_drift(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    text: str,
) -> None:
    sentences = _sentence_texts(ctx.parsed_doc, text)

    tense_count = _count_tense_shifts(ctx.parsed_doc, sentences, cfg["tense"])
    _add_capped_human(
        ctx,
        tense_count * int(cfg["tense"].get("add_human", 1)),
        int(cfg["tense"].get("max_add", 0)),
        "pass5_temporal_drift_tense",
        f"temporal drift tense changes: {tense_count}",
    )

    perspective_count = _count_perspective_shifts(sentences, cfg["perspective"])
    _add_capped_human(
        ctx,
        perspective_count * int(cfg["perspective"].get("add_human", 1)),
        int(cfg["perspective"].get("max_add", 0)),
        "pass5_temporal_drift_perspective",
        f"temporal drift perspective changes: {perspective_count}",
    )

    return_count = _count_unreturned_callbacks(sentences, cfg["return"])
    _add_capped_human(
        ctx,
        return_count * int(cfg["return"].get("add_human", 1)),
        int(cfg["return"].get("max_add", 0)),
        "pass5_temporal_drift_return",
        f"temporal drift missing returns: {return_count}",
    )


def _count_tense_shifts(
    doc: Any,
    sentences: list[str],
    cfg: dict[str, Any],
) -> int:
    if doc is None:
        return _count_tense_shifts_regex(sentences, cfg)

    future_markers = {str(item).lower() for item in cfg.get("future_markers", [])}
    min_tense_cues = int(cfg.get("min_tense_cues", 2))
    count = 0

    for sent in doc.sents:
        past_cues = 0
        present_cues = 0
        future_cues = 0

        for token in sent:
            if not token.is_alpha:
                continue

            lower = token.lower_
            if lower in future_markers:
                future_cues += 1

            if lower in {str(item).lower() for item in cfg.get("past_markers", [])}:
                past_cues += 1
            if lower in {str(item).lower() for item in cfg.get("present_markers", [])}:
                present_cues += 1

            if token.pos_ not in ("AUX", "VERB"):
                continue

            if token.tag_ in ("VBD", "VBN"):
                past_cues += 1
            if token.tag_ in ("VBP", "VBZ"):
                present_cues += 1

        total_cues = past_cues + present_cues + future_cues
        if total_cues < min_tense_cues:
            continue
        if past_cues > 0 and (present_cues > 0 or future_cues > 0):
            count += 1

    return count


def _count_tense_shifts_regex(
    sentences: list[str],
    cfg: dict[str, Any],
) -> int:
    past_markers = {str(item).lower() for item in cfg.get("past_markers", [])}
    present_markers = {str(item).lower() for item in cfg.get("present_markers", [])}
    future_markers = {str(item).lower() for item in cfg.get("future_markers", [])}
    min_tense_cues = int(cfg.get("min_tense_cues", 2))
    count = 0

    for sentence in sentences:
        tokens = re.findall(r"\b[a-z']+\b", sentence.lower())
        past_cues = sum(1 for token in tokens if token in past_markers)
        present_cues = sum(1 for token in tokens if token in present_markers)
        future_cues = sum(1 for token in tokens if token in future_markers)
        total_cues = past_cues + present_cues + future_cues
        if total_cues < min_tense_cues:
            continue
        if past_cues > 0 and (present_cues > 0 or future_cues > 0):
            count += 1

    return count


def _count_perspective_shifts(
    sentences: list[str],
    cfg: dict[str, Any],
) -> int:
    first_singular = {str(item).lower() for item in cfg.get("first_singular", [])}
    first_plural = {str(item).lower() for item in cfg.get("first_plural", [])}
    second_person = {str(item).lower() for item in cfg.get("second_person", [])}
    count = 0
    previous_bucket: str | None = None

    for sentence in sentences:
        tokens = re.findall(r"\b[a-z']+\b", sentence.lower())
        buckets: set[str] = set()
        if any(token in first_singular for token in tokens):
            buckets.add("first_singular")
        if any(token in first_plural for token in tokens):
            buckets.add("first_plural")
        if any(token in second_person for token in tokens):
            buckets.add("second_person")

        if len(buckets) >= 2:
            count += 1
            previous_bucket = None
            continue

        current_bucket = next(iter(buckets), None)
        if current_bucket is None:
            continue

        if previous_bucket is not None and current_bucket != previous_bucket:
            count += 1

        previous_bucket = current_bucket

    return count


def _count_unreturned_callbacks(
    sentences: list[str],
    cfg: dict[str, Any],
) -> int:
    lookahead = int(cfg.get("lookahead_sentences", 2))
    min_anchor_tokens = int(cfg.get("min_anchor_tokens", 1))
    min_anchor_overlap = int(cfg.get("min_anchor_overlap", 1))
    min_anchor_token_len = int(cfg.get("min_anchor_token_len", 4))
    count = 0

    for idx, sentence in enumerate(sentences):
        match = None
        for raw_pattern in cfg["patterns"]:
            match = re.search(raw_pattern, sentence, re.IGNORECASE)
            if match:
                break

        if match is None:
            continue

        anchor_source = sentence[: match.start()].strip()
        anchor_tokens = _extract_anchor_tokens(anchor_source, min_anchor_token_len)
        if len(anchor_tokens) < min_anchor_tokens and idx > 0:
            anchor_tokens = _extract_anchor_tokens(sentences[idx - 1], min_anchor_token_len)

        if len(anchor_tokens) < min_anchor_tokens:
            continue

        follow_up = [sentence[match.end() :]]
        follow_up.extend(sentences[idx + 1 : idx + 1 + lookahead])
        follow_up_tokens = _extract_anchor_tokens(" ".join(follow_up), min_anchor_token_len)

        if len(anchor_tokens & follow_up_tokens) < min_anchor_overlap:
            count += 1

    return count


def _sentence_texts(doc: Any, text: str) -> list[str]:
    if doc is not None:
        return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]


def _extract_anchor_tokens(text: str, min_token_len: int) -> set[str]:
    return {
        token
        for token in re.findall(r"\b[a-z']+\b", text.lower())
        if len(token) >= min_token_len and token not in _STOPWORD_TOKENS
    }


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
        token = raw.strip("'\"’‘").replace("-", "").replace("’", "'").replace("‘", "'")
        if not token:
            continue
        if len(token) < min_token_len:
            continue

        # Balanced policy: ignore capitalized words and all-caps initialisms.
        if token[0].isupper():
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


def _add_capped_score(
    ctx: PipelineContext,
    score: str,
    raw_count: int,
    max_add: int,
    source: str,
    detail: dict[str, Any],
) -> None:
    if raw_count <= 0:
        return
    amount = min(raw_count, max_add)
    if score == "ai":
        ctx.score.ai_score += amount
    elif score == "human":
        ctx.score.human_score += amount
    elif score == "garbage":
        ctx.score.garbage_score += amount
    else:
        raise ValueError(f"Unsupported score type: {score}")
    _record_score_contribution(ctx, score, amount, source, detail)


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
