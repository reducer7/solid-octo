from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing configuration file: {path}")

    with path.open("r", encoding="utf-8") as handle:
        parsed = yaml.safe_load(handle) or {}

    if not isinstance(parsed, dict):
        raise ConfigError(f"Configuration at {path} must be a YAML object")

    return parsed


def load_engine_config(project_root: Path) -> dict[str, Any]:
    root_cfg = _load_yaml(project_root / "config.yaml")
    similar_cfg = _load_yaml(project_root / "backend" / "tests" / "similarity" / "similar.yaml")
    garbage_cfg = _load_yaml(project_root / "backend" / "tests" / "garbage" / "garbage.yaml")
    construction_cfg = _load_yaml(
        project_root / "backend" / "tests" / "construction" / "construction.yaml"
    )
    ai_cfg = _load_yaml(project_root / "backend" / "tests" / "ai" / "ai_tests.yaml")
    human_cfg = _load_yaml(project_root / "backend" / "tests" / "human" / "human_tests.yaml")
    report_cfg = _load_yaml(project_root / "backend" / "reporter" / "report.yaml")

    _validate_root(root_cfg)
    _validate_similarity(similar_cfg)
    _validate_garbage(garbage_cfg)
    _validate_construction(construction_cfg)
    _validate_ai_detector(ai_cfg)
    _validate_human_detector(human_cfg)
    _validate_report(report_cfg)

    return {
        "root": root_cfg,
        "similarity": similar_cfg["similarity"],
        "garbage": garbage_cfg["garbage"],
        "construction": construction_cfg["construction"],
        "ai_detector": ai_cfg["ai_detector"],
        "human_detector": human_cfg["human_detector"],
        "report": report_cfg["report"],
    }


def resolve_from_project(project_root: Path, rel_path: str) -> Path:
    return (project_root / rel_path).resolve()


def _require(cfg: dict[str, Any], key: str, where: str) -> Any:
    if key not in cfg:
        raise ConfigError(f"Missing key '{key}' in {where}")
    return cfg[key]


def _validate_root(cfg: dict[str, Any]) -> None:
    app = _require(cfg, "app", "config.yaml")
    redis = _require(cfg, "redis", "config.yaml")
    fuzz = _require(cfg, "fuzz", "config.yaml")
    ui = _require(cfg, "ui", "config.yaml")

    for key in ("max_text_length", "simhash_bits", "scoring_max", "schema_version", "require_captcha"):
        _require(app, key, "config.yaml.app")

    for key in ("enabled", "url", "similarity_index_key", "entry_key_prefix", "fallback_bucket_key"):
        _require(redis, key, "config.yaml.redis")

    for key in ("enabled", "max_jitter", "bucket_hours"):
        _require(fuzz, key, "config.yaml.fuzz")

    _require(ui, "progress_display_ms", "config.yaml.ui")


def _validate_similarity(cfg: dict[str, Any]) -> None:
    similarity = _require(cfg, "similarity", "similar.yaml")
    for key in ("hamming_max_distance", "require_exact_hamming_check", "use_redisbloom", "use_fallback_search", "lsh"):
        _require(similarity, key, "similar.yaml.similarity")


def _validate_garbage(cfg: dict[str, Any]) -> None:
    garbage = _require(cfg, "garbage", "garbage.yaml")
    for key in ("entropy", "repeated_char_density", "non_printable_density", "unicode_outliers", "word_salad", "bigram"):
        _require(garbage, key, "garbage.yaml.garbage")


def _validate_construction(cfg: dict[str, Any]) -> None:
    construction = _require(cfg, "construction", "construction.yaml")
    for key in (
        "model",
        "semantic_coherence",
        "topic_persistence",
        "embedding_variance",
        "marker_clause",
        "semantic_marker",
        "marker_spiral",
    ):
        _require(construction, key, "construction.yaml.construction")


def _validate_ai_detector(cfg: dict[str, Any]) -> None:
    ai = _require(cfg, "ai_detector", "ai_tests.yaml")
    for key in (
        "key_markers",
        "grammar",
        "constructed_sentences",
        "perfect_parallelism",
        "balance_hedges",
        "over_explanation",
        "no_personal_experience",
        "ai_connectors",
        "overused_intensifiers",
        "list_introductions",
    ):
        _require(ai, key, "ai_tests.yaml.ai_detector")


def _validate_human_detector(cfg: dict[str, Any]) -> None:
    human = _require(cfg, "human_detector", "human_tests.yaml")
    for key in (
        "key_markers",
        "grammar",
        "micro_hesitation",
        "rhythm",
        "grounded_novelty",
        "local_contradictions",
        "temporal_drift",
        "spelling",
    ):
        _require(human, key, "human_tests.yaml.human_detector")


def _validate_report(cfg: dict[str, Any]) -> None:
    report = _require(cfg, "report", "report.yaml")
    for key in ("include_novel_flag", "include_reuse_flag", "fuzz_scores", "hide_marker_details"):
        _require(report, key, "report.yaml.report")
