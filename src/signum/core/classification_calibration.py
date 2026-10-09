"""Load measured decision policies only for the exact evaluated question and model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from signum.ai.model_profiles import ModelProfile
from signum.core.classification import ClassificationBatch, apply_classification, make_question
from signum.core.decision import MAX_CLASSIFICATION_LABELS, label_questions


def question_identity(question: dict[str, Any]) -> str:
    payload = json.dumps(label_questions(question), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


@lru_cache(maxsize=8)
def _hash_files(files: tuple[tuple[str, str, int, int], ...]) -> str:
    digest = hashlib.sha256()
    for name, filename, _size, _mtime in files:
        digest.update(name.encode())
        with Path(filename).open("rb") as handle:
            digest.update(hashlib.file_digest(handle, "sha256").digest())
    return digest.hexdigest()


def local_identity(model_dir: str, runtime: str) -> str:
    files = []
    for prefix, base, patterns in (
        ("model", Path(model_dir), ("*.json", "*.safetensors")),
        ("runtime", Path(runtime), ("**/*.py",)),
    ):
        if not base.is_dir():
            return ""
        paths = sorted(
            {
                p
                for pattern in patterns
                for p in base.glob(pattern)
                if p.is_file() and "__pycache__" not in p.parts
            }
        )
        if not paths:
            return ""
        for path in paths:
            stat = path.stat()
            files.append(
                (
                    prefix + "/" + path.relative_to(base).as_posix(),
                    str(path),
                    stat.st_size,
                    stat.st_mtime_ns,
                )
            )
    return _hash_files(tuple(files))


def policy_for(profile: ModelProfile, question: dict[str, Any]) -> dict[str, Any]:
    source = resources.files("signum.core") / "classification_profiles.json"
    profiles = json.loads(source.read_text(encoding="utf-8"))
    question_sha = question_identity(question)
    for policy in profiles:
        if (policy["question_sha256"] != question_sha
                or policy.get("max_labels") != MAX_CLASSIFICATION_LABELS):
            continue
        if profile.provider == "jevk5" and policy["model"] == "jevk5":
            if local_identity(profile.model_dir, profile.runtime) == policy["local_identity"]:
                return dict(policy)
        elif (
            profile.provider == "api"
            and profile.api_format == "decisions"
            and profile.url.rstrip("/") == "https://api.venice.ai/api/v1"
            and profile.model == "jev-latest"
            and policy["model"] == "venice"
        ) or (
            profile.provider == "ollama" and profile.local
            and policy["model"] == "gemma"
            and profile.model == policy.get("model_name")
            and policy.get("score_source") == "declared"
        ):
            return dict(policy)
    return {}


def refresh_review_policy(batch: ClassificationBatch, profiles: list[ModelProfile]) -> int:
    """Refresh obsolete HITL flags without changing labels or reviewed decisions."""
    source = resources.files("signum.core") / "classification_profiles.json"
    bundled = json.loads(source.read_text(encoding="utf-8"))
    obsolete_ids = {
        old for policy in bundled for old in policy.get("replaces_review_profiles", [])
    }
    candidates = [
        row for row in batch.rows
        if row.category_source == "model" and not row.error and row.label_scores
        and row.calibration_id in obsolete_ids
    ]
    if not candidates:
        return 0
    try:
        question = make_question(batch.categories, batch.instructions)
    except ValueError:
        return 0
    names = [name.strip() for name, _ in batch.categories if name.strip()]
    labels = {f"c{i + 1:02d}": name for i, name in enumerate(names)}
    policies = {}
    for profile in profiles:
        if not any(row.model == profile.id for row in candidates):
            continue
        try:
            policies[profile.id] = policy_for(profile, question)
        except (OSError, ValueError):
            # An unavailable runtime cannot invalidate or erase a saved result.
            continue
    updated = 0
    for row in candidates:
        policy = policies.get(row.model, {})
        if (row.calibration_id not in policy.get("replaces_review_profiles", [])
                or row.threshold != policy.get("threshold")
                or set(row.label_scores) != set(labels.values())):
            continue
        refreshed = replace(
            row, hitl_margin=policy["hitl_margin"], calibration_id=policy["id"],
            calibration_warning=policy.get("review_reason", ""),
            review_labels=[labels[key] for key in policy.get("review_labels", [])],
        )
        try:
            apply_classification(
                refreshed, {"label_scores": {key: row.label_scores[name]
                                             for key, name in labels.items()},
                            "score_source": row.score_source or "decision"}, labels,
            )
        except ValueError:
            continue
        if set(refreshed.selected_categories) != set(row.selected_categories):
            continue
        row.hitl_margin = refreshed.hitl_margin
        row.calibration_id = refreshed.calibration_id
        row.calibration_warning = refreshed.calibration_warning
        row.review_labels = refreshed.review_labels
        row.review_reasons = refreshed.review_reasons
        row.hitl = refreshed.hitl
        updated += 1
    return updated
