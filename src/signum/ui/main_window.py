"""Okno główne: kolejka plików, przetwarzanie z postępem i raport z wycinkami."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPointF, QSignalBlocker, Qt, QTimer, QUrl, Signal
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
    QComboBox,
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
from signum.i18n import set_language, tr
from signum.local_components import repair_instructions
from signum.network import processing_is_local
from signum.report import write_csv, write_html
from signum.ui.batch_risk_dialog import BatchRiskDialog
from signum.ui.classification_panel import ClassificationPanel
from signum.ui.components_dialog import ComponentsDialog
from signum.ui.settings_dialog import SettingsDialog
from signum.ui.theme import SIGNUM_STYLE
from signum.ui.worker import (
    BatchWorker,
    ConnectionTestWorker,
    SignatureComparisonWorker,
    signature_settings,
)

_COL_FILE, _COL_TITLE, _COL_SIGNATURES, _COL_CONFIDENCE, _COL_STATUS = range(5)

_GREEN = QColor("#2e7d32")
_GRAY = QColor("#757575")
_RED = QColor("#c62828")
_BLUE = QColor("#1565c0")


def _file_dialog_filter() -> str:
    return tr("main.main_window.documents_pdf_jpg_jpeg_png_tif_tiff")


class MainWindow(QMainWindow):
    """Główne okno aplikacji Signum."""

    def __init__(self) -> None:
        super().__init__()
        self._config = AppConfig.load()
        set_language(self._config.language)
        self._files: list[Path] = []
        self._results: dict[int, DocumentResult] = {}
        self._worker: BatchWorker | SignatureComparisonWorker | None = None
        self._preflight_worker: ConnectionTestWorker | None = None
        self._pending_model: VisionModel | None = None
        self._last_batch: BatchResult | None = None
        self._signature_runs: list[BatchResult] = []
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
        self.act_add_files = QAction(tr("main.main_window.add_files"), self)
        self.act_add_files.triggered.connect(self._on_add_files)
        self.act_add_folder = QAction(tr("main.main_window.add_folder"), self)
        self.act_add_folder.triggered.connect(self._on_add_folder)
        self.act_process = QAction(tr("main.main_window.process"), self)
        self.act_process.triggered.connect(self._on_process)
        self.act_compare = QAction(tr("main.main_window.compare_ollama_jev"), self)
        self.act_compare.triggered.connect(self._on_compare)
        self.act_cancel = QAction(tr("main.main_window.cancel"), self)
        self.act_cancel.triggered.connect(self._on_cancel)
        self.act_export = QAction(tr("main.main_window.save_report"), self)
        self.act_export.triggered.connect(self._on_export)
        self.act_clear = QAction(tr("main.main_window.clear"), self)
        self.act_clear.triggered.connect(self._on_clear)
        self.act_settings = QAction(tr("main.main_window.ai_settings"), self)
        self.act_settings.triggered.connect(self._on_settings)
        self.act_components = QAction(tr("main.main_window.ai_components"), self)
        self.act_components.triggered.connect(self._on_components)
        self.act_about = QAction(tr("main.main_window.about"), self)
        self.act_about.triggered.connect(self._on_about)
        for action, icon in (
            (self.act_add_files, QStyle.StandardPixmap.SP_FileIcon),
            (self.act_add_folder, QStyle.StandardPixmap.SP_DirOpenIcon),
            (self.act_export, QStyle.StandardPixmap.SP_DialogSaveButton),
        ):
            action.setIcon(self.style().standardIcon(icon))

    def _build_toolbar(self) -> None:
        self.signature_toolbar = QToolBar(tr("main.main_window.main"))
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

        hint = QLabel(tr("main.main_window.drop_pdf_files_or_scans_here"))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setProperty("role", "muted")
        self._left_stack.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                tr("main.main_window.file"),
                tr("main.main_window.description_name"),
                tr("main.main_window.signatures"),
                tr("main.main_window.score"),
                tr("main.main_window.status"),
            ]
        )
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
        self.signature_file_count = QLabel(tr("main.main_window.0_files"))
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
        model_layout.addWidget(self._action_button(self.act_compare))
        model_layout.addWidget(self._action_button(self.act_process, "primary"))
        signature_layout.addWidget(model_bar)
        self.signature_layout = signature_layout
        history_bar = QHBoxLayout()
        history_bar.addWidget(QLabel(tr("main.main_window.run_results")))
        self.signature_runs = QComboBox()
        self.signature_runs.setMinimumContentsLength(25)
        self.signature_runs.currentIndexChanged.connect(self._show_signature_run)
        history_bar.addWidget(self.signature_runs, 1)
        history_bar.addWidget(QLabel(tr("main.main_window.the_report_includes_all_runs_until_the")))
        signature_layout.addLayout(history_bar)
        self.signature_comparison = QLabel()
        self.signature_comparison.setTextFormat(Qt.TextFormat.PlainText)
        self.signature_comparison.setWordWrap(True)
        signature_layout.addWidget(self.signature_comparison)
        signature_layout.addWidget(splitter, 1)
        self.mode_tabs = QTabWidget()
        self.mode_tabs.addTab(signature_page, tr("main.main_window.signature_detection"))
        self.classification = ClassificationPanel(self)
        self.mode_tabs.addTab(self.classification, tr("main.main_window.document_classification"))
        self.classification.busy_changed.connect(self._classification_busy_changed)
        self.classification.settings_changed.connect(self._reload_config)
        self.classification.files_moved.connect(self._files_moved)
        self.mode_tabs.currentChanged.connect(self._mode_changed)
        app_controls = QWidget()
        controls_layout = QHBoxLayout(app_controls)
        controls_layout.setContentsMargins(8, 0, 8, 0)
        language_label = QLabel(tr("main.language"))
        controls_layout.addWidget(language_label)
        self.language_combo = QComboBox()
        self.language_combo.addItem(tr("main.language_polish"), "pl")
        self.language_combo.addItem(tr("main.language_english"), "en")
        self.language_combo.setCurrentIndex(self.language_combo.findData(self._config.language))
        self.language_combo.setAccessibleName(tr("main.language"))
        language_label.setBuddy(self.language_combo)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        controls_layout.addWidget(self.language_combo)
        controls_layout.addWidget(self._action_button(self.act_about, "quiet"))
        self.mode_tabs.setCornerWidget(app_controls)
        self.setCentralWidget(self.mode_tabs)

    def _on_language_changed(self, _index: int) -> None:
        config = AppConfig.load()
        language = self.language_combo.currentData()
        if language == config.language:
            return
        previous_language = config.language
        config.language = language
        try:
            config.save()
        except OSError as exc:
            with QSignalBlocker(self.language_combo):
                self.language_combo.setCurrentIndex(
                    self.language_combo.findData(previous_language)
                )
            QMessageBox.warning(self, tr("main.language"),
                                tr("main.language_save_failed", error=exc))
            return
        self._config = config

    def _files_moved(self, moved: dict[Path, Path]) -> None:
        self._files = [moved.get(path, path) for path in self._files]
        results = list(self._results.values())
        for run in self._signature_runs:
            results += run.results
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
        self.status_label = QLabel(tr("main.main_window.ai_connection_not_checked"))
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
            tr(
                "main.main_window.preparation_s_loading_s_inference_s_total",
                arg0=preparation,
                arg1=loading,
                arg2=inference,
                arg3=total,
            )
        )

    def _refresh_online_badge(self) -> None:
        """Plakietka „model online" jest widoczna, gdy dostawca AI nie jest lokalny."""
        cfg = self._config
        self.online_badge.setVisible(
            not processing_is_local(cfg.provider, cfg.api_base_url)
            or (cfg.provider == "ollama" and cfg.ollama_model.lower().endswith("cloud"))
        )
        provider = "Ollama" if cfg.provider == "ollama" else tr("main.main_window.ai_provider")
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
            self,
            tr("main.main_window.choose_documents"),
            self._config.last_dir,
            _file_dialog_filter(),
        )
        if files:
            self._remember_dir(Path(files[0]).parent)
            self._add_documents([Path(f) for f in files])

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, tr("main.main_window.choose_a_document_folder"), self._config.last_dir
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
            self.status_label.setText(tr("main.main_window.no_new_supported_documents_found"))
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
            self.table.setItem(row, _COL_STATUS, QTableWidgetItem(tr("main.main_window.pending")))
        self._files.extend(new_files)
        self._left_stack.setCurrentIndex(1)
        self.status_label.setText(tr("main.main_window.queued_files", arg0=len(self._files)))
        self._update_action_states()

    def _on_process(self) -> None:
        if self._is_busy() or not self._files:
            return
        if not self._ensure_ai_ready():
            return
        if not self._confirm_batch_risk():
            self.status_label.setText(tr("main.main_window.analysis_was_not_started"))
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
            QMessageBox.critical(self, tr("main.main_window.ai_settings_112"), str(exc))
            return
        self._pending_model = model
        self.status_label.setText(tr("main.main_window.checking_ai_service_and_model_availability"))
        self._preflight_worker = ConnectionTestWorker(model, self)
        self._preflight_worker.finished_with_result.connect(self._on_preflight_result)
        self._preflight_worker.finished.connect(self._on_preflight_finished)
        self._preflight_worker.start()
        self._update_action_states()

    def _on_compare(self) -> None:
        if self._is_busy() or not self._files:
            return
        configs = [replace(self._config, provider=provider) for provider in ("ollama", "vjev")]
        remote_targets = [
            cfg.api_base_url
            for cfg in configs
            if not processing_is_local(
                cfg.provider,
                cfg.api_base_url,
                cfg.ollama_model,
            )
        ]
        dialog = BatchRiskDialog(
            self._config,
            len(self._files),
            self,
            remote_targets=remote_targets,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        worker = SignatureComparisonWorker(list(self._files), configs)
        self._worker = worker
        worker.model_started.connect(self._on_comparison_model_started)
        worker.file_started.connect(self._on_file_started)
        worker.file_done.connect(self._on_file_done)
        worker.batch_done.connect(self._on_batch_done)
        worker.finished.connect(self._on_worker_finished)
        worker.start()
        self._update_action_states()

    def _on_comparison_model_started(self, name: str) -> None:
        self._preflight_started = time.perf_counter()
        self._batch_started = time.monotonic()
        self._preflight_loading = 0
        self._last_batch = None
        self._results.clear()
        self._show_details_placeholder()
        for row in range(self.table.rowCount()):
            for column in (_COL_TITLE, _COL_SIGNATURES, _COL_CONFIDENCE):
                self._cell(row, column).setText("")
            self._set_status_cell(row, tr("main.main_window.pending"), _GRAY)
        self.progress.setRange(0, len(self._files))
        self.progress.setValue(0)
        self._signature_timer.start(200)
        self.status_label.setText(
            tr("main.main_window.comparison_checking_and_starting_the_model", arg0=name)
        )

    def _show_signature_run(self, index: int) -> None:
        if self._is_busy() or not 0 <= index < len(self._signature_runs):
            return
        batch = self._signature_runs[index]
        self._last_batch = batch
        by_path = {result.path: result for result in batch.results}
        self._results.clear()
        for row, path in enumerate(self._files):
            result = by_path.get(path)
            if result is not None:
                self._results[row] = result
                self._fill_result_row(row, result)
            else:
                for column in (_COL_TITLE, _COL_SIGNATURES, _COL_CONFIDENCE):
                    self._cell(row, column).setText("")
                self._set_status_cell(row, tr("main.main_window.no_result"), _GRAY)
        self._refresh_signature_time()
        self._on_selection_changed()

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
            self._set_status_cell(row, tr("main.main_window.pending"), _GRAY)
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
            QMessageBox.critical(self, tr("main.main_window.ai_service_unavailable"), detail)
            self.status_label.setText(tr("main.main_window.ai_service_unavailable_check_settings"))
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
                tr("main.main_window.missing_api_key"),
                tr("main.main_window.no_api_key_is_saved_for_the"),
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._on_settings()
            return False
        return True

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText(
                tr("main.main_window.cancelling_waiting_for_the_current_page_to")
            )
            self.act_cancel.setEnabled(False)

    def _on_clear(self) -> None:
        if self._is_busy():
            return
        self._files.clear()
        self._signature_runs.clear()
        self.signature_runs.clear()
        self.signature_comparison.clear()
        self._results.clear()
        self._last_batch = None
        self.table.setRowCount(0)
        self._left_stack.setCurrentIndex(0)
        self._show_details_placeholder()
        self.progress.setValue(0)
        self.signature_elapsed.clear()
        self.status_label.setText(tr("main.main_window.add_documents"))
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
            self.status_label.setText(tr("main.main_window.ai_settings_saved"))
        else:
            # Dialog mógł zmodyfikować obiekt konfiguracji (np. test połączenia)
            # bez zapisu — wracamy do stanu z dysku.
            self._config = AppConfig.load()
        self._refresh_online_badge()

    def _on_export(self) -> None:
        if not self._signature_runs:
            QMessageBox.information(
                self,
                tr("main.main_window.report"),
                tr("main.main_window.process_documents_first_the_report_is_created"),
            )
            return
        answer = QMessageBox.question(
            self,
            tr("main.main_window.report_confidentiality"),
            tr("main.main_window.the_report_contains_document_names_and_information"),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        path_str, selected_filter = QFileDialog.getSaveFileName(
            self,
            tr("main.main_window.save_report_51"),
            str(Path(self._config.last_dir or ".") / tr("main.main_window.signature_report_html")),
            tr("main.main_window.html_report_html_csv_report_csv"),
        )
        if not path_str:
            return
        path = Path(path_str)
        self._remember_dir(path.parent)
        try:
            if "CSV" in selected_filter or path.suffix.lower() == ".csv":
                write_csv(path, self._signature_runs)
            else:
                write_html(path, self._signature_runs)
        except OSError as exc:
            QMessageBox.critical(
                self,
                tr("main.main_window.report"),
                tr("main.main_window.could_not_save_the_report", arg0=exc),
            )
            return
        self.status_label.setText(tr("main.main_window.report_saved", arg0=path))

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            tr("main.main_window.about"),
            tr(
                "main.main_window.version_two_separate_workspaces_classifying_pdf_text",
                arg0=APP_DISPLAY_NAME,
                arg1=__version__,
            ),
        )

    # -- zdarzenia wątku roboczego --------------------------------------------

    def _on_file_started(self, index: int, total: int, name: str) -> None:
        eta = self._format_eta(index, total)
        self.status_label.setText(
            tr("main.main_window.processing", arg0=index + 1, arg1=total, arg2=name, arg3=eta)
        )
        self._set_status_cell(index, tr("main.main_window.analyzing"), _BLUE)
        self.table.scrollToItem(self._cell(index, _COL_FILE))

    def _on_file_done(self, index: int, result: DocumentResult) -> None:
        self._results[index] = result
        self.progress.setValue(index + 1)
        self._fill_result_row(index, result)
        selected = self.table.currentRow()
        if selected == index:
            self._show_details(result)

    def _on_batch_done(self, batch: BatchResult) -> None:
        if not batch.analysis_settings:
            batch.analysis_settings = signature_settings(self._config)
        self._last_batch = batch
        self._signature_runs.append(batch)
        self.signature_runs.blockSignals(True)
        self.signature_runs.addItem(f"{len(self._signature_runs)}. {batch.model_name}")
        self.signature_runs.setCurrentIndex(len(self._signature_runs) - 1)
        self.signature_runs.blockSignals(False)
        self.signature_comparison.setText(
            "\n".join(
                tr(
                    "main.main_window.preparation_s_loading_s_inference_s_total_121",
                    arg0=i,
                    arg1=run.model_name,
                    arg2=run.preparation_s,
                    arg3=run.loading_s,
                    arg4=run.inference_s,
                    arg5=run.duration_s,
                )
                for i, run in enumerate(self._signature_runs, 1)
            )
        )
        self._signature_timer.stop()
        self._refresh_signature_time()
        self.progress.setValue(self.progress.maximum())
        summary = tr(
            "main.main_window.finished_files_in_s_with_signatures_errors",
            arg0=len(batch.results),
            arg1=batch.duration_s,
            arg2=batch.signed_count,
            arg3=batch.error_count,
        )
        self.status_label.setText(summary)
        # Uzupełnij wiersze anulowane (worker nie wysłał dla nich file_done).
        for index, result in enumerate(batch.results):
            self._results[index] = result
            self._fill_result_row(index, result)
        if (
            batch.abort_error
            and not self._close_when_finished
            and not isinstance(self._worker, SignatureComparisonWorker)
        ):
            QMessageBox.critical(
                self,
                tr("main.main_window.processing_interrupted"),
                repair_instructions(batch.abort_error, self._config.provider),
            )
        self._update_action_states()

    def _on_worker_finished(self) -> None:
        self._signature_timer.stop()
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
            raise RuntimeError(tr("main.main_window.missing_table_cell", arg0=row, arg1=col))
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
                    tr("main.main_window.highest_probability_of_signature_presence_across_analyzed")
                )
            self._set_status_cell(
                row, "HITL" if result.hitl else "OK", QColor("#946000") if result.hitl else _GREEN
            )
            self._cell(row, _COL_STATUS).setToolTip(result.review_summary)
            signatures_item.setToolTip(result.review_summary)
            if result.hitl:
                signatures_item.setForeground(QColor("#946000"))
        elif result.status == DocumentStatus.ERROR:
            self._set_status_cell(row, tr("main.main_window.error"), _RED)
            self._cell(row, _COL_STATUS).setToolTip(
                repair_instructions(result.error or "", self._config.provider)
            )
        elif result.status == DocumentStatus.CANCELLED:
            self._set_status_cell(row, tr("main.main_window.cancelled"), _GRAY)

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
        return tr("main.main_window.about_remaining", arg0=minutes, arg1=seconds)

    def _is_processing(self) -> bool:
        return self._worker is not None

    def _is_preflighting(self) -> bool:
        return self._preflight_worker is not None

    def _is_busy(self) -> bool:
        return self._is_processing() or self._is_preflighting() or self.classification.is_busy()

    def _update_action_states(self) -> None:
        processing = self._is_processing()
        busy = self._is_busy()
        self.mode_tabs.setTabEnabled(0, not self.classification.is_busy())
        self.mode_tabs.setTabEnabled(1, not (processing or self._is_preflighting()))
        self.signature_file_count.setText(tr("main.main_window.files", arg0=len(self._files)))
        has_files = bool(self._files)
        self.act_add_files.setEnabled(not busy)
        self.act_add_folder.setEnabled(not busy)
        self.act_process.setEnabled(not busy and has_files)
        self.act_compare.setEnabled(not busy and has_files)
        self.signature_runs.setEnabled(not busy and bool(self._signature_runs))
        self.act_cancel.setEnabled(processing)
        self.act_clear.setEnabled(not busy and has_files)
        self.act_components.setEnabled(not self._is_busy())
        self.act_settings.setEnabled(not busy)
        self.language_combo.setEnabled(not busy)
        self.act_export.setEnabled(not busy and bool(self._signature_runs))

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
        label = QLabel(tr("main.main_window.select_a_document"))
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
        open_source = QPushButton(tr("main.main_window.open_source_document"))
        open_source.clicked.connect(lambda: self._open_source_document(result.path))
        self.details_layout.addWidget(open_source)

        if result.status == DocumentStatus.ERROR:
            error = QLabel(
                repair_instructions(
                    result.error or tr("main.main_window.document_error"), self._config.provider
                )
            )
            error.setTextFormat(Qt.TextFormat.PlainText)
            error.setWordWrap(True)
            error.setStyleSheet("color: #c62828;")
            self.details_layout.addWidget(error)
            return
        if result.status == DocumentStatus.CANCELLED:
            self.details_layout.addWidget(QLabel(tr("main.main_window.file_skipped_cancelled")))
            return

        meta = QLabel(
            tr(
                "main.main_window.analyzed_pages_in_s",
                arg0=result.pages_analyzed,
                arg1=result.page_count,
                arg2=result.duration_s,
            )
        )
        meta.setStyleSheet("color: #666;")
        self.details_layout.addWidget(meta)

        if result.pages_analyzed < result.page_count:
            partial = QLabel(tr("main.main_window.only_part_of_the_document_was_analyzed"))
            partial.setWordWrap(True)
            self.details_layout.addWidget(partial)
        if result.hitl:
            review = QLabel(tr("main.main_window.review_document") + result.review_summary)
            review.setTextFormat(Qt.TextFormat.PlainText)
            review.setWordWrap(True)
            review.setStyleSheet("color: #946000;")
            self.details_layout.addWidget(review)
        if result.page_signature_probabilities and not result.is_signed:
            values = "; ".join(
                tr("main.main_window.page", arg0=page, arg1=probability * 100)
                for page, probability in result.page_signature_probabilities.items()
            )
            probability_label = QLabel(
                tr("main.main_window.signature_presence_probability") + values
            )
            probability_label.setTextFormat(Qt.TextFormat.PlainText)
            probability_label.setWordWrap(True)
            self.details_layout.addWidget(probability_label)

        if not result.findings:
            none_label = QLabel(tr("main.main_window.no_signatures_detected"))
            self.details_layout.addWidget(none_label)
            return

        header = QLabel(tr("main.main_window.detected", arg0=result.kinds_summary))
        header.setWordWrap(True)
        self.details_layout.addWidget(header)
        for finding in result.findings:
            self.details_layout.addWidget(self._finding_widget(finding))

    def _finding_widget(self, finding) -> QWidget:  # type: ignore[no-untyped-def]
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        caption = QLabel(
            tr(
                "main.main_window.page_confidence",
                arg0=finding.kind.label_pl.capitalize(),
                arg1=finding.page,
                arg2=finding.confidence,
            )
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
                self,
                tr("main.main_window.source_document"),
                tr("main.main_window.could_not_open_the_document_in_the"),
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
                tr("main.main_window.checking_ai_service"),
                tr("main.main_window.wait_for_the_check_to_finish_and"),
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._close_when_finished = True
                self.status_label.setText(
                    tr("main.main_window.closing_after_the_ai_service_check_finishes")
                )
                self.setEnabled(False)
            event.ignore()
            return
        if self._is_processing():
            if self._close_when_finished:
                event.ignore()
                return
            answer = QMessageBox.question(
                self,
                tr("main.main_window.processing_in_progress"),
                tr("main.main_window.documents_are_being_analyzed_cancel_and_close"),
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self._worker is not None:
                self._worker.cancel()
                self._close_when_finished = True
                self.status_label.setText(
                    tr("main.main_window.closing_after_the_current_ai_request_finishes")
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
        self.setToolTip(tr("main.main_window.click_to_enlarge"))
        self.setStyleSheet("border: 1px solid #ccc; background: white; padding: 2px;")

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def] # noqa: N802 — API Qt
        dialog = QDialog(self.window())
        dialog.setWindowTitle(tr("main.main_window.signature_crop"))
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
        row.addWidget(QLabel(tr("main.main_window.online_model")))
        self.setToolTip(tr("main.main_window.the_active_ai_service_runs_outside_this"))


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
