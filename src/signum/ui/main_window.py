"""Okno główne: kolejka plików, przetwarzanie z postępem i raport z wycinkami."""

from __future__ import annotations

import math
import time
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedLayout,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from signum import APP_DISPLAY_NAME, __version__
from signum.ai import VisionModel, create_vision_model
from signum.ai.prompts import build_page_prompt
from signum.config import AppConfig, get_api_key
from signum.core.discovery import collect_documents
from signum.core.models import DocumentResult, DocumentStatus
from signum.core.pipeline import BatchResult, DocumentAnalyzer
from signum.local_components import repair_instructions
from signum.network import processing_is_local
from signum.report import write_csv, write_html
from signum.ui.batch_risk_dialog import BatchRiskDialog
from signum.ui.classification_panel import ClassificationPanel
from signum.ui.components_dialog import ComponentsDialog
from signum.ui.settings_dialog import SettingsDialog
from signum.ui.theme import SIGNUM_STYLE
from signum.ui.worker import BatchWorker, ConnectionTestWorker

_COL_FILE, _COL_TITLE, _COL_SIGNATURES, _COL_CONFIDENCE, _COL_STATUS = range(5)

_GREEN = QColor("#2e7d32")
_GRAY = QColor("#757575")
_RED = QColor("#c62828")
_BLUE = QColor("#1565c0")

_FILE_DIALOG_FILTER = (
    "Dokumenty (*.pdf *.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp);;Wszystkie pliki (*.*)"
)


