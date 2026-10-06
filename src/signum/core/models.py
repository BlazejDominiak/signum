"""Modele domenowe: rodzaje podpisów, znaleziska i wyniki analizy dokumentów."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class SignatureKind(StrEnum):
    """Rodzaj wykrytego podpisu."""

    HANDWRITTEN = "handwritten"
    INITIALS = "initials"
    STAMP = "stamp"
    DIGITAL = "digital"

    @property
    def label_pl(self) -> str:
        return _KIND_LABELS[self]


_KIND_LABELS = {
    SignatureKind.HANDWRITTEN: "podpis odręczny",
    SignatureKind.INITIALS: "parafka",
    SignatureKind.STAMP: "pieczątka",
    SignatureKind.DIGITAL: "podpis cyfrowy",
}


class DocumentStatus(StrEnum):
    """Stan przetwarzania pojedynczego dokumentu."""

    PENDING = "pending"
    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class SignatureFinding:
    """Pojedyncze znalezisko: jeden podpis/parafka/pieczątka/podpis cyfrowy.

    ``confidence`` to deklarowana przez model pewność 0–100. Dla podpisów
    cyfrowych wykrytych ze struktury PDF przyjmujemy 100 — obecność pola
    podpisu z wartością jest faktem strukturalnym, nie oceną wizualną
    (nie weryfikujemy kryptograficznej poprawności podpisu).
    """

    kind: SignatureKind
    page: int  # numer strony, 1-bazowy
    confidence: int  # 0-100
    crop_png: bytes | None = None  # wycinek podpisu do weryfikacji przez człowieka
    overview_jpeg: bytes | None = None  # miniatura strony z zaznaczonym znaleziskiem
    detail: str = ""  # np. rodzaj podpisu cyfrowego, podpisujący, data


@dataclass(slots=True)
class DocumentResult:
    """Wynik analizy jednego pliku."""

    path: Path
    status: DocumentStatus = DocumentStatus.PENDING
    title: str = ""  # kilkuwyrazowy opis nadany przez model
    findings: list[SignatureFinding] = field(default_factory=list)
    page_count: int = 0  # łączna liczba stron w dokumencie
    pages_analyzed: int = 0  # ile stron faktycznie przeanalizowano
    error: str | None = None
    duration_s: float = 0.0
    page_signature_probabilities: dict[int, float] = field(default_factory=dict)

    @property
    def is_signed(self) -> bool:
        return any(f.kind != SignatureKind.STAMP for f in self.findings)

    @property
    def kinds_summary(self) -> str:
        """Np. ``2× podpis odręczny, 1× pieczątka``."""
        counts: dict[SignatureKind, int] = {}
        for f in self.findings:
            counts[f.kind] = counts.get(f.kind, 0) + 1
        return ", ".join(f"{n}× {kind.label_pl}" for kind, n in counts.items())

    @property
    def max_confidence(self) -> int | None:
        if not self.findings:
            return None
        return max(f.confidence for f in self.findings)
