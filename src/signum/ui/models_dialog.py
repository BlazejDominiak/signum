"""Model selection and connection settings for classification."""

from __future__ import annotations

import contextlib
import threading
import uuid
from dataclasses import replace

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from signum.ai.model_profiles import (
    API_FORMATS,
    ModelProfile,
    default_decision_values,
    load_profiles,
)
from signum.ai.text_classifiers import create_text_classifier, venice_key
from signum.config import AppConfig, get_api_key, set_api_key
from signum.i18n import tr
from signum.local_components import repair_instructions
from signum.network import normalize_ai_endpoint
from signum.ui.components_dialog import ComponentsDialog
from signum.ui.worker import ModelListWorker


class TextConnectionTestWorker(QThread):
    result = Signal(bool, str)

    def __init__(self, profile: ModelProfile, config: AppConfig, key: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.profile, self.config, self.key = profile, config, key

    def run(self) -> None:
        client = None
        try:
            client = create_text_classifier(
                self.profile,
                self.config,
                threading.Event(),
                api_key=self.key if self.key or self.profile.key_slot != "venice" else None,
            )
            client.check_connection()
            ok, message = True, tr("classification.connection_ok")
        except Exception as exc:
            ok, message = False, repair_instructions(str(exc), self.profile.provider)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception as exc:
                    ok, message = False, repair_instructions(str(exc), self.profile.provider)
        self.result.emit(ok, message)


class ModelsDialog(QDialog):
    def __init__(
        self,
        config: AppConfig,
        profiles: list[ModelProfile],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.profiles = [replace(p) for p in profiles]
        self.keys = {p.id: get_api_key(p.credential_slot) or "" for p in profiles}
        for p in profiles:
            if p.key_slot == "venice" and not self.keys[p.id]:
                with contextlib.suppress(ValueError, OSError):
                    self.keys[p.id] = venice_key(config)
        self.current = -1
        self._loading = False
        self.worker: QThread | None = None
        self.setWindowTitle(tr("classification.ai_settings"))
        self.resize(860, 660)
        outer = QVBoxLayout(self)
        self.components = QPushButton(tr("classification.components_repair"))
        self.components.clicked.connect(self._components)
        outer.addWidget(self.components)
        split = QSplitter()
        outer.addWidget(split, 1)
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(QLabel(tr("classification.models_heading")))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        sidebar_layout.addWidget(self.list)
        actions = QHBoxLayout()
        for title, callback in (
            (tr("classification.add"), self._add),
            (tr("classification.duplicate"), self._duplicate),
            (tr("classification.remove"), self._remove),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        sidebar_layout.addLayout(actions)
        split.addWidget(sidebar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.editor = QWidget()
        self.form = QFormLayout(self.editor)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name = QLineEdit()
        self.form.addRow(tr("classification.configuration_name"), self.name)
        self.provider = QComboBox()
        for label, value in (
            ("Ollama", "ollama"),
            (tr("classification.ai_provider"), "api"),
            (tr("classification.jevk5_provider"), "jevk5"),
        ):
            self.provider.addItem(label, value)
        self.provider.currentIndexChanged.connect(self._visibility)
        self.form.addRow(tr("classification.connection"), self.provider)
        self.protocol = QComboBox()
        for value, label in API_FORMATS.items():
            self.protocol.addItem(label, value)
        self.form.addRow(tr("classification.api_format"), self.protocol)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://api.example.com/v1")
        self.form.addRow(tr("classification.api_url"), self.url)
        self.model_row = QWidget()
        row = QHBoxLayout(self.model_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setMinimumWidth(170)
        self.refresh = QPushButton(tr("classification.refresh_list"))
        self.refresh.clicked.connect(self._refresh)
        row.addWidget(self.model, 1)
        row.addWidget(self.refresh)
        self.form.addRow(tr("classification.model"), self.model_row)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.form.addRow(tr("classification.api_key"), self.key)
        self.paths: dict[str, QLineEdit] = {}
        for key, title in (
            ("python", tr("classification.python_cuda")),
            ("model_dir", tr("classification.model_directory")),
            ("runtime", tr("classification.runtime_directory")),
            ("packages", tr("classification.libraries")),
        ):
            edit = QLineEdit()
            self.paths[key] = edit
            self.form.addRow(title, edit)
        self.custom_thresholds = QCheckBox(tr("classification.custom_thresholds"))
        self.form.addRow("", self.custom_thresholds)
        self.threshold = QDoubleSpinBox()
        self.hitl_margin = QDoubleSpinBox()
        for spin, label in (
            (self.threshold, tr("classification.decision_threshold")),
            (self.hitl_margin, tr("classification.hitl_margin")),
        ):
            spin.setRange(0, 1)
            spin.setDecimals(3)
            spin.setSingleStep(0.01)
            self.form.addRow(label, spin)
        self.reset_thresholds = QPushButton(tr("classification.default_thresholds"))
        self.reset_thresholds.clicked.connect(lambda: self.custom_thresholds.setChecked(False))
        self.form.addRow("", self.reset_thresholds)
        self.custom_thresholds.toggled.connect(self._threshold_defaults)
        self.provider.currentIndexChanged.connect(self._threshold_defaults)
        self.protocol.currentIndexChanged.connect(self._threshold_defaults)
        self.model.currentTextChanged.connect(self._threshold_defaults)
        self.test = QPushButton(tr("classification.test_connection"))
        self.test.clicked.connect(self._test)
        self.form.addRow("", self.test)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.form.addRow(self.message)
        scroll.setWidget(self.editor)
        split.addWidget(scroll)
        split.setSizes([260, 560])
        self.split = split
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("classification.save"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr("classification.cancel")
        )
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self._rebuild(0)

    def _components(self) -> None:
        self._store()
        self._remember_checks()
        ComponentsDialog(self.config, self).exec()
        for installed in load_profiles(self.config):
            matching = next((p for p in self.profiles if p.id == installed.id), None)
            if matching is None:
                self.profiles.append(installed)
            elif installed.provider == "jevk5":
                for field in ("python", "packages", "runtime", "model_dir"):
                    setattr(matching, field, getattr(installed, field))
        self._rebuild(max(0, self.current))

    def _store(self) -> None:
        if self.current < 0:
            return
        p = self.profiles[self.current]
        p.name = self.name.text().strip()
        p.provider = self.provider.currentData()
        p.url = self.url.text().strip()
        p.model = self.model.currentText().strip()
        p.api_format = self.protocol.currentData()
        p.threshold = self.threshold.value() if self.custom_thresholds.isChecked() else None
        p.hitl_margin = self.hitl_margin.value() if self.custom_thresholds.isChecked() else None
        self.keys[p.id] = self.key.text().strip()
        for key, edit in self.paths.items():
            setattr(p, key, edit.text().strip())
        self.list.item(self.current).setText(p.label)

    def _select(self, index: int) -> None:
        self._store()
        self.current = index
        self.editor.setEnabled(index >= 0)
        if index < 0:
            return
        p = self.profiles[index]
        self._loading = True
        self.name.setText(p.name)
        self.provider.setCurrentIndex(self.provider.findData(p.provider))
        self.url.setText(p.url)
        self.model.clear()
        self.model.setEditText(p.model)
        self.protocol.setCurrentIndex(self.protocol.findData(p.api_format))
        self.key.setText(self.keys.get(p.id, ""))
        for key, edit in self.paths.items():
            edit.setText(getattr(p, key))
        defaults = default_decision_values(p)
        self.custom_thresholds.setChecked(p.threshold is not None or p.hitl_margin is not None)
        self.threshold.setValue(p.threshold if p.threshold is not None else defaults[0])
        self.hitl_margin.setValue(p.hitl_margin if p.hitl_margin is not None else defaults[1])
        self._loading = False
        self._threshold_defaults()
        self.message.clear()
        self._visibility()

    def _threshold_defaults(self) -> None:
        if self._loading:
            return
        custom = self.custom_thresholds.isChecked()
        self.threshold.setEnabled(custom)
        self.hitl_margin.setEnabled(custom)
        if not custom:
            profile = ModelProfile(
                id="preview",
                provider=self.provider.currentData(),
                model=self.model.currentText(),
                api_format=self.protocol.currentData(),
            )
            threshold, margin = default_decision_values(profile)
            self.threshold.setValue(threshold)
            self.hitl_margin.setValue(margin)

    def _visibility(self) -> None:
        provider = self.provider.currentData()
        self.form.setRowVisible(self.protocol, provider == "api")
        for widget in (self.url, self.model_row, self.key):
            self.form.setRowVisible(widget, provider != "jevk5")
        self.refresh.setVisible(provider == "ollama")
        for edit in self.paths.values():
            self.form.setRowVisible(edit, provider == "jevk5")

    def _rebuild(self, selection: int) -> None:
        self.current = -1
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.profiles:
            item = QListWidgetItem(p.label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if p.enabled else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.list.setCurrentRow(min(selection, len(self.profiles) - 1))
        self.editor.setEnabled(bool(self.profiles))

    def _remember_checks(self) -> None:
        for i, p in enumerate(self.profiles):
            p.enabled = self.list.item(i).checkState() == Qt.CheckState.Checked

    def _add(self) -> None:
        self._store()
        self._remember_checks()
        p = ModelProfile(
            id=uuid.uuid4().hex,
            python=self.config.classification_jev_python,
            model_dir=self.config.classification_jev_model_dir,
            runtime=self.config.classification_jev_runtime,
            packages=self.config.classification_jev_packages,
        )
        self.profiles.append(p)
        self._rebuild(len(self.profiles) - 1)

    def _duplicate(self) -> None:
        if self.current < 0:
            return
        self._store()
        self._remember_checks()
        original = self.profiles[self.current]
        p = replace(
            original,
            id=uuid.uuid4().hex,
            name=original.label + tr("classification.copy_suffix"),
            key_slot="",
        )
        self.keys[p.id] = self.keys.get(original.id, "")
        self.profiles.append(p)
        self._rebuild(len(self.profiles) - 1)

    def _remove(self) -> None:
        if self.current < 0:
            return
        self._remember_checks()
        index = self.current
        self.profiles.pop(index)
        self._rebuild(index)

    def _busy(self, busy: bool) -> None:
        self.components.setEnabled(not busy)
        self.split.setEnabled(not busy)
        self.buttons.setEnabled(not busy)

    def _refresh(self) -> None:
        try:
            url = normalize_ai_endpoint(
                self.url.text(), "http://localhost:11434", tr("classification.ollama_endpoint")
            )
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        worker = ModelListWorker(url, self, self.key.text().strip())
        worker.finished_with_result.connect(self._models_loaded)
        self._start_worker(worker)

    def _models_loaded(self, ok: bool, payload: object) -> None:
        if not ok:
            self.message.setText(repair_instructions(str(payload), "ollama"))
            return
        current = self.model.currentText()
        self.model.clear()
        self.model.addItems(list(payload))  # type: ignore[call-overload]
        self.model.setEditText(current)
        self.message.setText(tr("classification.available_models", count=self.model.count()))

    def _test(self) -> None:
        self._store()
        try:
            profile = replace(self.profiles[self.current])
            profile.validate()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        worker = TextConnectionTestWorker(profile, self.config, self.key.text().strip(), self)
        worker.result.connect(lambda ok, text: self.message.setText(("✔ " if ok else "✘ ") + text))
        self.message.setText(tr("classification.testing"))
        self._start_worker(worker)

    def _start_worker(self, worker: QThread) -> None:
        if self.worker is not None:
            return
        self.worker = worker
        worker.finished.connect(self._finished)
        self._busy(True)
        worker.start()

    def _finished(self) -> None:
        worker = self.worker
        self.worker = None
        self._busy(False)
        if worker is not None:
            worker.deleteLater()

    def _save(self) -> None:
        if self.worker is not None:
            return
        self._store()
        self._remember_checks()
        try:
            for p in self.profiles:
                p.validate()
            for p in self.profiles:
                # Give each editable profile its own credential entry.
                key = self.keys.get(p.id, "")
                p.key_slot = ""
                set_api_key(p.credential_slot, key)
        except Exception as exc:
            QMessageBox.warning(self, tr("classification.ai_settings"), str(exc))
            return
        self.accept()

    def reject(self) -> None:
        if self.worker is None:
            super().reject()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def] # noqa: N802
        if self.worker is not None:
            event.ignore()
        else:
            super().closeEvent(event)
