from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from backend.common.models import PipelineContext

# ---- lazy model cache -------------------------------------------------------

_EMBEDDING_MODEL_CACHE: dict[str, Any] = {}
_NLP_CACHE: dict[str, Any] = {}


def _get_embedding_model(name: str) -> Any:
    if name not in _EMBEDDING_MODEL_CACHE:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        _EMBEDDING_MODEL_CACHE[name] = SentenceTransformer(name)
    return _EMBEDDING_MODEL_CACHE[name]


def _get_nlp(name: str) -> Any:
    if name not in _NLP_CACHE:
        import spacy  # noqa: PLC0415
        _NLP_CACHE[name] = spacy.load(name)
    return _NLP_CACHE[name]


# ---- public entry point -----------------------------------------------------

def run_construction_pass(
    ctx: PipelineContext,
    construction_cfg: dict[str, Any],
    max_score: int,
    project_root: Path | None = None,
) -> None:
    model_cfg = construction_cfg["model"]
    coherence_cfg = construction_cfg["semantic_coherence"]
    persistence_cfg = construction_cfg["topic_persistence"]
    variance_cfg = construction_cfg["embedding_variance"]
    marker_clause_cfg = construction_cfg["marker_clause"]
    semantic_marker_cfg = construction_cfg["semantic_marker"]
    spiral_cfg = construction_cfg["marker_spiral"]

    nlp = _get_nlp(str(model_cfg["spacy_model"]))
    emb_model = _get_embedding_model(str(model_cfg["embedding_model"]))

    sentences = _split_sentences(ctx.text, nlp)

    if len(sentences) < int(model_cfg["min_sentences"]):
        return

    embeddings = _embed(sentences, emb_model)

    _test_semantic_coherence(ctx, coherence_cfg, sentences, embeddings)
    _test_topic_persistence(ctx, persistence_cfg, sentences, embeddings)
    _test_embedding_variance(ctx, variance_cfg, sentences, embeddings)
    _test_marker_clause_structure(ctx, marker_clause_cfg, sentences, nlp)
    _test_semantic_marker_check(ctx, semantic_marker_cfg, sentences, nlp, emb_model)
    _test_marker_spiral(ctx, spiral_cfg, sentences)

    ctx.score.clamp(max_score)


# ---- test 1: semantic coherence ---------------------------------------------

def _test_semantic_coherence(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    sentences: list[str],
    embeddings: np.ndarray,
) -> None:
    if len(sentences) < 2:
        return

    low_threshold = float(cfg["low_threshold"])
    n_pairs = len(sentences) - 1
    low_pairs = sum(
        1
        for i in range(n_pairs)
        if _cosine_sim(embeddings[i], embeddings[i + 1]) < low_threshold
    )

    if low_pairs / n_pairs >= float(cfg["low_ratio"]):
        amount = int(cfg["add_garbage"])
        ctx.score.garbage_score += amount
        _record_score_contribution(
            ctx,
            score="garbage",
            amount=amount,
            source="pass3_semantic_coherence",
            detail={"low_pair_ratio": round(low_pairs / n_pairs, 4)},
        )


# ---- test 2: topic persistence ----------------------------------------------

def _test_topic_persistence(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    sentences: list[str],
    embeddings: np.ndarray,
) -> None:
    if len(sentences) < int(cfg["min_sentences"]):
        return

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normed = embeddings / (norms + 1e-9)

    clustering = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=float(cfg["cluster_distance_threshold"]),
    )
    labels = clustering.fit_predict(normed)
    n_clusters = len(set(labels))
    n_sentences = len(sentences)
    cluster_ratio = n_clusters / n_sentences

    detail = {
        "cluster_ratio": round(cluster_ratio, 4),
        "n_clusters": n_clusters,
        "n_sentences": n_sentences,
    }

    if cluster_ratio > float(cfg["high_ratio"]):
        amount = int(cfg["high_add_garbage"])
        ctx.score.garbage_score += amount
        _record_score_contribution(ctx, "garbage", amount, "pass3_topic_persistence_high", detail)
    elif cluster_ratio > float(cfg["mid_ratio"]):
        amount = int(cfg["mid_add_garbage"])
        ctx.score.garbage_score += amount
        _record_score_contribution(ctx, "garbage", amount, "pass3_topic_persistence_mid", detail)


