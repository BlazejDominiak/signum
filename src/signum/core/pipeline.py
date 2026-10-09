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
    open_pages,
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
    analysis_settings: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    preparation_s: float = 0.0
    loading_s: float = 0.0
    inference_s: float = 0.0
    preflight_s: float = 0.0
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
        self.last_result: DocumentResult | None = None

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
        self.last_result = result
        started = time.monotonic()
        try:
            self._analyze_into(result, path, cancel)
            result.status = DocumentStatus.ERROR if result.error else DocumentStatus.OK
        except (BatchCancelledError, AIConnectionError):
            raise
        except (DocumentReadError, AIError, OSError) as exc:
            result.status = DocumentStatus.ERROR
            result.error = "; ".join(filter(None, (result.error, _safe_document_error(exc, path))))
        finally:
            result.duration_s = time.monotonic() - started
            result.preparation_s = max(
                0.0, result.duration_s - result.inference_s - result.loading_s
            )
        return result

    def _analyze_into(self, result: DocumentResult, path: Path, cancel: CancelToken) -> None:
        _raise_if_cancelled(cancel)
        with open_pages(path, self._max_pages) as (pages, total):
            result.page_count = total
            if is_pdf(path):
                self._digital_findings(path, result, cancel)
            for page in pages:
                _raise_if_cancelled(cancel)
                self._analyze_visual_page(result, page, cancel)
                _raise_if_cancelled(cancel)
        if not result.title:
            result.title = path.stem

    def _analyze_visual_page(
        self, result: DocumentResult, page: PageImage, cancel: CancelToken
    ) -> None:
        started = time.perf_counter()
        loading_before = self._model.loading_seconds
        requests_before = self._model.request_seconds
        try:
            analysis = self._analyze_page_with_retry(page, cancel)
        finally:
            duration = time.perf_counter() - started
            loading = min(duration, max(0.0, self._model.loading_seconds - loading_before))
            result.loading_s += loading
            requests_after = self._model.request_seconds
            request_time = (
                max(0.0, requests_after - requests_before)
                if requests_before is not None and requests_after is not None else duration
            )
            result.inference_s += max(0.0, min(duration, request_time) - loading)
        if analysis.signature_probability is not None:
            result.page_signature_probabilities[page.number] = analysis.signature_probability
        if analysis.signature_score is not None:
            result.page_decision_scores[page.number] = analysis.signature_score
        if analysis.signature_threshold is not None:
            result.page_decision_thresholds[page.number] = analysis.signature_threshold
        if analysis.review_reasons:
            result.page_review_reasons[page.number] = list(analysis.review_reasons)
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
        self, path: Path, result: DocumentResult, cancel: CancelToken
    ) -> None:
        scan = scan_digital_signatures(path)
        if scan.notes:
            result.error = _safe_document_error(DocumentReadError("; ".join(scan.notes)), path)
        for sig in scan.signatures:
            _raise_if_cancelled(cancel)
            crop_png, overview_jpeg = self._digital_images(path, sig)
            result.findings.append(
                SignatureFinding(
                    kind=SignatureKind.DIGITAL,
                    page=sig.page or 1,
                    confidence=100,  # obecność w strukturze PDF jest pewna
                    crop_png=crop_png,
                    overview_jpeg=overview_jpeg,
                    detail=sig.detail,
                )
            )

    def _digital_images(
        self, path: Path, sig: DigitalSignature
    ) -> tuple[bytes | None, bytes | None]:
        """Wycinek i miniatura widocznego widgetu podpisu cyfrowego (jeśli istnieje)."""
        if sig.page is None or sig.rect_pt is None:
            return None, None
        try:
            page = render_pdf_page(path, sig.page)
        except DocumentReadError:
            return None, None
        try:
            if page.page_size_pt is None:
                return None, None
            crop = crop_pdf_rect(
                page.image, sig.rect_pt, page.page_size_pt, page.page_bbox_pt, page.rotation,
            )
            overview = overview_pdf_rect(
                page.image, sig.rect_pt, page.page_size_pt, page.page_bbox_pt, page.rotation,
            )
            return (
                to_png_bytes(crop) if crop is not None else None,
                to_jpeg_bytes(overview) if overview is not None else None,
            )
        finally:
            page.image.close()


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
            partial = analyzer.last_result
            if partial is not None:
                partial.status = DocumentStatus.CANCELLED
                batch.results.append(partial)
            batch.results.extend(
                DocumentResult(path=p, status=DocumentStatus.CANCELLED) for p in files[index + 1:]
            )
            break
        except Exception as exc:
            batch.abort_error = str(exc)
            partial = analyzer.last_result
            if not isinstance(partial, DocumentResult):
                partial = DocumentResult(path=path)
            partial.status = DocumentStatus.ERROR
            partial.error = str(exc)
            batch.results.append(partial)
            batch.results.extend(
                DocumentResult(path=p, status=DocumentStatus.CANCELLED) for p in files[index + 1 :]
            )
            break
        batch.results.append(result)
        if on_file_done is not None:
            on_file_done(index, result)
    batch.preparation_s = sum(r.preparation_s for r in batch.results)
    batch.loading_s = sum(r.loading_s for r in batch.results)
    batch.inference_s = sum(r.inference_s for r in batch.results)
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
