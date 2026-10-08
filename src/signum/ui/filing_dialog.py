"""Review destination paths and file a classified collection in a worker thread."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from signum.core.classification import ClassificationBatch
from signum.core.collection_session import journal_path
from signum.core.filing import (
    FilingEntry,
    FilingMode,
    FilingPlan,
    FilingResult,
    build_filing_plan,
    execute_filing,
)


class FilingWorker(QThread):
    progress = Signal(int, object, str)
    completed = Signal(object)

    def __init__(self, plan: FilingPlan, parent: QWidget) -> None:
        super().__init__(parent)
        self.plan = plan
        self.cancel_event = threading.Event()

    def run(self) -> None:
        result = execute_filing(self.plan, self.cancel_event, self.progress.emit, journal_path())
        self.completed.emit(result)


class FilingDialog(QDialog):
    filed = Signal(object)
    busy_changed = Signal(bool)

    def __init__(
        self, files: list[Path], batch: ClassificationBatch, mode: FilingMode,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.files, self.batch, self.mode = files, batch, mode
        self.plan: FilingPlan | None = None
        self.worker: FilingWorker | None = None
        self.outcome: FilingResult | None = None
        self._done_count = 0
        self.setWindowTitle("Przenieś do folderów" if mode == "move" else "Skopiuj do folderów")
        self.resize(900, 560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.run_choice = QComboBox()
        runs = list(dict.fromkeys((row.model, row.repeat) for row in batch.rows))
        if len(runs) > 1:
            self.run_choice.addItem("Wybierz wynik klasyfikacji…", None)
        for model, repeat in runs:
            label = batch.model_labels.get(model, model)
            self.run_choice.addItem(f"{label} · przejście {repeat + 1}", (model, repeat))
        self.run_choice.currentIndexChanged.connect(self.refresh_plan)
        form.addRow("Etykiety z:", self.run_choice)
        destination = QHBoxLayout()
        self.destination = QLineEdit()
        self.destination.setPlaceholderText("Folder docelowy")
        self.destination.editingFinished.connect(self.refresh_plan)
        self.destination.textChanged.connect(self._invalidate)
        self.browse = QPushButton("Przeglądaj…")
        self.browse.clicked.connect(self._browse)
        destination.addWidget(self.destination, 1)
        destination.addWidget(self.browse)
        form.addRow("Zapisz w:", destination)
        layout.addLayout(form)
        note = QLabel(
            "Oryginały zostaną przeniesione. Istniejące pliki nie będą nadpisane."
            if mode == "move" else
            "Oryginały pozostaną na miejscu. Istniejące pliki nie będą nadpisane."
        )
        note.setProperty("role", "muted")
        layout.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Dokument", "Folder / plik docelowy", "Stan"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(29)
        self.table.setShowGrid(False)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(2, 230)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.summary = QLabel("Wybierz folder docelowy.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.open_folder = QPushButton("Otwórz folder")
        self.open_folder.clicked.connect(self._open_folder)
        self.open_folder.hide()
        buttons.addWidget(self.open_folder)
        buttons.addStretch()
        self.cancel_button = QPushButton("Anuluj")
        self.cancel_button.clicked.connect(self.reject)
        self.execute_button = QPushButton("Przenieś" if mode == "move" else "Skopiuj")
        self.execute_button.setProperty("role", "primary")
        self.execute_button.setEnabled(False)
        self.execute_button.clicked.connect(self._execute)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.execute_button)
        layout.addLayout(buttons)

    def _invalidate(self) -> None:
        self.plan = None
        self.table.setRowCount(0)
        self.execute_button.setEnabled(False)
        self.summary.setText("Wybierz folder docelowy i wynik klasyfikacji.")

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder docelowy", self.destination.text())
        if path:
            self.destination.setText(path)
            self.refresh_plan()

    def refresh_plan(self) -> None:
        if self.worker is not None or self.outcome is not None:
            return
        self._invalidate()
        run = self.run_choice.currentData()
        if not self.destination.text().strip() or run is None:
            return
        try:
            self.plan = build_filing_plan(
                self.files, self.batch, run[0], run[1], Path(self.destination.text()), self.mode,
            )
        except (OSError, ValueError) as exc:
            self.summary.setText(str(exc))
            return
        self.table.setRowCount(len(self.plan.entries))
        for index, entry in enumerate(self.plan.entries):
            relative = str(entry.target.relative_to(self.plan.root)) if entry.target else "—"
            for column, value in enumerate((entry.source.name, relative, entry.skip or "Gotowy")):
                item = QTableWidgetItem(value)
                item.setToolTip(str(entry.source) if column == 0 else value)
                self.table.setItem(index, column, item)
        self.summary.setText(
            f"Do {'przeniesienia' if self.mode == 'move' else 'skopiowania'}: {self.plan.ready}"
            f"   ·   Pominięte: {len(self.plan.entries) - self.plan.ready}"
        )
        self.execute_button.setEnabled(bool(self.plan.ready))

    def _execute(self) -> None:
        if self.plan is None or not self.plan.ready or self.worker is not None:
            return
        for widget in (self.run_choice, self.destination, self.browse, self.execute_button):
            widget.setEnabled(False)
        self.progress.setRange(0, self.plan.ready)
        self.progress.setValue(0)
        self.progress.show()
        self.worker = FilingWorker(self.plan, self)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._completed)
        self.worker.finished.connect(self._finished)
        self.summary.setText("Przenoszenie…" if self.mode == "move" else "Kopiowanie…")
        self.busy_changed.emit(True)
        self.worker.start()

    def _progress(self, index: int, entry: FilingEntry, status: str) -> None:
        self._done_count += 1
        self.progress.setValue(self._done_count)
        item = QTableWidgetItem(status)
        item.setToolTip(status)
        self.table.setItem(index, 2, item)
        self.table.scrollToItem(item)

    def _completed(self, result: FilingResult) -> None:
        self.outcome = result
        self.filed.emit(result)
        verb = "Przeniesiono" if self.mode == "move" else "Skopiowano"
        skipped = sum(bool(e.skip) for e in self.plan.entries) if self.plan else 0
        self.summary.setText(
            ("Anulowano. " if result.cancelled else "")
            + f"{verb}: {len(result.completed)}   ·   Błędy: {len(result.errors)}"
            + f"   ·   Pominięte: {skipped}"
        )
        if result.cancelled and self.plan:
            attempted = {e.source for e in result.completed} | {e.source for e, _ in result.errors}
            for i, entry in enumerate(self.plan.entries):
                if not entry.skip and entry.source not in attempted:
                    self.table.setItem(i, 2, QTableWidgetItem("Anulowano"))
        self.cancel_button.setText("Zamknij")
        self.cancel_button.setEnabled(True)
        self.open_folder.show()

    def _finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        self.busy_changed.emit(False)

    def _open_folder(self) -> None:
        if self.plan:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.plan.root)))

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel_event.set()
            self.summary.setText("Anulowanie…")
            self.cancel_button.setEnabled(False)

    def reject(self) -> None:
        if self.worker is not None:
            self.cancel()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.worker is not None:
            self.cancel()
            event.ignore()
        else:
            super().closeEvent(event)