# ---- test 3: embedding variance ---------------------------------------------

def _test_embedding_variance(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    sentences: list[str],
    embeddings: np.ndarray,
) -> None:
    if len(sentences) < 2:
        return

    mean_emb = embeddings.mean(axis=0)
    dists = np.array(
        [1.0 - _cosine_sim(embeddings[i], mean_emb) for i in range(len(sentences))]
    )
    variance = float(dists.mean())
    detail = {"embedding_variance": round(variance, 6)}

    if variance < float(cfg["very_low_lt"]):
        amount = int(cfg["very_low_add_ai"])
        ctx.score.ai_score += amount
        _record_score_contribution(ctx, "ai", amount, "pass3_embedding_variance_very_low", detail)
    elif variance < float(cfg["mod_low_lt"]):
        amount = int(cfg["mod_low_add_ai"])
        ctx.score.ai_score += amount
        _record_score_contribution(ctx, "ai", amount, "pass3_embedding_variance_mod_low", detail)
    elif variance < float(cfg["human_lt"]):
        amount = int(cfg["human_add_human"])
        ctx.score.human_score += amount
        _record_score_contribution(ctx, "human", amount, "pass3_embedding_variance_human", detail)
    elif variance < float(cfg["mod_high_lt"]):
        h_amount = int(cfg["mod_high_add_human"])
        g_amount = int(cfg["mod_high_add_garbage"])
        ctx.score.human_score += h_amount
        ctx.score.garbage_score += g_amount
        _record_score_contribution(ctx, "human", h_amount, "pass3_embedding_variance_mod_high", detail)
        _record_score_contribution(ctx, "garbage", g_amount, "pass3_embedding_variance_mod_high", detail)
    else:
        amount = int(cfg["very_high_add_garbage"])
        ctx.score.garbage_score += amount
        _record_score_contribution(ctx, "garbage", amount, "pass3_embedding_variance_very_high", detail)


# ---- test 4: marker clause structure ----------------------------------------

def _test_marker_clause_structure(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    sentences: list[str],
    nlp: Any,
) -> None:
    markers = [m.lower() for m in cfg["markers"]]
    add_ai = int(cfg["add_ai"])
    min_clause_words = int(cfg.get("min_clause_words", 3))

    for idx, sent in enumerate(sentences):
        doc = nlp(sent)
        alpha_set = {tok.lower_ for tok in doc if tok.is_alpha}

        for marker in markers:
            if marker not in alpha_set:
                continue

            marker_tok = next(
                (tok for tok in doc if tok.lower_ == marker and tok.is_alpha), None
            )
            if marker_tok is None:
                continue

            if _is_marker_misuse(doc, marker_tok, marker, sent, min_clause_words):
                ctx.score.ai_score += add_ai
                _record_score_contribution(
                    ctx,
                    score="ai",
                    amount=add_ai,
                    source="pass3_marker_clause_misuse",
                    detail={"marker": marker, "sentence_idx": idx},
                )


def _is_marker_misuse(
    doc: Any,
    marker_tok: Any,
    marker: str,
    sent: str,
    min_clause_words: int,
) -> bool:
    before = sent[: marker_tok.idx].strip().rstrip(",;:")
    after = sent[marker_tok.idx + len(marker_tok.text) :].strip().lstrip(",; ")

    before_words = [w for w in re.split(r"\W+", before) if w.isalpha()]
    after_words = [w for w in re.split(r"\W+", after) if w.isalpha()]

    # The clause following the marker must carry enough words for all marker types.
    if len(after_words) < min_clause_words:
        return True

    # "because" and "therefore" must not open a sentence; a main clause must precede.
    if marker in ("because", "therefore") and len(before_words) < min_clause_words:
        return True

    # For subordinating conjunctions, verify spaCy assigns the correct dep role.
    if marker in ("because", "although") and marker_tok.dep_ not in ("mark", "advmod"):
        return True

    return False


