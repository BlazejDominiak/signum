"""Wątki robocze Qt — analiza plików i test połączenia poza wątkiem GUI."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from signum.ai.base import AIError, VisionModel
from signum.ai.ollama_client import OllamaVisionModel
from signum.core.models import DocumentResult
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
