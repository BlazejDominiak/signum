"""Threshold decisions and human review based on numeric model outputs."""
from __future__ import annotations

import math
from typing import Any

MAX_CLASSIFICATION_LABELS = 3


def select_labels(
    scores: dict[str, float], threshold: float, limit: int = MAX_CLASSIFICATION_LABELS,
) -> list[str]:
    """Highest qualifying scores first; category IDs break ties deterministically."""
    return sorted(
        (key for key, score in scores.items() if score >= threshold),
        key=lambda key: (-scores[key], key),
    )[:limit]


def uncertain_labels(
    scores: dict[str, float], threshold: float, margin: float,
    limit: int = MAX_CLASSIFICATION_LABELS,
) -> list[str]:
    selected = select_labels(scores, threshold, limit)
    return [
        key for key in scores
        if (key in selected or len(selected) < limit)
        and near_threshold(scores[key], threshold, margin)
    ]


def probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Brak poprawnego wyniku modelu w zakresie 0–1.")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Wynik modelu musi być skończoną liczbą w zakresie 0–1.")
    return float(value)


def near_threshold(score: float, threshold: float, margin: float) -> bool:
    """Inclusive band on either side; tolerate only floating point rounding."""
    distance = abs(probability(score) - probability(threshold))
    margin = probability(margin)
    return distance <= margin or math.isclose(distance, margin, rel_tol=0, abs_tol=1e-12)


def review_reason(label: str, score: float, threshold: float, margin: float) -> str:
    return (
        f"HITL — sprawdź: {label}; wynik {score:.3f}, próg {threshold:.3f}, "
        f"margines ±{margin:.3f}."
    )


def label_questions(question: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Independent yes/no scores, never a softmax over competing labels."""
    catalog = "\n".join(question["criteria"].values())
    return {
        key: {
            "type": "noul",
            "instructions": (
                question["instructions"]
                + "\nAvailable categories:\n" + catalog
                + "\nEvaluate this label independently. Other labels may also apply. "
                "The document belongs to this category: " + description
            ),
        }
        for key, description in question["criteria"].items()
    }