# ---- test 5: semantic marker check ------------------------------------------

def _test_semantic_marker_check(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    sentences: list[str],
    nlp: Any,
    emb_model: Any,
) -> None:
    markers = list(cfg.keys())

    # Collect all valid clause pairs before encoding to allow a single batch call.
    pending: list[tuple[str, str, str]] = []  # (marker, clause_a, clause_b)

    for idx, sent in enumerate(sentences):
        words_lower = set(re.findall(r"\b[a-z]+\b", sent.lower()))

        for marker in markers:
            if marker not in words_lower:
                continue

            clause_a, clause_b = _split_at_marker(sent, marker, idx, sentences, nlp)
            if clause_a is None or clause_b is None:
                continue
            if len(clause_a.split()) < 3 or len(clause_b.split()) < 3:
                continue

            pending.append((marker, clause_a, clause_b))

    if not pending:
        return

    # Batch-encode all clauses in one call.
    all_texts = [text for _, ca, cb in pending for text in (ca, cb)]
    all_embs = emb_model.encode(all_texts, convert_to_numpy=True)

    for pair_idx, (marker, _ca, _cb) in enumerate(pending):
        emb_a = all_embs[pair_idx * 2]
        emb_b = all_embs[pair_idx * 2 + 1]
        sim = _cosine_sim(emb_a, emb_b)
        _apply_marker_sim_thresholds(ctx, marker, cfg[marker], sim)


def _split_at_marker(
    sent: str,
    marker: str,
    sentence_idx: int,
    sentences: list[str],
    nlp: Any,
) -> tuple[str | None, str | None]:
    doc = nlp(sent)
    marker_tok = next(
        (tok for tok in doc if tok.lower_ == marker and tok.is_alpha), None
    )
    if marker_tok is None:
        return None, None

    clause_a = sent[: marker_tok.idx].strip().rstrip(",;:").strip()
    clause_b = sent[marker_tok.idx + len(marker_tok.text) :].strip().lstrip(",; ").strip()

    # "however" fallback: use the previous sentence as clause A when nothing precedes the marker.
    if marker == "however" and len(clause_a.split()) < 3:
        if sentence_idx > 0:
            clause_a = sentences[sentence_idx - 1]

    return clause_a or None, clause_b or None


def _apply_marker_sim_thresholds(
    ctx: PipelineContext,
    marker: str,
    cfg: dict[str, Any],
    sim: float,
) -> None:
    detail = {"cosine_sim": round(sim, 4)}

    if marker == "because":
        if sim < float(cfg["low_lt"]):
            _add_scores(ctx, [("ai", int(cfg["low_add_ai"])), ("garbage", int(cfg["low_add_garbage"]))],
                        "pass3_semantic_because_low", detail)
        elif sim < float(cfg["mid_lt"]):
            _add_scores(ctx, [("ai", int(cfg["mid_add_ai"])), ("garbage", int(cfg["mid_add_garbage"]))],
                        "pass3_semantic_because_mid", detail)
        else:
            _add_scores(ctx, [("human", int(cfg["high_add_human"])), ("ai", int(cfg["high_add_ai"]))],
                        "pass3_semantic_because_high", detail)

    elif marker == "however":
        if sim < float(cfg["very_low_lt"]):
            _add_scores(ctx, [("ai", int(cfg["very_low_add_ai"])), ("garbage", int(cfg["very_low_add_garbage"]))],
                        "pass3_semantic_however_very_low", detail)
        elif sim < float(cfg["low_lt"]):
            _add_scores(ctx, [("ai", int(cfg["low_add_ai"])), ("garbage", int(cfg["low_add_garbage"]))],
                        "pass3_semantic_however_low", detail)
        elif sim < float(cfg["mid_lt"]):
            _add_scores(ctx, [("ai", int(cfg["mid_add_ai"])), ("human", int(cfg["mid_add_human"]))],
                        "pass3_semantic_however_mid", detail)
        elif sim >= float(cfg["high_gte"]):
            _add_scores(ctx, [("garbage", int(cfg["high_add_garbage"])), ("ai", int(cfg["high_add_ai"]))],
                        "pass3_semantic_however_high", detail)
        # 0.6–0.8 gap: no rule per spec.

    elif marker == "therefore":
        if sim > float(cfg["high_gt"]):
            _add_scores(ctx, [("ai", int(cfg["high_add_ai"])), ("human", int(cfg["high_add_human"]))],
                        "pass3_semantic_therefore_high", detail)
        else:
            _add_scores(ctx, [("garbage", int(cfg["low_add_garbage"])), ("ai", int(cfg["low_add_ai"]))],
                        "pass3_semantic_therefore_low", detail)

    elif marker == "although":
        if sim < float(cfg["low_lt"]):
            _add_scores(ctx, [("ai", int(cfg["low_add_ai"])), ("garbage", int(cfg["low_add_garbage"]))],
                        "pass3_semantic_although_low", detail)
        elif sim < float(cfg["mid_lt"]):
            _add_scores(ctx, [("human", int(cfg["mid_add_human"])), ("ai", int(cfg["mid_add_ai"]))],
                        "pass3_semantic_although_mid", detail)
        else:
            _add_scores(ctx, [("garbage", int(cfg["high_add_garbage"])), ("ai", int(cfg["high_add_ai"]))],
                        "pass3_semantic_although_high", detail)


