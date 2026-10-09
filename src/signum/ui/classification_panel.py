"""Independent categorization UI with editable categories and configurable model comparisons."""

from __future__ import annotations

import json
import random
import shutil
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from signum.ai.model_profiles import ModelProfile, dump_profiles, load_profiles
from signum.config import AppConfig
from signum.core.classification import (
    DEFAULT_CATEGORIES,
    DEFAULT_INSTRUCTIONS,
    LEGACY_DEFAULT_INSTRUCTIONS,
    LEGACY_ENGLISH_INSTRUCTIONS,
    ClassificationBatch,
    ClassificationRow,
    confirm_categories,
    make_question,
    write_classification_report,
)
from signum.core.classification_calibration import refresh_review_policy
from signum.core.collection_session import (
    journal_path,
    load_collection,
    save_collection,
    session_path,
)
from signum.core.decision import MAX_CLASSIFICATION_LABELS
from signum.core.discovery import collect_documents
from signum.core.file_identity import fingerprint
from signum.core.filing import FilingMode, FilingResult
from signum.local_components import repair_instructions
from signum.ui.batch_risk_dialog import BatchRiskDialog
from signum.ui.classification_worker import ClassificationWorker
from signum.ui.components_dialog import ComponentsDialog
from signum.ui.filing_dialog import FilingDialog
from signum.ui.models_dialog import ModelsDialog
from signum.ui.theme import CategoryDelegate


