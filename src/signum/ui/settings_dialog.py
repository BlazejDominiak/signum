"""Dialog ustawień AI i przetwarzania.

Klucze API są zapisywane w systemowym magazynie poświadczeń (keyring),
nigdy w pliku konfiguracyjnym.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from signum.ai import create_vision_model
from signum.ai.jev_prompts import JEV_PROMPT_INSTRUCTIONS
from signum.ai.prompts import PROMPT_INSTRUCTIONS, default_instructions
from signum.config import (
    MAX_CUSTOM_PROMPT_LENGTH,
    PROVIDERS,
    AppConfig,
    get_api_key,
    set_api_key,
)
from signum.i18n import tr
from signum.local_components import repair_instructions
from signum.network import normalize_ai_endpoint, processing_is_local
from signum.ui.components_dialog import ComponentsDialog
from signum.ui.worker import ConnectionTestWorker, ModelListWorker

_PROVIDER_ORDER = ("ollama", "api", "vjev")
_PROVIDER_LABELS = {
    "ollama": "settings.provider_ollama",
    "api": "settings.provider_api",
    "openai": "settings.provider_api",
    "anthropic": "settings.provider_api",
    "vjev": "settings.provider_jev",
}
_OLLAMA_INSTALL_HELP = "settings.ollama_install_help"


class _ProviderStack(QStackedWidget):
    """Ukryty formularz dostawcy nie zostawia pustego miejsca pod bieżącym."""

    def sizeHint(self) -> QSize:  # noqa: N802
        widget = self.currentWidget()
        return widget.sizeHint() if widget else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget else super().minimumSizeHint()


class SettingsDialog(QDialog):
    """Konfiguracja dostawcy AI, modelu i parametrów przetwarzania."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._initial_local = processing_is_local(config.provider, config.api_base_url)
        self._key_edits: dict[str, QLineEdit] = {}
        self._url_edits: dict[str, QLineEdit] = {}
        self._model_edits: dict[str, QLineEdit] = {}
        self._decision_edits: dict[str, QDoubleSpinBox] = {}
        self._prompt_family: str | None = None
        self._prompt_drafts = {
            "llm": config.custom_prompt or default_instructions(),
            "jev": config.jev_custom_prompt or JEV_PROMPT_INSTRUCTIONS,
        }
        self._test_worker: ConnectionTestWorker | None = None
        self._models_worker: ModelListWorker | None = None
        self._auto_refresh_started = False
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(520)
        self._build_ui()
        self._load_config()
        self.ollama_additional_analysis.toggled.connect(
            lambda: self._on_provider_changed(self.provider_combo.currentIndex())
        )

    # -- budowa UI ---------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        language_form = QFormLayout()
        self.language_combo = QComboBox()
        self.language_combo.addItem(tr("settings.language_polish"), "pl")
        self.language_combo.addItem(tr("settings.language_english"), "en")
        language_form.addRow(tr("settings.language"), self.language_combo)
        outer.addLayout(language_form)
        self.components_button = QPushButton(tr("settings.components_button"))
        self.components_button.clicked.connect(self._components)
        outer.addWidget(self.components_button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        provider_form = QFormLayout()
        self.provider_combo = QComboBox()
        for key in _PROVIDER_ORDER:
            self.provider_combo.addItem(tr(_PROVIDER_LABELS[key]), userData=key)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_form.addRow(tr("settings.connection"), self.provider_combo)
        self.api_format = QComboBox()
        self.api_format.addItem(tr("settings.chat_api"), "openai")
        self.api_format.addItem(tr("settings.messages_api"), "anthropic")
        self.api_format.currentIndexChanged.connect(
            lambda: self._on_provider_changed(self.provider_combo.currentIndex())
        )
        provider_form.addRow(tr("settings.api_format"), self.api_format)
        self.provider_form = provider_form
        layout.addLayout(provider_form)

        self.stack = _ProviderStack()
        self.stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.stack.addWidget(self._build_ollama_page())
        self.stack.addWidget(self._build_openai_page())
        self.stack.addWidget(self._build_anthropic_page())
        self.stack.addWidget(self._build_jev_page("vjev"))
        layout.addWidget(self.stack)

        test_row = QHBoxLayout()
        self.test_button = QPushButton(tr("settings.test_connection"))
        self.test_button.clicked.connect(self._on_test_clicked)
        self.test_result = QLabel("")
        self.test_result.setTextFormat(Qt.TextFormat.PlainText)
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_button)
        test_row.addWidget(self.test_result, stretch=1)
        layout.addLayout(test_row)

        layout.addWidget(self._build_processing_group())
        layout.addWidget(self._build_prompt_group())

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("settings.save"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("settings.cancel"))
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.resize(620, max(480, min(840, self.screen().availableGeometry().height() - 80)))

    def _build_ollama_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.ollama_url = QLineEdit()
        self.ollama_url.setPlaceholderText("http://localhost:11434")
        form.addRow(tr("settings.api_address"), self.ollama_url)

        model_row = QHBoxLayout()
        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)
        self.refresh_models = QPushButton(tr("settings.refresh_models"))
        self.refresh_models.clicked.connect(self._on_refresh_models)
        model_row.addWidget(self.ollama_model, stretch=1)
        model_row.addWidget(self.refresh_models)
        form.addRow(tr("settings.model"), model_row)
        self.ollama_additional_analysis = QCheckBox(tr("settings.additional_analysis"))
        self.ollama_additional_analysis.setToolTip(
            tr("settings.additional_analysis_hint")
        )
        form.addRow("", self.ollama_additional_analysis)
        basic = self._decision_group(tr("settings.basic_thresholds"), (
            ("ollama_threshold", tr("settings.signature_threshold")),
            ("ollama_stamp_threshold", tr("settings.stamp_threshold")),
        ))
        full = self._decision_group(tr("settings.extra_thresholds"), (
            ("ollama_full_threshold", tr("settings.finding_threshold")),
        ))
        form.addRow(basic)
        form.addRow(full)
        self.ollama_additional_analysis.toggled.connect(basic.setHidden)
        self.ollama_additional_analysis.toggled.connect(full.setVisible)
        basic.setVisible(not self._config.ollama_additional_analysis)
        full.setVisible(self._config.ollama_additional_analysis)
        form.addRow(self._decision_group(tr("settings.hitl"), (
            ("ollama_hitl_margin", tr("settings.hitl_margin")),
        )))
        self.ollama_key = self._password_edit()
        self._key_edits["ollama"] = self.ollama_key
        form.addRow(tr("settings.optional_key"), self._with_reveal(self.ollama_key))
        form.addRow(
            "", _hint_label(tr("settings.vision_required"))
        )
        self.ollama_status = QLabel("")
        self.ollama_status.setTextFormat(Qt.TextFormat.PlainText)
        self.ollama_status.setWordWrap(True)
        form.addRow(tr("settings.service_status"), self.ollama_status)
        self.ollama_install_help = QLabel(tr(_OLLAMA_INSTALL_HELP))
        self.ollama_install_help.setWordWrap(True)
        self.ollama_install_help.setOpenExternalLinks(True)
        self.ollama_install_help.setVisible(False)
        form.addRow("", self.ollama_install_help)

        self.ollama_num_ctx = QSpinBox()
        self.ollama_num_ctx.setRange(2048, 262144)
        self.ollama_num_ctx.setSingleStep(2048)
        self.ollama_num_ctx.setSuffix(tr("settings.tokens"))
        form.addRow(tr("settings.context_window"), self.ollama_num_ctx)
        return page

    def _build_openai_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.openai_base_url = QLineEdit()
        self.openai_base_url.setPlaceholderText("https://api.openai.com/v1")
        form.addRow(tr("settings.api_address"), self.openai_base_url)
        self.openai_model = QLineEdit()
        self.openai_model.setPlaceholderText("gpt-4o")
        form.addRow(tr("settings.model"), self.openai_model)
        self.openai_key = self._password_edit()
        self._key_edits["openai"] = self.openai_key
        self._url_edits["openai"] = self.openai_base_url
        self._model_edits["openai"] = self.openai_model
        form.addRow(tr("settings.api_key"), self._with_reveal(self.openai_key))
        form.addRow(self._decision_group(tr("settings.thresholds"), (
            ("openai_threshold", tr("settings.finding_threshold")),
            ("openai_hitl_margin", tr("settings.hitl_margin")),
        )))
        return page

    def _build_anthropic_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.anthropic_base_url = QLineEdit()
        self.anthropic_base_url.setPlaceholderText(AppConfig().anthropic_base_url)
        form.addRow(tr("settings.api_address"), self.anthropic_base_url)
        self.anthropic_model = QLineEdit()
        self.anthropic_model.setPlaceholderText("claude-sonnet-5")
        form.addRow(tr("settings.model"), self.anthropic_model)
        self.anthropic_key = self._password_edit()
        self._key_edits["anthropic"] = self.anthropic_key
        self._url_edits["anthropic"] = self.anthropic_base_url
        self._model_edits["anthropic"] = self.anthropic_model
        form.addRow(tr("settings.api_key"), self._with_reveal(self.anthropic_key))
        form.addRow(self._decision_group(tr("settings.thresholds"), (
            ("anthropic_threshold", tr("settings.finding_threshold")),
            ("anthropic_hitl_margin", tr("settings.hitl_margin")),
        )))
        return page

    def _build_jev_page(self, provider: str) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        defaults = AppConfig()
        url = QLineEdit()
        url.setPlaceholderText(getattr(defaults, f"{provider}_base_url"))
        model = QLineEdit()
        model.setPlaceholderText(getattr(defaults, f"{provider}_model"))
        key = self._password_edit()
        self._url_edits[provider] = url
        self._model_edits[provider] = model
        self._key_edits[provider] = key
        form.addRow(tr("settings.api_address"), url)
        form.addRow(tr("settings.model"), model)
        form.addRow(tr("settings.optional_key"), self._with_reveal(key))
        self.vjev_runtime_dir = QLineEdit()
        form.addRow(tr("settings.jev_directory"), self.vjev_runtime_dir)
        self.vjev_additional_analysis = QCheckBox(tr("settings.additional_analysis"))
        self.vjev_additional_analysis.setToolTip(
            tr("settings.jev_extra_hint")
        )
        form.addRow("", self.vjev_additional_analysis)
        form.addRow(self._decision_group(tr("settings.thresholds"), (
            ("vjev_threshold", tr("settings.signature_threshold")),
            ("vjev_hitl_margin", tr("settings.hitl_margin")),
            ("vjev_stamp_threshold", tr("settings.stamp_threshold")),
        )))
        self.vjev_hitl_margin = self._decision_edits["vjev_hitl_margin"]
        extra = self._decision_group(tr("settings.extra_thresholds"), (
            ("vjev_category_threshold", tr("settings.category_threshold")),
            ("vjev_candidate_threshold", tr("settings.region_threshold")),
            ("vjev_verify_threshold", tr("settings.verification_threshold")),
            ("vjev_single_threshold", tr("settings.single_threshold")),
        ))
        form.addRow(extra)
        self.vjev_additional_analysis.toggled.connect(extra.setVisible)
        extra.setVisible(self._config.vjev_additional_analysis)
        self.stop_jev_button = QPushButton(tr("settings.stop_jev"))
        self.stop_jev_button.clicked.connect(lambda: self._on_test_clicked(stop_local=True))
        form.addRow("", self.stop_jev_button)
        return page

    def _decision_group(self, title: str, fields: tuple[tuple[str, str], ...]) -> QGroupBox:
        group = QGroupBox(title)
        form = QFormLayout(group)
        for name, label in fields:
            edit = QDoubleSpinBox()
            edit.setRange(0, 1)
            edit.setDecimals(3)
            edit.setSingleStep(0.01)
            self._decision_edits[name] = edit
            form.addRow(label, edit)
        reset = QPushButton(tr("settings.default_thresholds"))
        reset.clicked.connect(lambda: self._reset_decisions(fields))
        form.addRow("", reset)
        return group

    def _reset_decisions(self, fields: tuple[tuple[str, str], ...]) -> None:
        defaults = AppConfig()
        for name, _ in fields:
            self._decision_edits[name].setValue(getattr(defaults, name))

    def _build_processing_group(self) -> QGroupBox:
        group = QGroupBox(tr("settings.processing"))
        form = QFormLayout(group)
        self.max_pages = QSpinBox()
        self.max_pages.setRange(1, 500)
        self.max_pages.setSuffix(tr("settings.pages"))
        form.addRow(tr("settings.page_limit"), self.max_pages)

        self.image_side = QComboBox()
        for value in (768, 1024, 1120, 1400, 1600, 2048):
            self.image_side.addItem(f"{value} px", userData=value)
        form.addRow(tr("settings.image_size"), self.image_side)
        self.timeout = QSpinBox()
        self.timeout.setRange(30, 3600)
        self.timeout.setSuffix(" s")
        form.addRow(tr("settings.response_timeout"), self.timeout)

        self.recursive = QCheckBox(tr("settings.recursive"))
        form.addRow("", self.recursive)
        return group

    def _build_prompt_group(self) -> QGroupBox:
        group = QGroupBox(tr("settings.advanced_prompt"))
        group.setCheckable(True)
        group.setChecked(False)
        outer = QVBoxLayout(group)
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(content)
        content.setVisible(False)
        group.toggled.connect(content.setVisible)
        self.prompt_hint = _hint_label("")
        box.addWidget(self.prompt_hint)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setFixedHeight(150)
        box.addWidget(self.prompt_edit)
        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        reset = QPushButton(tr("settings.restore_default"))
        reset.clicked.connect(lambda: self.prompt_edit.setPlainText(self._default_prompt()))
        reset_row.addWidget(reset)
        box.addLayout(reset_row)
        return group

    @staticmethod
    def _password_edit() -> QLineEdit:
        edit = QLineEdit()
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        return edit

    @staticmethod
    def _with_reveal(edit: QLineEdit) -> QWidget:
        """Pole hasła z przyciskiem pokaż/ukryj."""
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        toggle = QPushButton(tr("settings.show"))
        toggle.setCheckable(True)
        toggle.setFixedWidth(60)

        def on_toggle(checked: bool) -> None:
            edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
            toggle.setText(tr("settings.hide") if checked else tr("settings.show"))

        toggle.toggled.connect(on_toggle)
        row.addWidget(edit, stretch=1)
        row.addWidget(toggle)
        clear = QPushButton(tr("settings.clear"))
        clear.clicked.connect(edit.clear)
        row.addWidget(clear)
        return wrapper

    # -- konfiguracja ------------------------------------------------------

    def _load_config(self) -> None:
        cfg = self._config
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(cfg.language)))
        self.api_format.setCurrentIndex(max(0, self.api_format.findData(cfg.provider)))
        self.provider_combo.setCurrentIndex(
            _PROVIDER_ORDER.index(
                "api" if cfg.provider in {"openai", "anthropic"} else cfg.provider
            )
        )
        self.ollama_url.setText(cfg.ollama_url)
        self.ollama_model.setEditText(cfg.ollama_model)
        for provider, edit in self._url_edits.items():
            edit.setText(getattr(cfg, f"{provider}_base_url"))
        for provider, edit in self._model_edits.items():
            edit.setText(getattr(cfg, f"{provider}_model"))
        for provider, edit in self._key_edits.items():
            edit.setText(get_api_key(provider) or "")
        self.max_pages.setValue(cfg.max_pages_per_doc)
        index = self.image_side.findData(cfg.model_image_max_side)
        self.image_side.setCurrentIndex(index if index >= 0 else 2)
        self.timeout.setValue(cfg.timeout_s)
        self.recursive.setChecked(cfg.recursive_folders)
        self.ollama_num_ctx.setValue(cfg.ollama_num_ctx)
        self.ollama_additional_analysis.setChecked(cfg.ollama_additional_analysis)
        self.vjev_additional_analysis.setChecked(cfg.vjev_additional_analysis)
        for name, spin in self._decision_edits.items():
            spin.setValue(getattr(cfg, name))
        self.vjev_runtime_dir.setText(cfg.vjev_runtime_dir)
        self._on_provider_changed(self.provider_combo.currentIndex())

    def _collect_config(self) -> AppConfig:
        """Zbiera ustawienia z formularza (bez zapisywania)."""
        cfg = replace(self._config)
        cfg.language = self.language_combo.currentData()
        cfg.provider = self._provider()
        cfg.ollama_url = normalize_ai_endpoint(
            self.ollama_url.text(), "http://localhost:11434", tr("settings.ollama_name")
        )
        cfg.ollama_model = self.ollama_model.currentText().strip() or "gemma4:12b"
        defaults = AppConfig()
        for provider, edit in self._url_edits.items():
            name = f"{provider}_base_url"
            setattr(
                cfg,
                name,
                normalize_ai_endpoint(
                    edit.text(), getattr(defaults, name), tr(_PROVIDER_LABELS[provider])
                ),
            )
        for provider, edit in self._model_edits.items():
            name = f"{provider}_model"
            setattr(cfg, name, edit.text().strip() or getattr(defaults, name))
        cfg.max_pages_per_doc = self.max_pages.value()
        cfg.model_image_max_side = self.image_side.currentData()
        cfg.timeout_s = self.timeout.value()
        cfg.recursive_folders = self.recursive.isChecked()
        cfg.ollama_num_ctx = self.ollama_num_ctx.value()
        cfg.ollama_additional_analysis = self.ollama_additional_analysis.isChecked()
        cfg.vjev_additional_analysis = self.vjev_additional_analysis.isChecked()
        for name, spin in self._decision_edits.items():
            setattr(cfg, name, spin.value())
        cfg.vjev_runtime_dir = self.vjev_runtime_dir.text().strip() or defaults.vjev_runtime_dir
        if self._prompt_family is not None:
            self._prompt_drafts[self._prompt_family] = self.prompt_edit.toPlainText().strip()
        if any(len(text) > MAX_CUSTOM_PROMPT_LENGTH for text in self._prompt_drafts.values()):
            raise ValueError(
                tr("settings.prompt_limit", limit=MAX_CUSTOM_PROMPT_LENGTH)
            )
        # Domyślną treść zapisujemy jako pustą — aktualizacja programu może
        # wtedy poprawić prompt bez ręcznej interwencji użytkownika.
        llm_text = self._prompt_drafts["llm"].strip()
        jev_text = self._prompt_drafts["jev"].strip()
        cfg.custom_prompt = (
            "" if llm_text in ("", PROMPT_INSTRUCTIONS.strip(), default_instructions().strip())
            else llm_text
        )
        cfg.jev_custom_prompt = (
            "" if jev_text in ("", JEV_PROMPT_INSTRUCTIONS.strip()) else jev_text
        )
        return cfg

    def _current_api_key(self) -> str:
        provider = self._provider()
        return self._key_edits[provider].text().strip()

    # -- akcje -------------------------------------------------------------

    def _provider(self) -> str:
        selected = self.provider_combo.currentData()
        return str(self.api_format.currentData() if selected == "api" else selected)

    def _on_provider_changed(self, index: int) -> None:
        self.provider_form.setRowVisible(
            self.api_format, self.provider_combo.currentData() == "api"
        )
        self.stack.setCurrentIndex(PROVIDERS.index(self._provider()))
        self.stack.updateGeometry()
        self.test_result.setText("")
        if self._prompt_family is not None:
            self._prompt_drafts[self._prompt_family] = self.prompt_edit.toPlainText()
        self._prompt_family = "jev" if self.provider_combo.currentData() == "vjev" else "llm"
        self.prompt_edit.setPlainText(self._prompt_drafts[self._prompt_family])
        self.image_side.setEnabled(self._prompt_family != "jev")
        self.image_side.setToolTip(
            tr("settings.jev_fixed_size")
            if self._prompt_family == "jev"
            else ""
        )
        self.prompt_hint.setText(tr("settings.page_instructions"))
        basic_ollama = (
            self.provider_combo.currentData() == "ollama"
            and not self.ollama_additional_analysis.isChecked()
        )
        self.prompt_edit.setEnabled(not basic_ollama)
        if basic_ollama:
            self.prompt_hint.setText(
                tr("settings.basic_prompt_hint")
            )

    def _default_prompt(self) -> str:
        return JEV_PROMPT_INSTRUCTIONS if self._prompt_family == "jev" else default_instructions()

    def _on_refresh_models(self) -> None:
        if self._models_worker is not None:
            return
        try:
            url = normalize_ai_endpoint(
                self.ollama_url.text(), "http://localhost:11434", tr("settings.ollama_name")
            )
        except ValueError as exc:
            self.ollama_status.setText(str(exc))
            self.ollama_install_help.setVisible(False)
            return
        self.refresh_models.setEnabled(False)
        self.ollama_status.setText(tr("settings.checking_ollama"))
        self.ollama_install_help.setText(tr(_OLLAMA_INSTALL_HELP))
        self.ollama_install_help.setVisible(False)
        self._models_worker = ModelListWorker(url, self, api_key=self.ollama_key.text().strip())
        self._models_worker.finished_with_result.connect(self._on_models_loaded)
        self._models_worker.finished.connect(self._on_models_worker_finished)
        self._update_busy_state()
        self._models_worker.start()

    def _on_models_loaded(self, ok: bool, payload: object) -> None:
        if not ok:
            self.ollama_status.setText(str(payload))
            self.ollama_install_help.setVisible(True)
            return
        models = list(payload)  # type: ignore[call-overload]
        current = self.ollama_model.currentText()
        self.ollama_model.clear()
        self.ollama_model.addItems(models)
        if current:
            self.ollama_model.setEditText(current)
        if models:
            self.ollama_status.setText(tr("settings.models_found", count=len(models)))
            self.ollama_install_help.setVisible(False)
        else:
            self.ollama_status.setText(tr("settings.ollama_empty"))
            self.ollama_install_help.setText(
                tr("settings.download_model_hint")
            )
            self.ollama_install_help.setVisible(True)

    def _on_models_worker_finished(self) -> None:
        worker = self._models_worker
        self._models_worker = None
        self._update_busy_state()
        if worker is not None:
            worker.deleteLater()

    def _on_test_clicked(self, *, stop_local: bool = False) -> None:
        if self._test_worker is not None:
            return
        self.test_button.setEnabled(False)
        self.test_result.setText(
            tr("settings.stopping_jev")
            if stop_local
            else tr("settings.loading_local")
            if self.provider_combo.currentData() == "vjev"
            else tr("settings.connecting")
        )
        try:
            config = self._collect_config()
            model = create_vision_model(config, api_key=self._current_api_key())
        except ValueError as exc:
            self.test_button.setEnabled(True)
            self.test_result.setText(str(exc))
            return
        self._test_worker = ConnectionTestWorker(model, self, stop_local=stop_local)
        self._test_worker.finished_with_result.connect(self._on_test_finished)
        self._test_worker.finished.connect(self._on_test_worker_finished)
        self._update_busy_state()
        self._test_worker.start()

    def _components(self) -> None:
        ComponentsDialog(self._config, self).exec()
        self._load_config()

    def _on_test_finished(self, ok: bool, message: str) -> None:
        prefix = "✔ " if ok else "✘ "
        self.test_result.setText(
            prefix
            + (message if ok else repair_instructions(message, self.provider_combo.currentData()))
        )
        color = "#2e7d32" if ok else "#c62828"
        self.test_result.setStyleSheet(f"color: {color};")

    def _on_test_worker_finished(self) -> None:
        worker = self._test_worker
        self._test_worker = None
        self._update_busy_state()
        if worker is not None:
            worker.deleteLater()

    def _on_save(self) -> None:
        if self._test_worker is not None or self._models_worker is not None:
            return
        try:
            config = self._collect_config()
        except ValueError as exc:
            QMessageBox.critical(self, tr("settings.invalid_settings"), str(exc))
            return
        if self._initial_local and not processing_is_local(config.provider, config.api_base_url):
            warning = OnlineWarningDialog(self)
            if warning.exec() != QDialog.DialogCode.Accepted:
                return  # użytkownik nie potwierdził — dialog ustawień zostaje otwarty
        try:
            for provider, edit in self._key_edits.items():
                set_api_key(provider, edit.text().strip())
        except Exception:
            QMessageBox.warning(
                self,
                tr("settings.credential_store"),
                tr("settings.credential_error"),
            )
            return
        config.save()
        self.accept()

    # -- sprzątanie --------------------------------------------------------

    def _update_busy_state(self) -> None:
        busy = self._test_worker is not None or self._models_worker is not None
        self.buttons.setEnabled(not busy)
        self.provider_combo.setEnabled(not busy)
        self.api_format.setEnabled(not busy)
        self.stack.setEnabled(not busy)
        self.test_button.setEnabled(self._test_worker is None)
        self.components_button.setEnabled(not busy)
        self.refresh_models.setEnabled(self._models_worker is None)

    def reject(self) -> None:
        # Escape/Anuluj nie może zniszczyć rodzica aktywnego QThread.
        if self._test_worker is None and self._models_worker is None:
            super().reject()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def] # noqa: N802 — API Qt
        super().showEvent(event)
        if not self._auto_refresh_started and self.provider_combo.currentData() == "ollama":
            self._auto_refresh_started = True
            QTimer.singleShot(0, self._on_refresh_models)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def] # noqa: N802 — API Qt
        if self._test_worker is not None or self._models_worker is not None:
            QMessageBox.information(
                self,
                tr("settings.connection_in_progress"),
                tr("settings.wait_connection"),
            )
            event.ignore()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def] # noqa: N802 — API Qt
        # Enter w polu tekstowym nie powinien zapisywać dialogu.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)


