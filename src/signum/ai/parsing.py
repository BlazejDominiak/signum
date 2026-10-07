"""Odporne parsowanie odpowiedzi modeli wizyjnych.

Nawet ze structured outputs modele potrafią dokleić śmieci po JSON-ie
(zaobserwowane na gemma4:12b: poprawny obiekt + ``<|tool_response>``),
dlatego zawsze wycinamy pierwszy zbalansowany obiekt JSON z tekstu.
Niepoprawne wpisy podpisów pomijamy pojedynczo — jeden zły element nie
unieważnia całej strony. Brak listy lub lista wyłącznie błędnych wpisów
powoduje błąd odpowiedzi, aby nie uznać jej za potwierdzenie braku podpisów.
"""

from __future__ import annotations

import json
import math
from typing import Any

from signum.ai.base import AIResponseError, PageAnalysis, VisualSignature
from signum.core.models import SignatureKind

_VISUAL_KINDS = {
    "handwritten": SignatureKind.HANDWRITTEN,
    "initials": SignatureKind.INITIALS,
    "stamp": SignatureKind.STAMP,
    # Spotykane synonimy, gdy model nie trzyma się enuma:
    "signature": SignatureKind.HANDWRITTEN,
    "seal": SignatureKind.STAMP,
}

MAX_DESCRIPTION_LEN = 120
BOX_SCALE = 1000


def extract_first_json_object(text: str) -> dict[str, Any]:
    """Zwraca pierwszy zbalansowany obiekt JSON znaleziony w tekście.

    Ignoruje nawiasy klamrowe wewnątrz łańcuchów JSON. Rzuca
    :class:`AIResponseError`, gdy tekst nie zawiera poprawnego obiektu.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            char = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break  # spróbuj od kolejnego "{"
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = text.find("{", start + 1)
    raise AIResponseError("Odpowiedź modelu nie zawiera poprawnego obiektu JSON")


def parse_page_analysis(raw: str) -> PageAnalysis:
    """Parsuje surową odpowiedź modelu do :class:`PageAnalysis`."""
    data = extract_first_json_object(raw)
    description = str(data.get("description") or "").strip()[:MAX_DESCRIPTION_LEN]

    signatures: list[VisualSignature] = []
    raw_signatures = data.get("signatures")
    if not isinstance(raw_signatures, list):
        raise AIResponseError("Odpowiedź modelu nie zawiera listy signatures")
    for entry in raw_signatures:
        parsed = _parse_signature(entry)
        if parsed is not None:
            signatures.append(parsed)
    if raw_signatures and not signatures:
        raise AIResponseError("Lista signatures nie zawiera poprawnych wpisów")
    return PageAnalysis(description=description, signatures=tuple(signatures))


def _parse_signature(entry: Any) -> VisualSignature | None:
    if not isinstance(entry, dict):
        return None
    kind = _VISUAL_KINDS.get(str(entry.get("type", "")).strip().lower())
    if kind is None:
        return None
    return VisualSignature(
        kind=kind,
        confidence=_clamp_confidence(entry.get("confidence")),
        box_2d=_parse_box(entry.get("box_2d")),
    )


def _clamp_confidence(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 50  # model nie podał pewności — wartość neutralna
    if not math.isfinite(number):
        return 50
    if 0 < number <= 1:  # model podał ułamek zamiast procentów
        number *= 100
    return max(0, min(100, round(number)))


def _parse_box(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        numbers = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(number) for number in numbers):
        return None
    ymin, xmin, ymax, xmax = (round(number) for number in numbers)
    coords = (ymin, xmin, ymax, xmax)
    if any(not 0 <= c <= BOX_SCALE for c in coords):
        return None
    if ymax <= ymin or xmax <= xmin:
        return None
    return coords
