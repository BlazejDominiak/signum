"""Orkiestracja analizy: pojedynczy dokument oraz sekwencyjna partia plików.

Moduł jest całkowicie niezależny od GUI — postęp raportuje przez zwrotne
wywołania (callbacks), a anulowanie obsługuje przez :class:`CancelToken`.
Dzięki temu ten sam kod napędza GUI (wątek roboczy Qt) i tryb CLI.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from signum.ai.base import AIConnectionError, AIError, PageAnalysis, VisionModel
from signum.core.cropping import (
    crop_box_2d,
    crop_pdf_rect,
    overview_box_2d,
    overview_pdf_rect,
    to_jpeg_bytes,
    to_png_bytes,
)
from signum.core.digital import DigitalSignature, scan_digital_signatures
from signum.core.models import DocumentResult, DocumentStatus, SignatureFinding, SignatureKind
from signum.core.rendering import (
    DocumentReadError,
    PageImage,
    is_pdf,
    load_pages,
    render_pdf_page,
)

# Ile razy ponawiamy analizę strony po błędnej odpowiedzi modelu
# (błędy połączenia NIE są ponawiane — przerywają całą partię).
PAGE_RETRIES = 1


class CancelToken:
    """Bezpieczny wątkowo sygnał anulowania przekazywany w głąb pipeline'u."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class BatchCancelledError(Exception):
    """Przerwanie przetwarzania na życzenie użytkownika."""


@dataclass(slots=True)
class BatchResult:
    """Wynik przetworzenia partii plików."""

    results: list[DocumentResult] = field(default_factory=list)
    model_name: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    abort_error: str | None = None  # ustawione, gdy partię przerwał błąd połączenia

    @property
    def duration_s(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    @property
    def signed_count(self) -> int:
        return sum(1 for r in self.results if r.status == DocumentStatus.OK and r.is_signed)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.status == DocumentStatus.ERROR)


class DocumentAnalyzer:
    """Analizuje pojedynczy dokument: struktura PDF + strony przez model wizyjny."""

    def __init__(
        self,
        model: VisionModel,
        max_pages: int,
        image_max_side: int,
        prompt: str | None = None,
    ) -> None:
        self._model = model
        self._max_pages = max_pages
        self._image_max_side = image_max_side
        self._prompt = prompt  # None = domyślny prompt programu

    @property
    def model_name(self) -> str:
        return self._model.name

    def release_resources(self) -> None:
        self._model.release_resources()

    def analyze(self, path: Path, cancel: CancelToken) -> DocumentResult:
        """Pełna analiza jednego pliku.

        Błędy pliku (uszkodzony PDF, zła odpowiedź modelu po ponowieniu)
        kończą się wynikiem ``ERROR`` — partia idzie dalej. Wyjątki
        :class:`AIConnectionError` i :class:`BatchCancelledError` propagują wyżej.
        """
        result = DocumentResult(path=path)
        started = time.monotonic()
        try:
            self._analyze_into(result, path, cancel)
            result.status = DocumentStatus.OK
        except (BatchCancelledError, AIConnectionError):
            raise
        except (DocumentReadError, AIError, OSError) as exc:
            result.status = DocumentStatus.ERROR
            result.error = _safe_document_error(exc, path)
        finally:
            result.duration_s = time.monotonic() - started
        return result

    def _analyze_into(self, result: DocumentResult, path: Path, cancel: CancelToken) -> None:
        _raise_if_cancelled(cancel)
        pages, total = load_pages(path, self._max_pages)
        result.page_count = total

        digital_findings: list[SignatureFinding] = []
        if is_pdf(path):
            digital_findings = self._digital_findings(path, pages)

        for page in pages:
            _raise_if_cancelled(cancel)
            analysis = self._analyze_page_with_retry(page, cancel)
            if analysis.signature_probability is not None:
                result.page_signature_probabilities[page.number] = analysis.signature_probability
            if analysis.description and not result.title:
                result.title = analysis.description
            for sig in analysis.signatures:
                crop_png = None
                overview_jpeg = None
                if sig.box_2d is not None:
                    crop = crop_box_2d(page.image, sig.box_2d)
                    if crop is not None:
                        crop_png = to_png_bytes(crop)
                    overview = overview_box_2d(page.image, sig.box_2d)
                    if overview is not None:
                        overview_jpeg = to_jpeg_bytes(overview)
                result.findings.append(
                    SignatureFinding(
                        kind=sig.kind,
                        page=page.number,
                        confidence=sig.confidence,
                        crop_png=crop_png,
                        overview_jpeg=overview_jpeg,
                        detail=sig.detail,
                    )
                )
            result.pages_analyzed += 1

        result.findings.extend(digital_findings)
        if not result.title:
            result.title = path.stem

    def _analyze_page_with_retry(self, page: PageImage, cancel: CancelToken) -> PageAnalysis:
        last_error: AIError | None = None
        for _attempt in range(1 + PAGE_RETRIES):
            try:
                return self._model.analyze_image(
                    page.image,
                    self._image_max_side,
                    self._prompt,
                    check_cancelled=lambda: _raise_if_cancelled(cancel),
                )
            except AIConnectionError:
                raise
            except AIError as exc:
                last_error = exc
        raise last_error if last_error else AIError("Nieznany błąd modelu")

    def _digital_findings(
        self, path: Path, rendered_pages: list[PageImage]
    ) -> list[SignatureFinding]:
        scan = scan_digital_signatures(path)
        by_number = {page.number: page for page in rendered_pages}
        findings = []
        for sig in scan.signatures:
            crop_png, overview_jpeg = self._digital_images(path, sig, by_number)
            findings.append(
                SignatureFinding(
                    kind=SignatureKind.DIGITAL,
                    page=sig.page or 1,
                    confidence=100,  # obecność w strukturze PDF jest pewna
                    crop_png=crop_png,
                    overview_jpeg=overview_jpeg,
                    detail=sig.detail,
                )
            )
        return findings

    def _digital_images(
        self, path: Path, sig: DigitalSignature, rendered: dict[int, PageImage]
    ) -> tuple[bytes | None, bytes | None]:
        """Wycinek i miniatura widocznego widgetu podpisu cyfrowego (jeśli istnieje)."""
        if sig.page is None or sig.rect_pt is None:
            return None, None
        try:
            page = rendered.get(sig.page) or render_pdf_page(path, sig.page)
        except DocumentReadError:
            return None, None
        if page.page_size_pt is None:
            return None, None
        crop = crop_pdf_rect(page.image, sig.rect_pt, page.page_size_pt)
        overview = overview_pdf_rect(page.image, sig.rect_pt, page.page_size_pt)
        return (
            to_png_bytes(crop) if crop is not None else None,
            to_jpeg_bytes(overview) if overview is not None else None,
        )