class MainWindow(QMainWindow):
    """Główne okno aplikacji Signum."""

    def __init__(self) -> None:
        super().__init__()
        self._config = AppConfig.load()
        self._files: list[Path] = []
        self._results: dict[int, DocumentResult] = {}
        self._worker: BatchWorker | None = None
        self._preflight_worker: ConnectionTestWorker | None = None
        self._pending_model: VisionModel | None = None
        self._last_batch: BatchResult | None = None
        self._batch_started = 0.0
        self._preflight_started = 0.0
        self._preflight_seconds = 0.0
        self._preflight_loading = 0.0
        self._close_when_finished = False

        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setStyleSheet(SIGNUM_STYLE)
        self.resize(1380, 860)
        self.setAcceptDrops(True)
        self._build_actions()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._update_action_states()

    # -- budowa UI ---------------------------------------------------------

    def _build_actions(self) -> None:
        self.act_add_files = QAction("Dodaj pliki…", self)
        self.act_add_files.triggered.connect(self._on_add_files)
        self.act_add_folder = QAction("Dodaj folder…", self)
        self.act_add_folder.triggered.connect(self._on_add_folder)
        self.act_process = QAction("Przetwórz", self)
        self.act_process.triggered.connect(self._on_process)
        self.act_cancel = QAction("Anuluj", self)
        self.act_cancel.triggered.connect(self._on_cancel)
        self.act_export = QAction("Zapisz raport…", self)
        self.act_export.triggered.connect(self._on_export)
        self.act_clear = QAction("Wyczyść", self)
        self.act_clear.triggered.connect(self._on_clear)
        self.act_settings = QAction("Ustawienia AI…", self)
        self.act_settings.triggered.connect(self._on_settings)
        self.act_components = QAction("Składniki AI…", self)
        self.act_components.triggered.connect(self._on_components)
        self.act_about = QAction("O programie", self)
        self.act_about.triggered.connect(self._on_about)
        for action, icon in (
            (self.act_add_files, QStyle.StandardPixmap.SP_FileIcon),
            (self.act_add_folder, QStyle.StandardPixmap.SP_DirOpenIcon),
            (self.act_export, QStyle.StandardPixmap.SP_DialogSaveButton),
        ):
            action.setIcon(self.style().standardIcon(icon))

    def _build_toolbar(self) -> None:
        self.signature_toolbar = QToolBar("Główne")
        self.signature_toolbar.hide()

    def _action_button(self, action: QAction, role: str = "") -> QPushButton:
        button = QPushButton(action.text())
        button.setIcon(action.icon())
        if role:
            button.setProperty("role", role)
        button.clicked.connect(action.trigger)
        action.changed.connect(lambda: button.setEnabled(action.isEnabled()))
        button.setEnabled(action.isEnabled())
        return button

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(5)

        # Lewa strona: podpowiedź (pusty stan) albo tabela wyników.
        left = QWidget()
        left.setProperty("role", "card")
        self._left_stack = QStackedLayout(left)
        self._left_stack.setContentsMargins(8, 8, 8, 8)

        hint = QLabel("Przeciągnij tutaj pliki PDF lub skany")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setProperty("role", "muted")
        self._left_stack.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Plik", "Opis / nazwa", "Podpisy", "Ocena", "Status"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnWidth(_COL_FILE, 180)
        self.table.setColumnWidth(_COL_TITLE, 160)
        self.table.setColumnWidth(_COL_SIGNATURES, 180)
        self.table.setColumnWidth(_COL_CONFIDENCE, 70)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self._left_stack.addWidget(self.table)

        splitter.addWidget(left)
        splitter.addWidget(self._build_details_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([740, 440])
        signature_page = QWidget()
        signature_layout = QVBoxLayout(signature_page)
        signature_layout.setContentsMargins(8, 0, 8, 6)
        signature_layout.setSpacing(6)
        file_bar = QWidget()
        file_bar.setProperty("role", "commandBar")
        files_layout = QHBoxLayout(file_bar)
        files_layout.setContentsMargins(4, 7, 4, 7)
        for action in (self.act_add_files, self.act_add_folder, self.act_clear, self.act_export):
            files_layout.addWidget(self._action_button(action))
        files_layout.addStretch()
        self.signature_file_count = QLabel("0 plików")
        self.signature_file_count.setProperty("role", "muted")
        files_layout.addWidget(self.signature_file_count)
        signature_layout.addWidget(file_bar)

        model_bar = QWidget()
        model_bar.setProperty("role", "commandBar")
        model_layout = QHBoxLayout(model_bar)
        model_layout.setContentsMargins(0, 0, 0, 6)
        self.signature_model = QLabel()
        self.signature_model.setTextFormat(Qt.TextFormat.PlainText)
        model_layout.addWidget(self.signature_model, 1)
        self.settings_button = self._action_button(self.act_settings)
        model_layout.addWidget(self.settings_button)
        model_layout.addWidget(self._action_button(self.act_components))
        model_layout.addWidget(self._action_button(self.act_cancel))
        model_layout.addWidget(self._action_button(self.act_process, "primary"))
        signature_layout.addWidget(model_bar)
        self.signature_layout = signature_layout
        signature_layout.addWidget(splitter, 1)
        self.mode_tabs = QTabWidget()
        self.mode_tabs.addTab(signature_page, "Sprawdzanie podpisów")
        self.classification = ClassificationPanel(self)
        self.mode_tabs.addTab(self.classification, "Kategoryzowanie dokumentów")
        self.classification.busy_changed.connect(self._classification_busy_changed)
        self.classification.settings_changed.connect(self._reload_config)
        self.classification.files_moved.connect(self._files_moved)
        self.mode_tabs.currentChanged.connect(self._mode_changed)
        self.mode_tabs.setCornerWidget(self._action_button(self.act_about, "quiet"))
        self.setCentralWidget(self.mode_tabs)

    def _files_moved(self, moved: dict[Path, Path]) -> None:
        self._files = [moved.get(path, path) for path in self._files]
        results = list(self._results.values())
        if self._last_batch:
            results += self._last_batch.results
        for result in {id(result): result for result in results}.values():
            result.path = moved.get(result.path, result.path)
        for index, path in enumerate(self._files):
            self._cell(index, _COL_FILE).setText(path.name)
            self._cell(index, _COL_FILE).setToolTip(str(path))
        self._on_selection_changed()

    def _reload_config(self) -> None:
        self._config = AppConfig.load()

    def _mode_changed(self, index: int) -> None:
        self.signature_toolbar.hide()
        self.statusBar().hide()
        self._reload_config()
        self._refresh_online_badge()

    def _classification_busy_changed(self, busy: bool) -> None:
        self._update_action_states()
        if not busy and self._close_when_finished:
            self._close_when_finished = False
            QTimer.singleShot(0, self.close)

    def _build_details_panel(self) -> QWidget:
        self.details_scroll = QScrollArea()
        self.details_scroll.setObjectName("signatureDetailsScroll")
        self.details_scroll.setWidgetResizable(True)
        self.details_container = QWidget()
        self.details_container.setStyleSheet("QWidget#signatureDetails { background: white; }")
        self.details_container.setObjectName("signatureDetails")
        self.details_layout = QVBoxLayout(self.details_container)
        self.details_layout.setContentsMargins(12, 12, 12, 12)
        self.details_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.details_scroll.setWidget(self.details_container)
        self._show_details_placeholder()
        return self.details_scroll

    def _build_statusbar(self) -> None:
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.signature_layout.addWidget(self.progress)
        controls = QHBoxLayout()
        info = QVBoxLayout()
        self.status_label = QLabel("AI: połączenie niesprawdzone")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        info.addWidget(self.status_label)
        self.signature_elapsed = QLabel()
        self.signature_elapsed.setProperty("role", "muted")
        info.addWidget(self.signature_elapsed)
        controls.addLayout(info, 1)
        self.online_badge = _OnlineBadge()
        controls.addWidget(self.online_badge)
        self.signature_layout.addLayout(controls)
        self.statusBar().hide()
        self._signature_timer = QTimer(self)
        self._signature_timer.timeout.connect(self._refresh_signature_time)
        self._refresh_online_badge()

    def _refresh_signature_time(self) -> None:
        batch = self._last_batch
        if batch is None:
            results = list(self._results.values())
            preparation = sum(r.preparation_s for r in results)
            loading = self._preflight_loading + sum(r.loading_s for r in results)
            inference = sum(r.inference_s for r in results)
            total = time.perf_counter() - self._preflight_started
        else:
            preparation, loading, inference, total = (
                batch.preparation_s,
                batch.loading_s,
                batch.inference_s,
                batch.duration_s,
            )
        self.signature_elapsed.setText(
            f"Przygotowanie: {preparation:.2f} s   ·   Ładowanie: {loading:.2f} s   ·   "
            f"Działanie: {inference:.2f} s   ·   Łącznie: {total:.2f} s"
        )

    def _refresh_online_badge(self) -> None:
        """Plakietka „model online" jest widoczna, gdy dostawca AI nie jest lokalny."""
        cfg = self._config
        self.online_badge.setVisible(
            not processing_is_local(cfg.provider, cfg.api_base_url)
            or (cfg.provider == "ollama" and cfg.ollama_model.lower().endswith("cloud"))
        )
        provider = "Ollama" if cfg.provider == "ollama" else "AI od dostawcy"
        self.signature_model.setText(f"{provider} · {getattr(cfg, cfg.provider + '_model')}")

    # -- drag & drop ---------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — API Qt
        if event.mimeData().hasUrls() and not self._is_busy():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — API Qt
        if self._is_busy():
            event.ignore()
            return
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            if self.mode_tabs.currentIndex() == 1:
                self.classification.add_files(paths)
            else:
                self._add_documents(paths)

    # -- akcje użytkownika ---------------------------------------------------

    def _on_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Wybierz dokumenty", self._config.last_dir, _FILE_DIALOG_FILTER
        )
        if files:
            self._remember_dir(Path(files[0]).parent)
            self._add_documents([Path(f) for f in files])

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Wybierz folder z dokumentami", self._config.last_dir
        )
        if folder:
            self._remember_dir(Path(folder))
            self._add_documents([Path(folder)])

    def _add_documents(self, paths: list[Path]) -> None:
        if self._is_busy():
            return
        found = collect_documents(paths, recursive=self._config.recursive_folders)
        existing = set(self._files)
        new_files = [f for f in found if f not in existing]
        if not new_files:
            self.status_label.setText("Nie znaleziono nowych obsługiwanych dokumentów.")
            return
        for path in new_files:
            row = self.table.rowCount()
            self.table.insertRow(row)
            file_item = QTableWidgetItem(path.name)
            file_item.setToolTip(str(path))
            self.table.setItem(row, _COL_FILE, file_item)
            self.table.setItem(row, _COL_TITLE, QTableWidgetItem(""))
            self.table.setItem(row, _COL_SIGNATURES, QTableWidgetItem(""))
            self.table.setItem(row, _COL_CONFIDENCE, QTableWidgetItem(""))
            self.table.setItem(row, _COL_STATUS, QTableWidgetItem("Oczekuje"))
        self._files.extend(new_files)
        self._left_stack.setCurrentIndex(1)
        self.status_label.setText(f"W kolejce: {len(self._files)} plików.")
        self._update_action_states()

    def _on_process(self) -> None:
        if self._is_busy() or not self._files:
            return
        if not self._ensure_ai_ready():
            return
        if not self._confirm_batch_risk():
            self.status_label.setText("Analiza nie została uruchomiona.")
            return
        self._preflight_started = time.perf_counter()
        self._preflight_loading = 0
        self._last_batch = None
        self._results.clear()
        self._signature_timer.start(200)
        try:
            model = create_vision_model(self._config)
        except ValueError as exc:
            self._signature_timer.stop()
            QMessageBox.critical(self, "Ustawienia AI", str(exc))
            return
        self._pending_model = model
        self.status_label.setText("Sprawdzanie usługi AI i dostępności modelu…")
        self._preflight_worker = ConnectionTestWorker(model, self)
        self._preflight_worker.finished_with_result.connect(self._on_preflight_result)
        self._preflight_worker.finished.connect(self._on_preflight_finished)
        self._preflight_worker.start()
        self._update_action_states()

    def _start_batch(self, model: VisionModel) -> None:
        analyzer = DocumentAnalyzer(
            model=model,
            max_pages=self._config.max_pages_per_doc,
            image_max_side=self._config.model_image_max_side,
            prompt=build_page_prompt(
                self._config.custom_prompt,
                self._config.provider,
                self._config.jev_custom_prompt,
            ),
        )
        self._results.clear()
        self._last_batch = None
        for row in range(self.table.rowCount()):
            self._set_status_cell(row, "Oczekuje", _GRAY)
            self._cell(row, _COL_TITLE).setText("")
            self._cell(row, _COL_SIGNATURES).setText("")
            self._cell(row, _COL_CONFIDENCE).setText("")

        self._batch_started = time.monotonic()
        self.progress.setRange(0, len(self._files))
        self.progress.setValue(0)
        self.progress.setVisible(True)

        self._worker = BatchWorker(
            list(self._files), analyzer, self._preflight_seconds, self._preflight_loading
        )
        self._worker.file_started.connect(self._on_file_started)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.batch_done.connect(self._on_batch_done)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()
        self._update_action_states()

    def _confirm_batch_risk(self) -> bool:
        """Wymaga jednego potwierdzenia dla całej kolejki, nie dla każdego pliku."""
        dialog = BatchRiskDialog(self._config, len(self._files), self)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _on_preflight_result(self, ok: bool, message: str) -> None:
        self._preflight_seconds = time.perf_counter() - self._preflight_started
        if self._pending_model is not None:
            self._preflight_loading = self._pending_model.loading_seconds
        if self._close_when_finished:
            self._signature_timer.stop()
            self._pending_model = None
            return
        if not ok:
            self._signature_timer.stop()
            self._refresh_signature_time()
            detail = repair_instructions(message, self._config.provider)
            QMessageBox.critical(self, "Usługa AI niedostępna", detail)
            self.status_label.setText("Usługa AI niedostępna — sprawdź ustawienia.")
            self._pending_model = None
            return
        self.status_label.setText(message)
        model = self._pending_model
        self._pending_model = None
        if model is not None:
            self._start_batch(model)

    def _on_preflight_finished(self) -> None:
        worker = self._preflight_worker
        self._preflight_worker = None
        if worker is not None:
            worker.deleteLater()
        self._update_action_states()
        if self._close_when_finished:
            self._close_when_finished = False
            QTimer.singleShot(0, self.close)

    def _ensure_ai_ready(self) -> bool:
        """Dla dostawców chmurowych wymagany jest klucz API."""
        if self._config.requires_api_key and not get_api_key(self._config.provider):
            answer = QMessageBox.question(
                self,
                "Brak klucza API",
                "Nie zapisano klucza API dla wybranego dostawcy.\nOtworzyć ustawienia AI?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._on_settings()
            return False
        return True

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText("Anulowanie — czekam na zakończenie bieżącej strony…")
            self.act_cancel.setEnabled(False)

    def _on_clear(self) -> None:
        if self._is_busy():
            return
        self._files.clear()
        self._results.clear()
        self._last_batch = None
        self.table.setRowCount(0)
        self._left_stack.setCurrentIndex(0)
        self._show_details_placeholder()
        self.progress.setValue(0)
        self.signature_elapsed.clear()
        self.status_label.setText("Dodaj dokumenty")
        self._update_action_states()

    def _on_components(self) -> None:
        if self._is_busy():
            return
        ComponentsDialog(self._config, self).exec()
        self._reload_config()
        self.classification.reload_models()
        self._refresh_online_badge()

    def _on_settings(self) -> None:
        dialog = SettingsDialog(self._config, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self.classification.reload_models()
        if accepted:
            self._config = AppConfig.load()
            self.status_label.setText("Zapisano ustawienia AI.")
        else:
            # Dialog mógł zmodyfikować obiekt konfiguracji (np. test połączenia)
            # bez zapisu — wracamy do stanu z dysku.
            self._config = AppConfig.load()
        self._refresh_online_badge()

    def _on_export(self) -> None:
        if self._last_batch is None:
            QMessageBox.information(
                self, "Raport", "Najpierw przetwórz dokumenty — raport powstaje z wyników."
            )
            return
        answer = QMessageBox.question(
            self,
            "Poufność raportu",
            "Raport zawiera nazwy dokumentów i informacje uzyskane z ich treści. "
            "Raport HTML zawiera również wycinki podpisów i miniatury stron.\n\n"
            "Przed przekazaniem raportu innej osobie sprawdź uprawnienia, poufność "
            "oraz miejsce zapisu. Kontynuować?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        path_str, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Zapisz raport",
            str(Path(self._config.last_dir or ".") / "raport_podpisy.html"),
            "Raport HTML (*.html);;Raport CSV (*.csv)",
        )
        if not path_str:
            return
        path = Path(path_str)
        self._remember_dir(path.parent)
        try:
            if "CSV" in selected_filter or path.suffix.lower() == ".csv":
                write_csv(path, self._last_batch)
            else:
                write_html(path, self._last_batch)
        except OSError as exc:
            QMessageBox.critical(self, "Raport", f"Nie udało się zapisać raportu:\n{exc}")
            return
        self.status_label.setText(f"Zapisano raport: {path}")

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "O programie",
            f"<b>{APP_DISPLAY_NAME}</b><br>wersja {__version__}<br><br>"
            "Dwie osobne funkcje: kategoryzowanie tekstu PDF do własnych kategorii "
            "oraz sprawdzanie podpisów.<br><br>"
            "Wykrywa podpisy odręczne, parafki, pieczątki i podpisy cyfrowe "
            "w dokumentach PDF i skanach przy użyciu wizyjnych modeli AI "
            "(lokalnie przez Ollamę albo przez API chmurowe).<br><br>"
            "Program stwierdza wyłącznie <i>obecność</i> podpisów — nie weryfikuje "
            "ich autentyczności, ważności prawnej ani kryptograficznej. Wyniki AI "
            "mogą być błędne lub niepełne i wymagają ręcznej weryfikacji.",
        )

    # -- zdarzenia wątku roboczego --------------------------------------------

    def _on_file_started(self, index: int, total: int, name: str) -> None:
        eta = self._format_eta(index, total)
        self.status_label.setText(f"Przetwarzanie {index + 1}/{total}: {name}{eta}")
        self._set_status_cell(index, "Analiza…", _BLUE)
        self.table.scrollToItem(self._cell(index, _COL_FILE))

    def _on_file_done(self, index: int, result: DocumentResult) -> None:
        self._results[index] = result
        self.progress.setValue(index + 1)
        self._fill_result_row(index, result)
        selected = self.table.currentRow()
        if selected == index:
            self._show_details(result)

    def _on_batch_done(self, batch: BatchResult) -> None:
        self._last_batch = batch
        self._signature_timer.stop()
        self._refresh_signature_time()
        self.progress.setValue(self.progress.maximum())
        summary = (
            f"Zakończono: {len(batch.results)} plików w {batch.duration_s:.0f} s — "
            f"z podpisami: {batch.signed_count}, błędy: {batch.error_count}."
        )
        self.status_label.setText(summary)
        # Uzupełnij wiersze anulowane (worker nie wysłał dla nich file_done).
        for index, result in enumerate(batch.results):
            if index not in self._results:
                self._results[index] = result
                self._fill_result_row(index, result)
        if batch.abort_error and not self._close_when_finished:
            QMessageBox.critical(
                self,
                "Przetwarzanie przerwane",
                repair_instructions(batch.abort_error, self._config.provider),
            )
        self._update_action_states()

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._update_action_states()
        if self._close_when_finished:
            self._close_when_finished = False
            QTimer.singleShot(0, self.close)

    # -- pomocnicze ------------------------------------------------------------

    def _cell(self, row: int, col: int) -> QTableWidgetItem:
        item = self.table.item(row, col)
        if item is None:  # wiersze zawsze tworzymy z kompletem komórek
            raise RuntimeError(f"Brak komórki tabeli ({row}, {col})")
        return item

    def _fill_result_row(self, row: int, result: DocumentResult) -> None:
        if row >= self.table.rowCount():
            return
        self._cell(row, _COL_TITLE).setText(result.title)
        if result.status == DocumentStatus.OK:
            text = result.signature_label
            color = _GREEN if result.is_signed else _GRAY
            signatures_item = self._cell(row, _COL_SIGNATURES)
            signatures_item.setText(text)
            signatures_item.setForeground(color)
            confidence = result.max_confidence
            self._cell(row, _COL_CONFIDENCE).setText(
                f"{confidence}%" if confidence is not None else ""
            )
            if result.page_signature_probabilities:
                item = self._cell(row, _COL_CONFIDENCE)
                item.setText(f"{max(result.page_signature_probabilities.values()) * 100:.1f}%")
                item.setToolTip(
                    "Najwyższe prawdopodobieństwo obecności podpisu na analizowanych stronach."
                )
            self._set_status_cell(row, "OK", _GREEN)
        elif result.status == DocumentStatus.ERROR:
            self._set_status_cell(row, "Błąd", _RED)
            self._cell(row, _COL_STATUS).setToolTip(
                repair_instructions(result.error or "", self._config.provider)
            )
        elif result.status == DocumentStatus.CANCELLED:
            self._set_status_cell(row, "Anulowano", _GRAY)

    def _set_status_cell(self, row: int, text: str, color: QColor) -> None:
        if row >= self.table.rowCount():
            return
        item = self._cell(row, _COL_STATUS)
        item.setText(text)
        item.setForeground(color)

    def _format_eta(self, done: int, total: int) -> str:
        if done == 0:
            return ""
        elapsed = time.monotonic() - self._batch_started
        remaining = elapsed / done * (total - done)
        minutes, seconds = divmod(int(remaining), 60)
        return f" (pozostało ok. {minutes}:{seconds:02d})"

    def _is_processing(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _is_preflighting(self) -> bool:
        return self._preflight_worker is not None and self._preflight_worker.isRunning()

    def _is_busy(self) -> bool:
        return self._is_processing() or self._is_preflighting() or self.classification.is_busy()

    def _update_action_states(self) -> None:
        processing = self._is_processing()
        busy = self._is_busy()
        self.mode_tabs.setTabEnabled(0, not self.classification.is_busy())
        self.mode_tabs.setTabEnabled(1, not (processing or self._is_preflighting()))
        self.signature_file_count.setText(f"{len(self._files)} plików")
        has_files = bool(self._files)
        self.act_add_files.setEnabled(not busy)
        self.act_add_folder.setEnabled(not busy)
        self.act_process.setEnabled(not busy and has_files)
        self.act_cancel.setEnabled(processing)
        self.act_clear.setEnabled(not busy and has_files)
        self.act_components.setEnabled(not self._is_busy())
        self.act_settings.setEnabled(not busy)
        self.act_export.setEnabled(not busy and self._last_batch is not None)

    def _remember_dir(self, directory: Path) -> None:
        self._config.last_dir = str(directory)
        self._config.save()

    # -- panel szczegółów --------------------------------------------------------

    def _on_selection_changed(self) -> None:
        row = self.table.currentRow()
        result = self._results.get(row)
        if result is None:
            self._show_details_placeholder()
        else:
            self._show_details(result)

    def _show_details_placeholder(self) -> None:
        self._clear_details()
        label = QLabel("Wybierz dokument")
        label.setWordWrap(True)
        label.setStyleSheet("color: #888;")
        self.details_layout.addWidget(label)

    def _show_details(self, result: DocumentResult) -> None:
        self._clear_details()
        title = QLabel(result.title or result.path.name)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(max(title_font.pointSize() + 3, 12))
        title.setFont(title_font)
        title.setWordWrap(True)
        self.details_layout.addWidget(title)
        path_label = QLabel(result.path.name)
        path_label.setTextFormat(Qt.TextFormat.PlainText)
        path_label.setToolTip(str(result.path))
        path_label.setWordWrap(True)
        path_label.setStyleSheet("color: #666; font-size: 11px;")
        self.details_layout.addWidget(path_label)
        open_source = QPushButton("Otwórz dokument źródłowy")
        open_source.clicked.connect(lambda: self._open_source_document(result.path))
        self.details_layout.addWidget(open_source)

        if result.status == DocumentStatus.ERROR:
            error = QLabel(
                repair_instructions(result.error or "Błąd dokumentu", self._config.provider)
            )
            error.setTextFormat(Qt.TextFormat.PlainText)
            error.setWordWrap(True)
            error.setStyleSheet("color: #c62828;")
            self.details_layout.addWidget(error)
            return
        if result.status == DocumentStatus.CANCELLED:
            self.details_layout.addWidget(QLabel("Plik pominięty (anulowano)."))
            return

        meta = QLabel(
            f"Przeanalizowano {result.pages_analyzed}/{result.page_count} stron "
            f"w {result.duration_s:.1f} s."
        )
        meta.setStyleSheet("color: #666;")
        self.details_layout.addWidget(meta)

        if result.pages_analyzed < result.page_count:
            partial = QLabel(
                "Analiza obejmuje tylko część dokumentu. Pozostałe strony mogą "
                "zawierać podpisy. Zwiększ limit stron w ustawieniach AI."
            )
            partial.setWordWrap(True)
            self.details_layout.addWidget(partial)
        if result.page_signature_probabilities and not result.is_signed:
            values = "; ".join(
                f"strona {page}: {probability * 100:.1f}%"
                for page, probability in result.page_signature_probabilities.items()
            )
            probability_label = QLabel("Prawdopodobieństwo obecności podpisu: " + values)
            probability_label.setTextFormat(Qt.TextFormat.PlainText)
            probability_label.setWordWrap(True)
            self.details_layout.addWidget(probability_label)

        if not result.findings:
            none_label = QLabel("<b>Nie wykryto podpisów.</b>")
            self.details_layout.addWidget(none_label)
            return

        header = QLabel(f"<b>Wykryto: {result.kinds_summary}</b>")
        header.setWordWrap(True)
        self.details_layout.addWidget(header)
        for finding in result.findings:
            self.details_layout.addWidget(self._finding_widget(finding))

    def _finding_widget(self, finding) -> QWidget:  # type: ignore[no-untyped-def]
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        caption = QLabel(
            f"<b>{finding.kind.label_pl.capitalize()}</b> — strona {finding.page}, "
            f"pewność {finding.confidence}%"
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)
        if finding.detail:
            detail = QLabel(finding.detail)
            detail.setTextFormat(Qt.TextFormat.PlainText)
            detail.setWordWrap(True)
            detail.setStyleSheet("color: #444; font-size: 11px;")
            layout.addWidget(detail)
        if finding.crop_png:
            pixmap = QPixmap()
            pixmap.loadFromData(finding.crop_png)
            crop_label = _ClickableLabel(pixmap)
            layout.addWidget(crop_label)
        return frame

    def _open_source_document(self, path: Path) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            QMessageBox.warning(
                self, "Dokument źródłowy", "Nie udało się otworzyć dokumentu w domyślnym programie."
            )

    def _clear_details(self) -> None:
        while self.details_layout.count():
            item = self.details_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                # Odpięcie rodzica od razu — widget czekający na deleteLater
                # nie może malować się nad nową zawartością panelu.
                widget.setParent(None)
                widget.deleteLater()

    # -- zamknięcie okna -----------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def] # noqa: N802 — API Qt
        self.classification.save_preferences()
        self.classification._persist_collection()
        if self.classification.is_busy():
            self._close_when_finished = True
            self.classification.cancel()
            event.ignore()
            return
        if self._is_preflighting():
            if self._close_when_finished:
                event.ignore()
                return
            answer = QMessageBox.question(
                self,
                "Trwa sprawdzanie usługi AI",
                "Poczekać na zakończenie sprawdzania i zamknąć program?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._close_when_finished = True
                self.status_label.setText("Zamykanie po zakończeniu sprawdzania usługi AI…")
                self.setEnabled(False)
            event.ignore()
            return
        if self._is_processing():
            if self._close_when_finished:
                event.ignore()
                return
            answer = QMessageBox.question(
                self,
                "Trwa przetwarzanie",
                "Trwa analiza dokumentów. Przerwać i zamknąć program?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self._worker is not None:
                self._worker.cancel()
                self._close_when_finished = True
                self.status_label.setText(
                    "Zamykanie po bezpiecznym zakończeniu bieżącego żądania AI…"
                )
                self.setEnabled(False)
                event.ignore()
                return
        event.accept()


class _ClickableLabel(QLabel):
    """Miniatura wycinka podpisu — kliknięcie otwiera podgląd 1:1."""

    clicked = Signal()

    def __init__(self, pixmap: QPixmap) -> None:
        super().__init__()
        self._full_pixmap = pixmap
        preview = pixmap
        if pixmap.width() > 380 or pixmap.height() > 140:
            preview = pixmap.scaled(
                380,
                140,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.setPixmap(preview)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Kliknij, aby powiększyć")
        self.setStyleSheet("border: 1px solid #ccc; background: white; padding: 2px;")

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def] # noqa: N802 — API Qt
        dialog = QDialog(self.window())
        dialog.setWindowTitle("Wycinek podpisu")
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QLabel()
        inner.setPixmap(self._full_pixmap)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        dialog.resize(
            min(1000, self._full_pixmap.width() + 60),
            min(700, self._full_pixmap.height() + 60),
        )
        dialog.exec()
        super().mousePressEvent(event)


class _OnlineBadge(QFrame):
    """Plakietka ostrzegawcza: aktywny dostawca AI wysyła dane poza komputer."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("onlineBadge")
        self.setStyleSheet(
            "#onlineBadge { border: 1px solid #c62828; border-radius: 0;"
            " background: #fff; }"
            "#onlineBadge QLabel { color: #c62828; font-weight: 600; border: none; }"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(6)
        icon = QLabel()
        icon.setPixmap(_transfer_arrows_pixmap())
        row.addWidget(icon)
        row.addWidget(QLabel("Model online"))
        self.setToolTip(
            "Aktywna usługa AI nie działa na tym komputerze — analizowane dokumenty "
            "są wysyłane przez sieć poza ten komputer.\n"
            "Trybem lokalnym jest API pod adresem pętli zwrotnej "
            "tego komputera (np. http://localhost:8800/v1)."
        )


def _transfer_arrows_pixmap(size: int = 18) -> QPixmap:
    """Ikona wymiany danych: czerwona strzałka ↗ (wysyłka), niebieska ↙ (odbiór)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    _draw_arrow(painter, s * 0.25, s * 0.72, s * 0.90, s * 0.08, _RED)
    _draw_arrow(painter, s * 0.75, s * 0.28, s * 0.10, s * 0.92, _BLUE)
    painter.end()
    return pixmap


def _draw_arrow(
    painter: QPainter, x0: float, y0: float, x1: float, y1: float, color: QColor
) -> None:
    pen = QPen(color, 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    angle = math.atan2(y1 - y0, x1 - x0)
    head = 5.0
    for offset in (math.pi * 5 / 6, -math.pi * 5 / 6):  # grot: dwa skośne odcinki
        painter.drawLine(
            QPointF(x1, y1),
            QPointF(
                x1 + head * math.cos(angle + offset),
                y1 + head * math.sin(angle + offset),
            ),
        )


__all__ = ["MainWindow"]
