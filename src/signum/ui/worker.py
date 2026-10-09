"""Wątki robocze Qt — analiza plików i test połączenia poza wątkiem GUI."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from signum.ai import create_vision_model
from signum.ai.base import AIError, VisionModel
from signum.ai.ollama_client import OllamaVisionModel
from signum.ai.prompts import build_page_prompt
from signum.config import AppConfig
from signum.core.models import DocumentResult, DocumentStatus
from signum.core.pipeline import BatchResult, CancelToken, DocumentAnalyzer, run_batch


class BatchWorker(QThread):
    """Sekwencyjnie przetwarza partię plików w tle, raportując postęp sygnałami."""

    file_started = Signal(int, int, str)  # indeks, liczba plików, nazwa pliku
    file_done = Signal(int, object)  # indeks, DocumentResult
    batch_done = Signal(object)  # BatchResult

    def __init__(
        self, files: list[Path], analyzer: DocumentAnalyzer,
        preflight_s: float = 0, loading_s: float = 0,
    ) -> None:
        super().__init__()
        self._preflight_s = preflight_s
        self._loading_s = loading_s
        self._files = files
        self._analyzer = analyzer
        self._cancel = CancelToken()

    def cancel(self) -> None:
        """Żądanie anulowania — wątek zakończy się po bieżącej stronie."""
        self._cancel.cancel()

    def run(self) -> None:
        started = time.time()
        completed: list[DocumentResult] = []

        def record(index: int, result: DocumentResult) -> None:
            completed.append(result)
            self.file_done.emit(index, result)

        try:
            batch = run_batch(
                self._files,
                self._analyzer,
                self._cancel,
                on_file_start=lambda i, n, p: self.file_started.emit(i, n, p.name),
                on_file_done=record,
            )
        except Exception as exc:  # obrona: wyjątek nie może zabić wątku po cichu
            batch = BatchResult(
                results=completed, started_at=started, abort_error=f"Nieoczekiwany błąd: {exc}"
            )
        try:
            self._analyzer.release_resources()
        except Exception as exc:
            batch.abort_error = batch.abort_error or f"Nie udało się zwolnić modelu: {exc}"
        batch.started_at -= self._preflight_s
        batch.finished_at = time.time()
        batch.loading_s += self._loading_s
        batch.preflight_s = max(0, self._preflight_s - self._loading_s)
        self.batch_done.emit(batch)


class SignatureComparisonWorker(QThread):
    """Run vision models sequentially, keeping every result and its timings."""

    model_started = Signal(str)
    file_started = Signal(int, int, str)
    file_done = Signal(int, object)
    batch_done = Signal(object)

    def __init__(self, files: list[Path], configs: list[AppConfig]) -> None:
        super().__init__()
        self._files = files
        self._configs = configs
        self._cancel = CancelToken()

    def cancel(self) -> None:
        self._cancel.cancel()

    def run(self) -> None:
        for config in self._configs:
            if self._cancel.cancelled:
                name = f"{config.provider}: {getattr(config, config.provider + '_model')}"
                self.batch_done.emit(BatchResult(
                    model_name=name, analysis_settings=signature_settings(config),
                    results=[
                        DocumentResult(p, status=DocumentStatus.CANCELLED) for p in self._files
                    ],
                ))
            else:
                self.batch_done.emit(self._run_model(config))

    def _run_model(self, config: AppConfig) -> BatchResult:
        started = time.time()
        name = f"{config.provider}: {getattr(config, config.provider + '_model')}"
        batch = BatchResult(model_name=name, started_at=started)
        self.model_started.emit(name)
        model: VisionModel | None = None
        completed: list[DocumentResult] = []
        preflight = time.perf_counter()
        preflight_s = 0.0
        loading_s = 0.0

        def record(index: int, result: DocumentResult) -> None:
            completed.append(result)
            self.file_done.emit(index, result)

        try:
            model = create_vision_model(config)
            model.check_connection()
            preflight_s = time.perf_counter() - preflight
            loading_s = min(preflight_s, max(0.0, model.loading_seconds))
            analyzer = DocumentAnalyzer(
                model, config.max_pages_per_doc, config.model_image_max_side,
                build_page_prompt(config.custom_prompt, config.provider, config.jev_custom_prompt),
            )
            batch = run_batch(
                self._files, analyzer, self._cancel,
                on_file_start=lambda i, n, p: self.file_started.emit(i, n, p.name),
                on_file_done=record,
            )
        except Exception as exc:
            batch.abort_error = str(exc)
            batch.results = completed
            # Preserve failed setup explicitly, so it cannot look like a negative prediction.
            batch.results.extend(
                DocumentResult(path, status=DocumentStatus.ERROR, error=str(exc))
                for path in self._files[len(completed):]
            )
            batch.preparation_s = sum(r.preparation_s for r in completed)
            batch.loading_s = sum(r.loading_s for r in completed)
            batch.inference_s = sum(r.inference_s for r in completed)
            if not preflight_s:
                preflight_s = time.perf_counter() - preflight
                loading_s = min(preflight_s, max(0.0, model.loading_seconds)) if model else 0
        finally:
            if model is not None:
                try:
                    model.release_resources()
                except Exception as exc:
                    batch.abort_error = batch.abort_error or f"Zwalnianie modelu: {exc}"
            batch.started_at = started
            batch.finished_at = time.time()
            batch.loading_s += loading_s
            batch.preflight_s = max(0.0, preflight_s - loading_s)
        batch.analysis_settings = signature_settings(config)
        return batch


def signature_settings(config: AppConfig) -> str:
    additional = getattr(config, config.provider + "_additional_analysis", True)
    return (
        f"Limit stron: {config.max_pages_per_doc}; "
        f"rozmiar obrazu: {config.model_image_max_side}; "
        f"dodatkowa analiza: {'tak' if additional else 'nie'}"
    )


class ConnectionTestWorker(QThread):
    """Test połączenia z modelem AI bez blokowania GUI."""

    finished_with_result = Signal(bool, str)  # sukces, komunikat

    def __init__(
        self,
        model: VisionModel,
        parent: QObject | None = None,
        *,
        stop_local: bool = False,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._stop_local = stop_local

    def run(self) -> None:
        try:
            message = (
                self._model.stop_local() if self._stop_local else self._model.check_connection()
            )
        except AIError as exc:
            self.finished_with_result.emit(False, str(exc))
        except Exception as exc:  # nie przepuszczaj żadnego wyjątku do Qt
            self.finished_with_result.emit(False, f"Nieoczekiwany błąd: {exc}")
        else:
            self.finished_with_result.emit(True, message)


class ModelListWorker(QThread):
    """Pobiera listę modeli z Ollamy (do rozwijanej listy w ustawieniach)."""

    finished_with_result = Signal(bool, object)  # sukces, list[str] | komunikat błędu

    def __init__(
        self,
        base_url: str,
        parent: QObject | None = None,
        api_key: str = "",
    ) -> None:
        super().__init__(parent)
        self._base_url = base_url
        self._api_key = api_key

    def run(self) -> None:
        try:
            models = OllamaVisionModel.list_models(self._base_url, api_key=self._api_key)
        except AIError as exc:
            self.finished_with_result.emit(False, str(exc))
        except Exception as exc:
            self.finished_with_result.emit(False, f"Nieoczekiwany błąd: {exc}")
        else:
            self.finished_with_result.emit(True, models)


__all__ = ["BatchWorker", "ConnectionTestWorker", "DocumentResult", "ModelListWorker"]