ProgressCallback = Callable[[int, int, Path], None]
ResultCallback = Callable[[int, DocumentResult], None]


def run_batch(
    files: list[Path],
    analyzer: DocumentAnalyzer,
    cancel: CancelToken,
    on_file_start: ProgressCallback | None = None,
    on_file_done: ResultCallback | None = None,
) -> BatchResult:
    """Sekwencyjnie przetwarza listę plików (użytkownik może wrzucić ich ~1000).

    Zasady odporności:
    - błąd pojedynczego pliku → wynik ``ERROR``, partia idzie dalej,
    - błąd połączenia z AI → przerwanie partii (``abort_error``), bo każdy
      kolejny plik i tak by się nie powiódł,
    - anulowanie → pliki nierozpoczęte dostają status ``CANCELLED``.
    """
    batch = BatchResult(model_name=analyzer.model_name, started_at=time.time())
    for index, path in enumerate(files):
        if cancel.cancelled:
            batch.results.extend(
                DocumentResult(path=p, status=DocumentStatus.CANCELLED) for p in files[index:]
            )
            break
        if on_file_start is not None:
            on_file_start(index, len(files), path)
        try:
            result = analyzer.analyze(path, cancel)
        except BatchCancelledError:
            batch.results.extend(
                DocumentResult(path=p, status=DocumentStatus.CANCELLED) for p in files[index:]
            )
            break
        except AIConnectionError as exc:
            batch.abort_error = str(exc)
            batch.results.append(
                DocumentResult(path=path, status=DocumentStatus.ERROR, error=str(exc))
            )
            batch.results.extend(
                DocumentResult(path=p, status=DocumentStatus.CANCELLED) for p in files[index + 1 :]
            )
            break
        batch.results.append(result)
        if on_file_done is not None:
            on_file_done(index, result)
    batch.finished_at = time.time()
    return batch


def _raise_if_cancelled(cancel: CancelToken) -> None:
    if cancel.cancelled:
        raise BatchCancelledError


def _safe_document_error(exc: Exception, path: Path) -> str:
    """Nie pozwala bibliotekom umieścić pełnej ścieżki dokumentu w raporcie."""
    message = str(exc)
    for variant in {str(path), path.as_posix()}:
        message = message.replace(variant, path.name)
    return message