# ---- test 6: marker spirals -------------------------------------------------

def _test_marker_spiral(
    ctx: PipelineContext,
    cfg: dict[str, Any],
    sentences: list[str],
) -> None:
    markers = {m.lower() for m in cfg["markers"]}
    n_sentences = len(sentences)
    if n_sentences == 0:
        return

    total_markers = 0
    unique_markers_found: set[str] = set()

    for idx, sent in enumerate(sentences):
        words = set(re.findall(r"\b[a-z]+\b", sent.lower()))
        found = markers & words
        total_markers += len(found)
        unique_markers_found |= found

        if len(found) >= 2:
            amount = int(cfg["multi_marker_per_sentence_add_ai"])
            ctx.score.ai_score += amount
            _record_score_contribution(
                ctx,
                score="ai",
                amount=amount,
                source="pass3_marker_spiral_multi_sentence",
                detail={"sentence_idx": idx, "markers_found": sorted(found)},
            )

    if total_markers / n_sentences > float(cfg["freq_per_sentence_gt"]):
        amount = int(cfg["freq_add_ai"])
        ctx.score.ai_score += amount
        _record_score_contribution(
            ctx,
            score="ai",
            amount=amount,
            source="pass3_marker_spiral_freq",
            detail={
                "total_markers": total_markers,
                "n_sentences": n_sentences,
                "freq_per_sentence": round(total_markers / n_sentences, 4),
            },
        )

    if len(unique_markers_found) >= int(cfg["multi_type_threshold"]):
        amount = int(cfg["multi_type_add_ai"])
        ctx.score.ai_score += amount
        _record_score_contribution(
            ctx,
            score="ai",
            amount=amount,
            source="pass3_marker_spiral_multi_type",
            detail={"unique_markers": sorted(unique_markers_found)},
        )


# ---- shared helpers ---------------------------------------------------------

def _split_sentences(text: str, nlp: Any) -> list[str]:
    doc = nlp(text)
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


def _embed(sentences: list[str], model: Any) -> np.ndarray:
    return model.encode(sentences, convert_to_numpy=True)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-9:
        return 0.0
    return float(np.dot(a, b) / denom)


def _add_scores(
    ctx: PipelineContext,
    score_pairs: list[tuple[str, int]],
    source: str,
    detail: dict[str, Any],
) -> None:
    for score_name, amount in score_pairs:
        if amount <= 0:
            continue
        if score_name == "ai":
            ctx.score.ai_score += amount
        elif score_name == "human":
            ctx.score.human_score += amount
        elif score_name == "garbage":
            ctx.score.garbage_score += amount
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


def _terminal(ctx: PipelineContext, reason: str, max_score: int) -> None:
    ctx.skip_reason = reason
    ctx.terminal = True
    ctx.score.ai_score = 0
    ctx.score.human_score = 0
    ctx.score_contributions = []
    ctx.score.clamp(max_score)
