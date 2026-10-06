"""Wspólny interfejs modeli wizyjnych i typy ich odpowiedzi."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from signum.core.models import SignatureKind


class AIError(Exception):
    """Błąd warstwy AI (bazowy)."""


class AIConnectionError(AIError):
    """Nie można połączyć się z usługą AI — przerywa całą partię plików."""


class AIResponseError(AIError):
    """Usługa odpowiedziała, ale odpowiedź jest błędna/nieparsowalna."""


@dataclass(frozen=True, slots=True)
class VisualSignature:
    """Podpis wykryty wizyjnie na stronie przez model."""

    kind: SignatureKind
    confidence: int  # 0-100
    box_2d: tuple[int, int, int, int] | None  # [ymin, xmin, ymax, xmax] w skali 0-1000
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PageAnalysis:
    """Wynik analizy jednej strony przez model wizyjny."""

    description: str  # kilkuwyrazowy opis dokumentu (może być pusty)
    signatures: tuple[VisualSignature, ...]
    signature_probability: float | None = None  # P(widocznego podpisu/parafki) tej strony


class VisionModel(ABC):
    """Model wizyjny analizujący obraz strony dokumentu.

    Dostawcy generatywni implementują transport (:meth:`_generate`) i korzystają
    ze wspólnego parsera. Dostawcy decyzji nadpisują :meth:`analyze_page`,
    zwracając ten sam typ wyniku bez generowania tekstu.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Czytelna nazwa, np. ``Ollama: gemma4:12b`` — trafia do raportu."""

    @abstractmethod
    def _generate(self, image_jpeg: bytes, prompt: str) -> str:
        """Wysyła obraz + prompt, zwraca surowy tekst odpowiedzi modelu."""

    @abstractmethod
    def check_connection(self) -> str:
        """Sprawdza łączność i dostępność modelu.

        Zwraca komunikat dla użytkownika albo rzuca :class:`AIError`.
        """

    def analyze_page(self, image_jpeg: bytes, prompt: str | None = None) -> PageAnalysis:
        """Analizuje stronę: opis dokumentu + podpisy widoczne na obrazie.

        ``prompt`` pozwala nadpisać domyślny prompt strony (np. część
        merytoryczną edytowaną w ustawieniach programu).
        """
        # Import lokalny — parsing importuje typy z tego modułu (cykl importów).
        from signum.ai.parsing import parse_page_analysis  # noqa: PLC0415
        from signum.ai.prompts import PAGE_PROMPT  # noqa: PLC0415

        raw = self._generate(image_jpeg, prompt or PAGE_PROMPT)
        return parse_page_analysis(raw)

    def stop_local(self) -> str:
        """Zwalnia pamięć lokalnego modelu, jeśli dostawca obsługuje zarządzanie."""
        raise AIResponseError("Ten dostawca nie obsługuje zatrzymywania lokalnego modelu.")

    def release_resources(self) -> None:
        """Po partii dostawca może zwolnić własny lokalny runtime."""
        return

    def analyze_image(
        self,
        image: Image.Image,
        max_side: int,
        prompt: str | None = None,
        check_cancelled: Callable[[], None] | None = None,
    ) -> PageAnalysis:
        """Analiza obrazu roboczego, zanim zostanie zmniejszony dla pojedynczego widoku."""
        from signum.core.rendering import to_model_jpeg  # noqa: PLC0415

        if check_cancelled:
            check_cancelled()
        return self.analyze_page(to_model_jpeg(image, max_side), prompt)