class OnlineWarningDialog(QDialog):
    """Ostrzeżenie przed przełączeniem na dostawcę AI działającego w chmurze.

    Przycisk potwierdzenia odblokowuje się dopiero po 3 sekundach —
    użytkownik ma faktycznie przeczytać ostrzeżenie, nie odklikać je.
    """

    COUNTDOWN_S = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("settings.online_title"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        message = QLabel(
            tr("settings.online_warning")
        )
        message.setWordWrap(True)
        message.setStyleSheet("color: #c62828;")
        layout.addWidget(message)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(tr("settings.cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.accept_button = QPushButton()
        self.accept_button.clicked.connect(self.accept)
        buttons.addWidget(self.accept_button)
        layout.addLayout(buttons)

        self._remaining = self.COUNTDOWN_S
        self._refresh_accept_button()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
        self._refresh_accept_button()

    def _refresh_accept_button(self) -> None:
        if self._remaining > 0:
            self.accept_button.setText(
                tr("settings.accept_risk_countdown", seconds=self._remaining)
            )
            self.accept_button.setEnabled(False)
        else:
            self.accept_button.setText(tr("settings.accept_risk"))
            self.accept_button.setEnabled(True)


def _hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #666; font-size: 11px;")
    return label


def _online_warning_label() -> QLabel:
    label = QLabel(
        tr("settings.online_notice")
    )
    label.setWordWrap(True)
    label.setStyleSheet("color: #c62828; font-weight: 600;")
    return label
