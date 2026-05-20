from __future__ import annotations

from typing import Any

from backend.common.models import PipelineContext, score_from_entry
from backend.common.simhash import hamming_distance, parse_simhash
from backend.database.redis_store import ScoreStore


def run_similarity_pass(
    ctx: PipelineContext,
    store: ScoreStore,
    similarity_cfg: dict[str, Any],
    redis_cfg: dict[str, Any],
) -> bool:
    threshold = int(similarity_cfg["hamming_max_distance"])
    use_redisbloom = bool(similarity_cfg["use_redisbloom"])
    use_fallback = bool(similarity_cfg["use_fallback_search"])
    lsh_cfg = similarity_cfg["lsh"]

    candidates = store.query_candidates(
        simhash_hex=ctx.computed_simhash_hex,
        index_key=redis_cfg["similarity_index_key"],
        fallback_key=redis_cfg["fallback_bucket_key"],
        use_redisbloom=use_redisbloom,
        use_fallback=use_fallback,
        lsh_bands=int(lsh_cfg["bands"]),
        lsh_bits=int(lsh_cfg["bits"]),
    )

    for candidate_hex in candidates:
        try:
            candidate_hash = parse_simhash(candidate_hex)
        except ValueError:
            continue

        if hamming_distance(ctx.computed_simhash, candidate_hash) > threshold:
            continue

        entry = store.get_entry(candidate_hex)
        if not entry:
            continue

        # Reusing prior scores here allows pass-2+ to be skipped for near duplicates.
        ctx.score = score_from_entry(entry)
        ctx.novel_text = False
        ctx.reused_result = True
        ctx.skip_reason = "pass1_similarity_reuse"
        ctx.terminal = True
        return True

    ctx.novel_text = True
    return False
