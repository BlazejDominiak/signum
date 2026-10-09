"""Frozen five-view signature classifier validated on the closed 120-page corpus."""

from __future__ import annotations

import math
from typing import Any

from PIL import Image

from signum.ai.base import AIResponseError, PageAnalysis, VisualSignature
from signum.core.decision import near_threshold, review_reason
from signum.core.models import SignatureKind

THRESHOLD = 0.535
INTERCEPT = -1.2752369584469005
SLOPE = 4.525887113758848
MEAN_KEYS = ("handwritten", "execution", "pen_strokes", "choice")
QUALITY_QUESTIONS: dict[str, Any] = {
    "handwritten": {
        "type": "noul",
        "instructions": "At least one handwritten signature is visible on this page.",
    },
    "initials": {
        "type": "noul",
        "instructions": "At least one handwritten initial or short signing mark is visible.",
    },
    "execution": {
        "type": "noul",
        "instructions": "The document visibly contains an actual handwritten "
        "signature used to sign it, not just a printed name or an "
        "empty signing line.",
    },
    "pen_strokes": {
        "type": "noul",
        "instructions": "At least one handwritten autograph made of pen strokes "
        "is visible on this document page.",
    },
    "absence": {
        "type": "noul",
        "instructions": "No handwritten signature is visible on this document page.",
    },
    "notes": {
        "type": "noul",
        "instructions": "The only handwriting visible is ordinary notes, numbers, "
        "dates or corrections, and not a signature or signing "
        "initial.",
    },
    "empty": {
        "type": "noul",
        "instructions": "All signing fields on this page are empty and there is no "
        "handwritten signature anywhere on this page.",
    },
    "stamp": {
        "type": "noul",
        "instructions": "At least one ink impression of a stamped seal is visible.",
    },
    "binary": {
        "type": "choice",
        "instructions": "Does the image contain at least one visible handwritten "
        "signature or handwritten signing initial?",
        "criteria": {
            "present": "Visible pen strokes of a handwritten signature or "
            "signing initial, including a scanned signature "
            "image.",
            "absent": "No visible handwritten signature or signing initial; "
            "printed names, empty lines, ordinary notes and "
            "stamps alone do not count.",
        },
    },
}


def signature_views(image: Image.Image) -> list[Image.Image]:
    w, h = image.size
    return [
        image,
        image.crop((0, 0, int(w * 0.6), int(h * 0.6))),
        image.crop((int(w * 0.4), 0, w, int(h * 0.6))),
        image.crop((0, int(h * 0.4), int(w * 0.6), h)),
        image.crop((int(w * 0.4), int(h * 0.4), w, h)),
    ]


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AIResponseError("Jev zwrócił niepoprawną ocenę obecności podpisu.")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise AIResponseError("Jev zwrócił ocenę poza zakresem 0–1.")
    return result


def _scores(response: dict[str, Any]) -> dict[str, float]:
    answers = response.get("answers")
    if not isinstance(answers, dict):
        raise AIResponseError("Brak odpowiedzi klasyfikatora podpisów Jev.")
    scores = {}
    for key in QUALITY_QUESTIONS:
        answer = answers.get(key)
        if not isinstance(answer, dict) or answer.get("type") != QUALITY_QUESTIONS[key]["type"]:
            raise AIResponseError(f"Brak poprawnej odpowiedzi Jev: {key}.")
        if key == "binary":
            probabilities = answer.get("probabilities")
            if not isinstance(probabilities, dict):
                raise AIResponseError("Brak prawdopodobieństw pytania binarnego Jev.")
            scores["choice"] = _probability(probabilities.get("present"))
            absent = _probability(probabilities.get("absent"))
            if abs(scores["choice"] + absent - 1) > 0.01:
                raise AIResponseError("Niespójne prawdopodobieństwa odpowiedzi Jev.")
        else:
            scores[key] = _probability(answer.get("noul"))
    return scores


def parse_signature_views(
    responses: list[dict[str, Any]], hitl_margin: float = 0.10,
) -> PageAnalysis:
    if len(responses) != 5:
        raise AIResponseError("Brak kompletu pięciu widoków Jev; wynik nie jest brakiem podpisu.")
    scores = [_scores(response) for response in responses]
    means = [sum(view[key] for key in MEAN_KEYS) / 4 for view in scores]
    best = max(range(5), key=lambda index: means[index])
    score = means[best]
    z = INTERCEPT + SLOPE * 4 * (score - 0.5)
    probability = 1 / (1 + math.exp(-max(-40, min(40, z))))
    signatures = []
    if score >= THRESHOLD:
        kind = (
            SignatureKind.INITIALS
            if scores[best]["initials"] > scores[best]["handwritten"]
            else SignatureKind.HANDWRITTEN
        )
        signatures.append(
            VisualSignature(
                kind,
                round(probability * 100),
                None,
            )
        )
    # Stamp is a separate, uncalibrated observation, not evidence of signing.
    if scores[0]["stamp"] >= 0.5:
        signatures.append(
            VisualSignature(
                SignatureKind.STAMP,
                round(scores[0]["stamp"] * 100),
                None,
            )
        )
    reasons = (
        (review_reason("obecność podpisu/parafki", score, THRESHOLD, hitl_margin),)
        if near_threshold(score, THRESHOLD, hitl_margin) else ()
    )
    return PageAnalysis("", tuple(signatures), probability, score, THRESHOLD, reasons)