def _label(text: str, role: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty("role", role)
    return label


class ModelMetricCard(QWidget):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("role", "metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 10, 13, 10)
        layout.setSpacing(3)
        layout.addWidget(_label(title, "heading"))
        layout.addWidget(_label(subtitle))
        self.value = _label("—", "metricValue")
        self.caption = _label("Czeka na pomiar")
        self.detail = _label(" ")
        for label in (self.value, self.caption, self.detail):
            layout.addWidget(label)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)



class LabelReviewDialog(QDialog):
    def __init__(self, row: ClassificationRow, labels: list[str], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sprawdź etykiety dokumentu")
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(row.path.name, "heading"))
        hint = _label("\n".join(row.review_reasons) or "Wybierz wszystkie pasujące etykiety.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.labels = QListWidget()
        for name in sorted(labels, key=lambda name: -row.label_scores.get(name, -1)):
            score = row.label_scores.get(name)
            item = QListWidgetItem(name + (f" — {score:.3f}" if score is not None else ""))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setCheckState(Qt.CheckState.Checked if name in row.selected_categories
                               else Qt.CheckState.Unchecked)
            self.labels.addItem(item)
        layout.addWidget(self.labels)
        self.selection_hint = _label("")
        layout.addWidget(self.selection_hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("Zapisz sprawdzone etykiety")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.labels.itemChanged.connect(self._update_selection_limit)
        self._update_selection_limit()

    def _update_selection_limit(self) -> None:
        count = len(self.selected_labels())
        allowed = count <= MAX_CLASSIFICATION_LABELS
        self.save_button.setEnabled(allowed)
        self.selection_hint.setText(
            f"Wybrano {count}/{MAX_CLASSIFICATION_LABELS}. "
            + ("Możesz też pozostawić listę pustą." if allowed
               else "Odznacz nadmiarowe etykiety, aby zapisać wynik.")
        )

    def selected_labels(self) -> list[str]:
        return [self.labels.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.labels.count())
                if self.labels.item(i).checkState() == Qt.CheckState.Checked]

class ClassificationPanel(QWidget):
    busy_changed = Signal(bool)
    settings_changed = Signal()
    files_moved = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.files: list[Path] = []
        self.rows: list[ClassificationRow] = []
        self.batch: ClassificationBatch | None = None
        self.worker: ClassificationWorker | None = None
        self.started = 0.0
        self._filing_busy = False
        self._filing_dialog: FilingDialog | None = None
        self._run_category_colors: dict[str, int] = {}
        self._expected_rows = 0
        self.profiles: list[ModelProfile] = []
        self._timing_batch: ClassificationBatch | None = None
        self._run_labels: dict[str, str] = {}
        self._loading = True
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_preferences)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._refresh_elapsed)
        self._session_path = session_path()
        self._checkpoint_timer = QTimer(self)
        self._checkpoint_timer.setSingleShot(True)
        self._checkpoint_timer.timeout.connect(self._persist_collection)
        self._restoring = False
        self._checkpoint_disabled = False
        self._build_ui()
        self._load_preferences()
        self._restore_collection()
        self._loading = False

    def _build_ui(self) -> None:
        self.setObjectName("classificationPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 6)
        layout.setSpacing(6)

        file_bar = QWidget()
        file_bar.setProperty("role", "commandBar")
        top = QHBoxLayout(file_bar)
        top.setContentsMargins(4, 7, 4, 7)
        top.setSpacing(4)
        self.add_button = QPushButton("Dodaj PDF-y…")
        self.add_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self.add_button.clicked.connect(self._add_dialog)
        self.folder_button = QPushButton("Dodaj folder…")
        self.folder_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.folder_button.clicked.connect(self._folder_dialog)
        self.copy_button = QPushButton("Skopiuj do folderów…")
        self.copy_button.clicked.connect(lambda: self._file_collection("copy"))
        self.move_button = QPushButton("Przenieś do folderów…")
        self.move_button.clicked.connect(lambda: self._file_collection("move"))
        self.copy_button.setEnabled(False)
        self.move_button.setEnabled(False)
        self.sample_button = QPushButton("Losuj 100 z folderu…")
        self.sample_button.clicked.connect(self._sample_dialog)
        self.benchmark_button = QPushButton("Zestaw lokalny…")
        self.benchmark_button.clicked.connect(self._benchmark_dialog)
        # Benchmark inputs remain available, without occupying the main command surface.
        self.sample_button.hide()
        self.benchmark_button.hide()
        self.more_button = QPushButton("Więcej")
        more = QMenu(self.more_button)
        more.addAction("Losuj 100 z folderu…", self._sample_dialog)
        more.addAction("Otwórz zestaw lokalny…", self._benchmark_dialog)
        more.addAction("Dziennik operacji", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(journal_path()))
        ))
        self.more_button.setMenu(more)
        self.clear_button = QPushButton("Wyczyść listę")
        self.clear_button.setProperty("role", "quiet")
        self.clear_button.clicked.connect(self.clear)
        for button in (self.add_button, self.folder_button, self.copy_button, self.move_button):
            top.addWidget(button)
        top.addStretch(1)
        self.file_count = _label("0 PDF")
        top.addWidget(self.file_count)
        top.addWidget(self.clear_button)
        top.addWidget(self.more_button)
        layout.addWidget(file_bar)

        model_row = QHBoxLayout()
        model_row.addWidget(_label("Model:"))
        self.model = QComboBox()
        self.model.setMinimumWidth(180)
        self.model.currentIndexChanged.connect(self._model_changed)
        model_row.addWidget(self.model, 1)
        self.connections_button = QPushButton("Ustawienia AI…")
        self.connections_button.clicked.connect(self._connections)
        self.components_button = QPushButton("Składniki AI…")
        self.components_button.clicked.connect(self._components)
        model_row.addWidget(self.connections_button)
        model_row.addWidget(self.components_button)
        self.repeats = QSpinBox()
        self.repeats.setRange(1, 10)
        self.repeats.setValue(1)
        model_row.addWidget(_label("Przejścia:"))
        model_row.addWidget(self.repeats)
        self.cancel_button = QPushButton("Anuluj")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.start_button = QPushButton("Kategoryzuj")
        self.start_button.setProperty("role", "primary")
        self.start_button.clicked.connect(self.start)
        model_row.addWidget(self.cancel_button)
        model_row.addWidget(self.start_button)
        layout.addLayout(model_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(5)
        editor = QWidget()
        editor.setProperty("role", "card")
        editor.setMinimumWidth(260)
        edit_layout = QVBoxLayout(editor)
        edit_layout.setContentsMargins(8, 8, 8, 8)
        edit_layout.setSpacing(6)
        self.categories = QTableWidget(12, 2)
        heading = QHBoxLayout()
        heading.addWidget(_label("Etykiety · maks. 3", "heading"), 1)
        descriptions = QPushButton("Opisy")
        descriptions.setProperty("role", "quiet")
        descriptions.setCheckable(True)
        descriptions.toggled.connect(lambda shown: self.categories.setColumnHidden(1, not shown))
        heading.addWidget(descriptions)
        self.examples_button = QPushButton("Przykładowe")
        self.examples_button.setProperty("role", "quiet")
        self.examples_button.clicked.connect(self._restore_examples)
        heading.addWidget(self.examples_button)
        edit_layout.addLayout(heading)
        self.categories.setHorizontalHeaderLabels(["Etykieta", "Opis"])
        self.categories.setToolTip("Od 2 do 12 etykiet. Dwukrotne kliknięcie lub F2: edycja.")
        self.categories.verticalHeader().hide()
        self.categories.verticalHeader().setDefaultSectionSize(30)
        self.categories.setShowGrid(False)
        self.categories.setItemDelegateForColumn(0, CategoryDelegate(self.categories))
        self.categories.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.categories.setColumnWidth(1, 180)
        self.categories.setColumnHidden(1, True)
        self.categories.itemChanged.connect(self._category_edited)
        edit_layout.addWidget(self.categories, 1)
        self.prompt_toggle = QPushButton("Instrukcja klasyfikacji")
        self.prompt_toggle.setProperty("role", "quiet")
        self.prompt_toggle.setCheckable(True)
        self.prompt_toggle.toggled.connect(self._toggle_prompt)
        edit_layout.addWidget(self.prompt_toggle)
        self.prompt = QPlainTextEdit()
        self.prompt.setFixedHeight(140)
        self.prompt.setVisible(False)
        self.prompt.textChanged.connect(self._schedule_save)
        edit_layout.addWidget(self.prompt)
        splitter.addWidget(editor)

        results = QWidget()
        results.setProperty("role", "card")
        results.setMinimumWidth(520)
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(8, 8, 8, 8)
        results_layout.setSpacing(6)
        result_heading = QHBoxLayout()
        result_heading.addWidget(_label("Dokumenty", "heading"), 1)
        self.table: QTableWidget
        self.correct_button = QPushButton("Sprawdź etykiety…")
        self.correct_button.setEnabled(False)
        self.correct_button.clicked.connect(lambda: self._correct_category(self.table.currentRow()))
        result_heading.addWidget(self.correct_button)
        self.measurements_button = QPushButton("Pomiary")
        self.measurements_button.setProperty("role", "quiet")
        self.measurements_button.setCheckable(True)
        self.measurements_button.toggled.connect(self._toggle_measurements)
        result_heading.addWidget(self.measurements_button)
        self.export_button = QPushButton("Zapisz wyniki…")
        self.export_button.setProperty("role", "quiet")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        result_heading.addWidget(self.export_button)
        results_layout.addLayout(result_heading)
        self.metrics_scroll = QScrollArea()
        self.metrics_scroll.setWidgetResizable(True)
        self.metrics_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.metrics_scroll.setFixedHeight(157)
        self.metrics_host = QWidget()
        self.metrics_layout = QHBoxLayout(self.metrics_host)
        self.metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metrics_scroll.setWidget(self.metrics_host)
        self.metric_cards: dict[str, ModelMetricCard] = {}
        self.metrics_scroll.hide()
        results_layout.addWidget(self.metrics_scroll)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Plik", "Model / próba", "Etykiety", "Działanie", "Limit API", "Oceny", "Status"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegateForColumn(2, CategoryDelegate(self.table))
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(70)
        for col, width in {0: 175, 1: 135, 3: 80, 4: 80, 5: 75, 6: 85}.items():
            self.table.setColumnWidth(col, width)
        self.table.setColumnHidden(3, True)
        self.table.setColumnHidden(4, True)
        self.table.cellDoubleClicked.connect(self._open_document)
        self.table.itemChanged.connect(self._inclusion_changed)
        self.table.itemSelectionChanged.connect(self._update_correction_action)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._file_menu)
        self.result_stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        empty_label = _label("Przeciągnij tutaj pliki PDF")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_label)
        empty_layout.addStretch()
        self.result_stack.addWidget(empty)
        self.result_stack.addWidget(self.table)
        results_layout.addWidget(self.result_stack, 1)
        self.summary = QLabel(self)
        self.summary.hide()
        splitter.addWidget(results)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([320, 1000])
        layout.addWidget(splitter, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("Gotowy")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(36)
        layout.addWidget(self.status)
        self.elapsed = _label("")
        self.elapsed.hide()
        layout.addWidget(self.elapsed)

    def _toggle_measurements(self, shown: bool) -> None:
        self.metrics_scroll.setVisible(shown)
        self.elapsed.setVisible(shown)
        self.table.setColumnHidden(3, not shown)
        self.table.setColumnHidden(4, not shown or not any(row.wait_s for row in self.rows))

    def reload_models(self) -> None:
        selection = self.model.currentData()
        self.profiles = load_profiles(AppConfig.load())
        self._populate_models(selection)
        self._model_changed()

    def _components(self) -> None:
        if self.is_busy():
            return
        config = AppConfig.load()
        ComponentsDialog(config, self).exec()
        self.profiles = load_profiles(config)
        self._populate_models()
        self._model_changed()
        self.settings_changed.emit()

    def _toggle_prompt(self, expanded: bool) -> None:
        self.prompt.setVisible(expanded)


    def _category_edited(self, item: QTableWidgetItem) -> None:
        self.categories.blockSignals(True)
        item.setToolTip(item.text())
        if item.column() == 0:
            item.setData(Qt.ItemDataRole.UserRole, item.row())
        self.categories.blockSignals(False)
        self._schedule_save()

    def _load_preferences(self) -> None:
        config = AppConfig.load()
        categories = list(DEFAULT_CATEGORIES)
        try:
            raw = json.loads(config.classification_categories)
            if (
                isinstance(raw, list)
                and len(raw) <= 12
                and all(
                    isinstance(row, list) and len(row) == 2 and all(isinstance(v, str) for v in row)
                    for row in raw
                )
            ):
                categories = raw
        except ValueError:
            pass
        self._fill_categories(categories)
        prompt = config.classification_prompt
        self.prompt.setPlainText(
            DEFAULT_INSTRUCTIONS if prompt in (
                "", LEGACY_DEFAULT_INSTRUCTIONS, LEGACY_ENGLISH_INSTRUCTIONS
            ) else prompt
        )
        self.profiles = load_profiles(config)
        self._populate_models(config.classification_selection)
        self._model_changed()

    def _fill_categories(self, categories: list[tuple[str, str]]) -> None:
        self.categories.blockSignals(True)
        for i in range(12):
            name, description = categories[i] if i < len(categories) else ("", "")
            for col, value in enumerate((name, description)):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, i)
                self.categories.setItem(i, col, item)
        self.categories.blockSignals(False)

    def category_values(self) -> list[tuple[str, str]]:
        values = []
        for i in range(12):
            name = self.categories.item(i, 0)
            description = self.categories.item(i, 1)
            values.append(
                (
                    name.text().strip() if name else "",
                    description.text().strip() if description else "",
                )
            )
        return values

    def _restore_examples(self) -> None:
        self._fill_categories(list(DEFAULT_CATEGORIES))
        self.prompt.setPlainText(DEFAULT_INSTRUCTIONS)
        self.save_preferences()

    def _schedule_save(self) -> None:
        if not self._loading:
            self._save_timer.start(400)

    def save_preferences(self) -> None:
        if self._loading:
            return
        self._save_timer.stop()
        config = AppConfig.load()
        config.classification_categories = json.dumps(self.category_values(), ensure_ascii=False)
        text = self.prompt.toPlainText()
        config.classification_prompt = "" if text == DEFAULT_INSTRUCTIONS else text
        config.classification_models = dump_profiles(self.profiles)
        config.classification_selection = self.model.currentData() or "selected"
        try:
            config.save()
        except OSError as exc:
            self.status.setText(f"Nie udało się zapisać ustawień: {exc}")
        else:
            self.settings_changed.emit()

    def _populate_models(self, selection: str = "selected") -> None:
        self.model.blockSignals(True)
        self.model.clear()
        enabled = sum(p.enabled for p in self.profiles)
        self.model.addItem(f"Porównaj zaznaczone modele ({enabled})", "selected")
        for p in self.profiles:
            self.model.addItem(p.label, p.id)
        self.model.setCurrentIndex(max(0, self.model.findData(selection)))
        self.model.blockSignals(False)
        for card in self.metric_cards.values():
            self.metrics_layout.removeWidget(card)
            card.deleteLater()
        self.metric_cards = {}
        for profile in self.profiles:
            subtitle = (
                "Ollama"
                if profile.provider == "ollama"
                else "Lokalny runtime"
                if profile.provider == "jevk5"
                else "AI od dostawcy"
            )
            card = ModelMetricCard(profile.label, subtitle)
            card.setMinimumWidth(210)
            self.metric_cards[profile.id] = card
            self.metrics_layout.addWidget(card, 1)
        self._model_changed()

    def _selected_profiles(self) -> list[ModelProfile]:
        selected = self.model.currentData()
        return [
            p for p in self.profiles if (p.enabled if selected == "selected" else p.id == selected)
        ]

    def _model_changed(self) -> None:
        self.start_button.setText(
            "Porównaj modele" if len(self._selected_profiles()) > 1 else "Kategoryzuj"
        )
        self._refresh_summary()
        self._schedule_save()

    def _open_document(self, row: int, column: int = 0) -> None:
        if column == 6:
            status = self.table.item(row, column)
            if status is not None and status.text().startswith("Błąd"):
                QMessageBox.warning(self, "Błąd modelu — jak naprawić", status.toolTip())
                return
        item = self.table.item(row, 0)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)) and not QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(path).parent))
        ):
            QMessageBox.warning(self, "Otwieranie PDF", "Nie można otworzyć pliku ani folderu.")

    def _file_menu(self, point: QPoint) -> None:
        item = self.table.itemAt(point)
        if item is None:
            return
        file_item = self.table.item(item.row(), 0)
        if file_item is None:
            return
        path = file_item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        menu = QMenu(self)
        menu.addAction("Otwórz PDF", lambda: self._open_document(item.row()))
        menu.addAction(
            "Otwórz folder",
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent))),
        )
        action = menu.addAction("Zmień etykietę…", lambda: self._correct_category(item.row()))
        action.setEnabled(not self.is_busy())
        menu.exec(self.table.viewport().mapToGlobal(point))

    def is_busy(self) -> bool:
        return self.worker is not None or self._filing_busy

    def add_files(self, paths: list[Path]) -> None:
        if self.is_busy():
            return
        found = collect_documents(paths, recursive=True)
        existing = set(self.files)
        added = [path for path in found if path.suffix.lower() == ".pdf" and path not in existing]
        if not added:
            return
        self.files.extend(added)
        self._render_collection()
        self._persist_collection()

    def _add_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Wybierz PDF-y", "", "PDF (*.pdf)")
        self.add_files([Path(path) for path in paths])

    def _folder_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder z PDF-ami")
        if path:
            self.add_files([Path(path)])

    def _sample_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Wylosuj 100 PDF-ów z folderu")
        if path:
            found = [p for p in collect_documents([Path(path)]) if p.suffix.lower() == ".pdf"]
            self.clear()
            self.add_files(random.SystemRandom().sample(found, min(100, len(found))))
            if len(found) < 100:
                self.status.setText(f"Folder zawiera {len(found)} PDF-ów; dodano wszystkie.")

    def _benchmark_dialog(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Wybierz protocol.json zapisanego testu",
            "",
            "Protokół JSON (*.json)",
        )
        if not selected:
            return
        default = Path(selected)
        try:
            data = json.loads(default.read_text(encoding="utf-8"))
            paths = [Path(doc["path"]) for doc in data["documents"]]
            if not all(path.is_file() for path in paths):
                raise ValueError("Część PDF-ów z protokołu nie jest dostępna.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Zestaw testowy", str(exc))
            return
        self.clear()
        self.add_files(paths)
        self.status.setText(
            "Wczytano PDF-y testowe. Użyte zostaną kategorie i prompt z tego ekranu."
        )

    def clear(self) -> None:
        if self.is_busy():
            return
        self._checkpoint_timer.stop()
        self.files.clear()
        self.rows.clear()
        self.batch = None
        self.table.setRowCount(0)
        self.file_count.setText("0 PDF")
        self.result_stack.setCurrentIndex(0)
        self._run_category_colors.clear()
        self._reset_progress()
        self._refresh_summary()
        self.export_button.setEnabled(False)
        self._update_filing_actions()

        self._persist_collection()

    def _reset_progress(self) -> None:
        self._expected_rows = 0
        self._timing_batch = None
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.table.setColumnHidden(4, True)
        self.elapsed.clear()
        self.status.setText("Dodaj dokumenty" if not self.files else "Czeka na analizę")

    def start(self) -> None:
        if self.is_busy():
            return
        try:
            if not self.files:
                raise ValueError("Najpierw dodaj dokumenty PDF.")
            categories = self.category_values()
            prompt = self.prompt.toPlainText()
            make_question(categories, prompt)
        except ValueError as exc:
            QMessageBox.warning(self, "Kategoryzowanie", str(exc))
            return
        selected = self._selected_profiles()
        if not selected:
            QMessageBox.warning(self, "Ustawienia AI", "Dodaj i zaznacz przynajmniej jeden model.")
            return
        config = AppConfig.load()
        dialog = BatchRiskDialog(
            config,
            len(self.files),
            self,
            classification=True,
            remote_targets=[f"{p.label} ({p.url})" for p in selected if not p.local],
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.save_preferences()
        models = [p.id for p in selected]
        self._run_labels = {p.id: p.label for p in selected}
        self._timing_batch = None
        self.rows.clear()
        self.batch = None
        self._run_category_colors = {name: i for i, (name, _) in enumerate(categories) if name}
        self._expected_rows = len(self.files) * len(models) * self.repeats.value()
        self.progress.setRange(0, 0)
        self.table.setColumnHidden(4, True)
        self.table.setRowCount(0)
        self.result_stack.setCurrentIndex(1)
        self._refresh_summary()
        self.started = time.perf_counter()
        # Run the exact configuration shown in the confirmation, even if saving failed.
        config.classification_models = dump_profiles(self.profiles)
        self.worker = ClassificationWorker(
            config, list(self.files), categories, prompt, models, self.repeats.value()
        )
        self.worker.progress.connect(self.status.setText)
        self.worker.row_done.connect(self._row_done)
        self.worker.timing.connect(self._timing_updated)
        self.worker.batch_done.connect(self._batch_done)
        self.worker.finished.connect(self._finished)
        self._set_busy(True)
        self._elapsed_timer.start(200)
        self.worker.start()

    def _set_busy(self, busy: bool) -> None:
        for control in (
            self.correct_button,
            self.add_button,
            self.folder_button,
            self.sample_button,
            self.more_button,
            self.benchmark_button,
            self.clear_button,
            self.model,
            self.connections_button,
            self.components_button,
            self.categories,
            self.prompt,
            self.prompt_toggle,
            self.examples_button,
            self.repeats,
            self.start_button,
        ):
            control.setEnabled(not busy)
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is not None:
                flags = item.flags()
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable if busy
                              else flags | Qt.ItemFlag.ItemIsUserCheckable)
        self._update_correction_action()
        self.cancel_button.setEnabled(busy)
        self.export_button.setEnabled(not busy and self.batch is not None)
        self._update_filing_actions()
        self.busy_changed.emit(busy)

    def cancel(self) -> None:
        if self._filing_dialog is not None:
            self._filing_dialog.cancel()
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Anulowanie — czekam na zakończenie bieżącego żądania.")

    def _row_done(self, row: ClassificationRow) -> None:
        self.rows.append(row)
        index = self.table.rowCount()
        self.table.insertRow(index)
        values = [
            row.path.name,
            f"{self._model_label(row.model)} · {row.repeat + 1}",
            row.category or ("Brak etykiet" if not row.error else ""),
            f"{row.elapsed_s:.3f} s",
            f"{row.wait_s:.1f} s",
            (f"{len(row.label_scores)} ocen" if row.label_scores else
             f"{row.confidence:.1%}" if row.confidence is not None else "—"),
            "Błąd · HITL" if row.error and row.hitl else
            "Błąd" if row.error else ("HITL" if row.hitl else
                                   "Sprawdzone" if row.category_source == "user" else "OK"),
        ]
        if not self._run_category_colors:
            self._run_category_colors = {
                name: i for i, (name, _) in enumerate(self.category_values()) if name
            }
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(
                f"{value}\n{row.path}\n{row.characters} znaków tekstu"
                + (" (tekst skrócony)" if row.truncated else "")
                + (
                    "\n"
                    + repair_instructions(
                        row.error,
                        next((p.provider for p in self.profiles if p.id == row.model), ""),
                    )
                    if row.error
                    else ""
                )
            )
            detail = "\n".join(row.review_reasons)
            if col in (2, 5, 6):
                scores = "\n".join(
                    f"{name}: {score:.3f}" for name, score in row.label_scores.items()
                )
                calibration = (f"Próg: {row.threshold:.3f}; HITL ±{row.hitl_margin:.3f}"
                               if row.threshold is not None else "Brak kalibracji")
                item.setToolTip(item.toolTip() + "\n" + calibration + "\n" + scores
                                + "\n" + detail)
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, str(row.path))
                item.setData(Qt.ItemDataRole.UserRole + 1, row)
                item.setCheckState(
                    Qt.CheckState.Unchecked if row.excluded else Qt.CheckState.Checked
                )
                item.setToolTip(str(row.path) + "\nZaznaczenie: uwzględnij w porządkowaniu")
            if col == 2:
                item.setData(Qt.ItemDataRole.UserRole, self._run_category_colors.get(row.category))
            elif col == 6:
                item.setForeground(QColor(
                    "#B33B4A" if row.error else "#A86500" if row.hitl else "#14755C"
                ))
            elif col in (3, 4, 5):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(index, col, item)
        if row.wait_s:
            self.table.setColumnHidden(4, False)
        self.result_stack.setCurrentIndex(1)
        self.progress.setRange(0, max(1, self._expected_rows, len(self.rows)))
        self.progress.setValue(len(self.rows))
        self.table.scrollToBottom()
        if not self._restoring:
            self._checkpoint_timer.start(300)
        self._refresh_summary()

    def _model_label(self, model: str) -> str:
        return self._run_labels.get(model) or next(
            (p.label for p in self.profiles if p.id == model), model
        )

    def _refresh_summary(self) -> None:
        selected = {p.id for p in self._selected_profiles()}
        timings = self.batch or self._timing_batch
        for model, card in self.metric_cards.items():
            rows = [r for r in self.rows if r.model == model]
            card.set_active(bool(rows) or model in selected)
            if not rows and (timings is None or model not in timings.models):
                card.value.setText("—")
                card.caption.setText("Czeka na pomiar" if model in selected else "Niewybrany")
                card.detail.setText(" ")
                continue
            seconds = sum(r.elapsed_s for r in rows)
            load = (
                timings.setup_seconds.get(model, 0) if timings else sum(r.loading_s for r in rows)
            )
            prep = timings.preparation_s if timings else 0
            total = prep + (
                timings.model_seconds.get(model, load + seconds) if timings else load + seconds
            )
            card.value.setText(f"{total:.2f} s")
            card.caption.setText("Łącznie")
            profile = next((p for p in self.profiles if p.id == model), None)
            can_measure_load = profile and profile.local and profile.provider in {"ollama", "jevk5"}
            load_text = f"{load:.2f} s" if can_measure_load else "—"
            card.detail.setText(
                f"Tekst: {prep:.2f} s\nŁadowanie: {load_text}\nDziałanie: {seconds:.2f} s"
            )
        if timings is not None:
            self._show_timing(timings)

    def _show_timing(self, batch: ClassificationBatch) -> None:
        model_s = sum(r.elapsed_s for r in self.rows)
        self.elapsed.setText(
            f"Tekst: {batch.preparation_s:.2f} s   ·   "
            f"Ładowanie: {sum(batch.setup_seconds.values()):.2f} s   ·   "
            f"Działanie: {model_s:.2f} s   ·   "
            f"Łącznie: {batch.duration_s:.2f} s"
        )

    def _timing_updated(self, batch: ClassificationBatch) -> None:
        self._timing_batch = batch
        self._refresh_summary()

    def _refresh_elapsed(self) -> None:
        if self.batch is not None:
            self._show_timing(self.batch)
        elif self.started:
            batch = self._timing_batch or ClassificationBatch()
            batch.duration_s = time.perf_counter() - self.started
            self._show_timing(batch)

    def _batch_done(self, batch: ClassificationBatch) -> None:
        self.batch = batch
        self.progress.setRange(0, max(1, self._expected_rows, len(self.rows)))
        self.progress.setValue(len(self.rows))
        self._refresh_summary()
        errors = sum(bool(row.error) for row in batch.rows)
        self.status.setText(
            batch.error or (
                "Anulowano." if batch.cancelled
                else f"Gotowe. Błędy: {errors}. HITL: {sum(r.hitl for r in batch.rows)}."
            )
        )
        self.status.setToolTip(self.status.text())
        if batch.error:
            QMessageBox.warning(self, "Kategoryzowanie", repair_instructions(batch.error))
        elif errors:
            self.status.setText(
                self.status.text() + " Kliknij dwukrotnie Błąd, aby zobaczyć instrukcję naprawy."
            )

    def _finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self._elapsed_timer.stop()
        self._refresh_elapsed()
        self._set_busy(False)
        self._persist_collection()

    def _export(self) -> None:
        if self.batch is None:
            return
        path, selected = QFileDialog.getSaveFileName(
            self,
            "Zapisz kategorie i pomiary",
            "kategoryzowanie.csv",
            "Tabela CSV (*.csv);;Pełny raport JSON (*.json)",
        )
        if path:
            target = Path(path)
            if not target.suffix:
                target = target.with_suffix(".json" if "JSON" in selected else ".csv")
            try:
                write_classification_report(target, self.batch)
            except OSError as exc:
                QMessageBox.warning(self, "Eksport", str(exc))
            else:
                self.status.setText(f"Zapisano {target}")

    def _connections(self) -> None:
        dialog = ModelsDialog(AppConfig.load(), self.profiles, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.reload_models()
            return
        selection = self.model.currentData()
        self.profiles = dialog.profiles
        self._populate_models(selection)
        self.save_preferences()
        self._render_collection()

    def _update_filing_actions(self) -> None:
        enabled = not self.is_busy() and self.batch is not None and any(
            row.selected_categories and not row.error and not row.excluded and not row.hitl
            for row in self.batch.rows
        )
        self.copy_button.setEnabled(enabled)
        self.move_button.setEnabled(enabled)

    def _file_collection(self, mode: FilingMode) -> None:
        if self.is_busy() or self.batch is None:
            return
        dialog = FilingDialog(list(self.files), self.batch, mode, self)
        self._filing_dialog = dialog
        dialog.filed.connect(lambda result: self._apply_filing_result(result, mode))
        dialog.busy_changed.connect(self._filing_state_changed)
        dialog.exec()
        self._filing_dialog = None
        dialog.deleteLater()

    def _filing_state_changed(self, busy: bool) -> None:
        self._filing_busy = busy
        self._set_busy(busy)

    def _apply_filing_result(self, result: FilingResult, mode: FilingMode) -> None:
        if mode == "move":
            moved = {entry.source: entry.target for entry in result.completed if entry.target}
            self.files = [moved.get(path, path) for path in self.files]
            # Rows can be shared by the batch; rewrite each object only once.
            all_rows = list(self.rows) + (self.batch.rows if self.batch else [])
            for row in {id(row): row for row in all_rows}.values():
                if row.path in moved:
                    row.path = moved[row.path]
                    row.source_fingerprint = fingerprint(row.path)
            if self.batch:
                for doc in self.batch.documents:
                    doc.path = moved.get(doc.path, doc.path)
            for i in range(self.table.rowCount()):
                item = self.table.item(i, 0)
                if item is None or not item.data(Qt.ItemDataRole.UserRole):
                    continue
                old = Path(item.data(Qt.ItemDataRole.UserRole))
                if old in moved:
                    target = moved[old]
                    item.setText(target.name)
                    item.setData(Qt.ItemDataRole.UserRole, str(target))
                    for col in range(self.table.columnCount()):
                        cell = self.table.item(i, col)
                        if cell:
                            cell.setToolTip(cell.toolTip().replace(str(old), str(target)))
            self.files_moved.emit(moved)
        verb = "Przeniesiono" if mode == "move" else "Skopiowano"
        self.status.setText(f"{verb}: {len(result.completed)} · Błędy: {len(result.errors)}")
        self._persist_collection()


    def _render_collection(self) -> None:
        self._restoring = True
        rows = list(self.rows)
        self.rows.clear()
        self.table.setRowCount(0)
        for row in rows:
            self._row_done(row)
        classified = {row.path for row in rows}
        for path in self.files:
            if path in classified:
                continue
            index = self.table.rowCount()
            self.table.insertRow(index)
            item = QTableWidgetItem(path.name)
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.table.setItem(index, 0, item)
            self.table.setItem(index, 6, QTableWidgetItem("Oczekuje"))
        self._restoring = False
        self.file_count.setText(f"{len(self.files)} PDF")
        self.result_stack.setCurrentIndex(1 if self.files else 0)
        self.export_button.setEnabled(self.batch is not None and not self.is_busy())
        self._update_filing_actions()
        self._refresh_summary()

    def _update_correction_action(self) -> None:
        item = self.table.item(self.table.currentRow(), 0)
        row = item.data(Qt.ItemDataRole.UserRole + 1) if item else None
        self.correct_button.setEnabled(
            not self.is_busy() and self.batch is not None and isinstance(row, ClassificationRow)
        )

    def _correct_category(self, index: int) -> None:
        if self.is_busy() or index < 0:
            return
        item = self.table.item(index, 0)
        row = item.data(Qt.ItemDataRole.UserRole + 1) if item else None
        if not isinstance(row, ClassificationRow) or not self.batch:
            return
        labels = [name for name, _ in self.batch.categories if name]
        dialog = LabelReviewDialog(row, labels, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        confirm_categories(row, dialog.selected_labels())
        self._render_collection()
        self._persist_collection()

    def _inclusion_changed(self, item: QTableWidgetItem) -> None:
        if self._restoring or self.is_busy() or item.column() != 0:
            return
        row = item.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(row, ClassificationRow):
            row.excluded = item.checkState() != Qt.CheckState.Checked
            self._update_filing_actions()
            self._checkpoint_timer.start(300)

    def _persist_collection(self) -> None:
        if self._restoring or self._checkpoint_disabled:
            return
        self._checkpoint_timer.stop()
        batch = self.batch or self._timing_batch or ClassificationBatch(
            categories=self.category_values(), instructions=self.prompt.toPlainText(),
        )
        snapshot = replace(batch, rows=list(self.rows), documents=[],
                           cancelled=batch.cancelled or (self.is_busy() and self.batch is None))
        try:
            save_collection(self.files, snapshot, self._session_path)
        except (OSError, ValueError) as exc:
            self.status.setText(f"Nie zapisano kolekcji: {exc}")

    def _restore_collection(self) -> None:
        try:
            saved = load_collection(self._session_path)
        except (OSError, ValueError) as exc:
            try:
                backup = self._session_path.with_suffix(f".unreadable-{time.time_ns()}.json")
                shutil.copy2(self._session_path, backup)
            except OSError:
                self._checkpoint_disabled = True
            self.status.setText(f"Nie odczytano kolekcji: {exc}")
            return
        if saved is None:
            return
        self.files, self.batch = saved
        refreshed = refresh_review_policy(self.batch, self.profiles)
        self.rows = list(self.batch.rows)
        self._run_labels = self.batch.model_labels
        self._run_category_colors = {name: i for i, (name, _) in enumerate(self.batch.categories)}
        if self.batch.categories:
            self.categories.setRowCount(len(self.batch.categories))
            for index, (name, detail) in enumerate(self.batch.categories):
                self.categories.setItem(index, 0, QTableWidgetItem(name))
                self.categories.setItem(index, 1, QTableWidgetItem(detail))
        if self.batch.instructions:
            self.prompt.setPlainText(
                DEFAULT_INSTRUCTIONS if self.batch.instructions in (
                    LEGACY_DEFAULT_INSTRUCTIONS, LEGACY_ENGLISH_INSTRUCTIONS
                ) else self.batch.instructions
            )
        self._render_collection()
        if self.files:
            self.status.setText("Przywrócono kolekcję" + (" · odświeżono oznaczenia HITL"
                                                       if refreshed else ""))
        if refreshed:
            self._persist_collection()
