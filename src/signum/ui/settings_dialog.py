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
from signum.ai.prompts import PROMPT_INSTRUCTIONS
from signum.config import (
    MAX_CUSTOM_PROMPT_LENGTH,
    PROVIDERS,
    AppConfig,
    get_api_key,
    set_api_key,
)
from signum.network import normalize_ai_endpoint, processing_is_local
from signum.ui.worker import ConnectionTestWorker, ModelListWorker

_PROVIDER_ORDER = PROVIDERS
_PROVIDER_LABELS = {
    "ollama": "Ollama (lokalna lub zdalna)",
    "openai": "OpenAI / API zgodne z OpenAI",
    "anthropic": "Claude (Anthropic)",
    "vjev": "vjev-vision (on-prem / API)",
}
_OLLAMA_INSTALL_HELP = (
    "Nie wykryto działającej Ollamy. Zainstaluj ją z "
    '<a href="https://docs.ollama.com/windows">oficjalnej instrukcji dla Windows</a>, '
    "uruchom usługę, wykonaj <code>ollama pull gemma4:12b</code> i odśwież listę."
)


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
        self._prompt_family: str | None = None
        self._prompt_drafts = {
            "llm": config.custom_prompt or PROMPT_INSTRUCTIONS,
            "jev": config.jev_custom_prompt or JEV_PROMPT_INSTRUCTIONS,
        }
        self._test_worker: ConnectionTestWorker | None = None
        self._models_worker: ModelListWorker | None = None
        self._auto_refresh_started = False
        self.setWindowTitle("Ustawienia AI")
        self.setMinimumWidth(520)
        self._build_ui()
        self._load_config()

    # -- budowa UI ---------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
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
            self.provider_combo.addItem(_PROVIDER_LABELS[key], userData=key)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_form.addRow("Dostawca AI:", self.provider_combo)
        layout.addLayout(provider_form)

        self.stack = _ProviderStack()
        self.stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.stack.addWidget(self._build_ollama_page())
        self.stack.addWidget(self._build_openai_page())
        self.stack.addWidget(self._build_anthropic_page())
        self.stack.addWidget(self._build_jev_page("vjev"))
        layout.addWidget(self.stack)

        test_row = QHBoxLayout()
        self.test_button = QPushButton("Testuj połączenie")
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
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Zapisz")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Anuluj")
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.resize(620, max(480, min(840, self.screen().availableGeometry().height() - 80)))

    def _build_ollama_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.ollama_url = QLineEdit()
        self.ollama_url.setPlaceholderText("http://localhost:11434")
        form.addRow("Adres API:", self.ollama_url)

        model_row = QHBoxLayout()
        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)
        self.refresh_models = QPushButton("Odśwież listę")
        self.refresh_models.clicked.connect(self._on_refresh_models)
        model_row.addWidget(self.ollama_model, stretch=1)
        model_row.addWidget(self.refresh_models)
        form.addRow("Model:", model_row)
        self.ollama_key = self._password_edit()
        self._key_edits["ollama"] = self.ollama_key
        form.addRow("Klucz API (opcjonalny):", self._with_reveal(self.ollama_key))
        form.addRow(
            "", _hint_label("Model musi obsługiwać obrazy (np. gemma4:12b, llava, qwen-vl).")
        )
        self.ollama_status = QLabel("")
        self.ollama_status.setTextFormat(Qt.TextFormat.PlainText)
        self.ollama_status.setWordWrap(True)
        form.addRow("Stan usługi:", self.ollama_status)
        self.ollama_install_help = QLabel(_OLLAMA_INSTALL_HELP)
        self.ollama_install_help.setWordWrap(True)
        self.ollama_install_help.setOpenExternalLinks(True)
        self.ollama_install_help.setVisible(False)
        form.addRow("", self.ollama_install_help)

        self.ollama_num_ctx = QSpinBox()
        self.ollama_num_ctx.setRange(2048, 262144)
        self.ollama_num_ctx.setSingleStep(2048)
        self.ollama_num_ctx.setSuffix(" tokenów")
        form.addRow("Okno kontekstu (num_ctx):", self.ollama_num_ctx)
        form.addRow(
            "",
            _hint_label(
                "Ollama domyślnie używa zaledwie 4096 tokenów; gemma4:12b obsługuje "
                "do 256 tys. Większe okno zwiększa zużycie pamięci (RAM/VRAM)."
            ),
        )
        return page

    def _build_openai_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.openai_base_url = QLineEdit()
        self.openai_base_url.setPlaceholderText("https://api.openai.com/v1")
        form.addRow("Adres API:", self.openai_base_url)
        self.openai_model = QLineEdit()
        self.openai_model.setPlaceholderText("gpt-4o")
        form.addRow("Model:", self.openai_model)
        self.openai_key = self._password_edit()
        self._key_edits["openai"] = self.openai_key
        self._url_edits["openai"] = self.openai_base_url
        self._model_edits["openai"] = self.openai_model
        form.addRow("Klucz API:", self._with_reveal(self.openai_key))
        form.addRow("", _online_warning_label())
        return page

    def _build_anthropic_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.anthropic_base_url = QLineEdit()
        self.anthropic_base_url.setPlaceholderText(AppConfig().anthropic_base_url)
        form.addRow("Adres API:", self.anthropic_base_url)
        self.anthropic_model = QLineEdit()
        self.anthropic_model.setPlaceholderText("claude-sonnet-5")
        form.addRow("Model:", self.anthropic_model)
        self.anthropic_key = self._password_edit()
        self._key_edits["anthropic"] = self.anthropic_key
        self._url_edits["anthropic"] = self.anthropic_base_url
        self._model_edits["anthropic"] = self.anthropic_model
        form.addRow("Klucz API:", self._with_reveal(self.anthropic_key))
        form.addRow("", _online_warning_label())
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
        form.addRow("Adres API:", url)
        form.addRow("Model:", model)
        form.addRow("Klucz API (opcjonalny):", self._with_reveal(key))
        self.vjev_runtime_dir = QLineEdit()
        form.addRow("Katalog lokalnego Jev:", self.vjev_runtime_dir)
        self.stop_jev_button = QPushButton("Zatrzymaj lokalny Jev / zwolnij GPU")
        self.stop_jev_button.clicked.connect(lambda: self._on_test_clicked(stop_local=True))
        form.addRow("", self.stop_jev_button)
        form.addRow(
            "",
            _hint_label(
                "Na localhost aplikacja uruchamia przygotowany model automatycznie przy "
                "testowaniu połączenia lub rozpoczęciu analizy. Pierwsze załadowanie "
                "wag może potrwać kilkadziesiąt sekund. Klucz nie jest wymagany. "
                "Po zakończeniu lub anulowaniu partii Jev zwalnia pamięć GPU."
            ),
        )
        form.addRow(
            "",
            _hint_label(
                "Podpisy i parafki: pięć widoków strony, reguła sprawdzona na 120 stronach. "
                "Wynik zawiera prawdopodobieństwo także przy braku podpisu. "
                "Jev nie zlicza oznaczeń ani nie zwraca ich wycinków. "
                "Test połączenia wysyła mały obraz testowy."
            ),
        )
        return page

    def _build_processing_group(self) -> QGroupBox:
        group = QGroupBox("Przetwarzanie")
        form = QFormLayout(group)
        self.max_pages = QSpinBox()
        self.max_pages.setRange(1, 500)
        self.max_pages.setSuffix(" stron")
        form.addRow("Limit stron na dokument:", self.max_pages)

        self.image_side = QComboBox()
        for value in (768, 1024, 1120, 1400, 1600, 2048):
            self.image_side.addItem(f"{value} px", userData=value)
        form.addRow("Rozmiar obrazu dla modelu:", self.image_side)
        form.addRow(
            "",
            _hint_label(
                "Uwaga: dla gemma4 Ollama i tak zmniejsza obraz do ~0,65 Mpx "
                "(sztywny limit 280 tokenów wizyjnych po stronie Ollamy) — "
                "rozmiary powyżej 1120 px wykorzystają głównie modele chmurowe."
            ),
        )

        self.timeout = QSpinBox()
        self.timeout.setRange(30, 3600)
        self.timeout.setSuffix(" s")
        form.addRow("Limit czasu odpowiedzi:", self.timeout)

        self.recursive = QCheckBox("Przeszukuj podfoldery przy dodawaniu folderu")
        form.addRow("", self.recursive)
        return group

    def _build_prompt_group(self) -> QGroupBox:
        group = QGroupBox("Prompt programu — zaawansowane")
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
        reset = QPushButton("Przywróć domyślny")
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
        toggle = QPushButton("Pokaż")
        toggle.setCheckable(True)
        toggle.setFixedWidth(60)

        def on_toggle(checked: bool) -> None:
            edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
            toggle.setText("Ukryj" if checked else "Pokaż")

        toggle.toggled.connect(on_toggle)
        row.addWidget(edit, stretch=1)
        row.addWidget(toggle)
        clear = QPushButton("Wyczyść")
        clear.clicked.connect(edit.clear)
        row.addWidget(clear)
        return wrapper

    # -- konfiguracja ------------------------------------------------------

    def _load_config(self) -> None:
        cfg = self._config
        self.provider_combo.setCurrentIndex(_PROVIDER_ORDER.index(cfg.provider))
        self.stack.setCurrentIndex(_PROVIDER_ORDER.index(cfg.provider))
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
        self.vjev_runtime_dir.setText(cfg.vjev_runtime_dir)
        self._on_provider_changed(self.provider_combo.currentIndex())

    def _collect_config(self) -> AppConfig:
        """Zbiera ustawienia z formularza (bez zapisywania)."""
        cfg = replace(self._config)
        cfg.provider = self.provider_combo.currentData()
        cfg.ollama_url = normalize_ai_endpoint(
            self.ollama_url.text(), "http://localhost:11434", "Ollamy"
        )
        cfg.ollama_model = self.ollama_model.currentText().strip() or "gemma4:12b"
        defaults = AppConfig()
        for provider, edit in self._url_edits.items():
            name = f"{provider}_base_url"
            setattr(
                cfg,
                name,
                normalize_ai_endpoint(
                    edit.text(), getattr(defaults, name), _PROVIDER_LABELS[provider]
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
        cfg.vjev_runtime_dir = self.vjev_runtime_dir.text().strip() or defaults.vjev_runtime_dir
        if self._prompt_family is not None:
            self._prompt_drafts[self._prompt_family] = self.prompt_edit.toPlainText().strip()
        if any(len(text) > MAX_CUSTOM_PROMPT_LENGTH for text in self._prompt_drafts.values()):
            raise ValueError(
                f"Prompt programu może mieć najwyżej {MAX_CUSTOM_PROMPT_LENGTH} znaków."
            )
        # Domyślną treść zapisujemy jako pustą — aktualizacja programu może
        # wtedy poprawić prompt bez ręcznej interwencji użytkownika.
        llm_text = self._prompt_drafts["llm"].strip()
        jev_text = self._prompt_drafts["jev"].strip()
        cfg.custom_prompt = "" if llm_text in ("", PROMPT_INSTRUCTIONS.strip()) else llm_text
        cfg.jev_custom_prompt = (
            "" if jev_text in ("", JEV_PROMPT_INSTRUCTIONS.strip()) else jev_text
        )
        return cfg

    def _current_api_key(self) -> str:
        provider = self.provider_combo.currentData()
        return self._key_edits[provider].text().strip()

    # -- akcje -------------------------------------------------------------

    def _on_provider_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.stack.updateGeometry()
        self.test_result.setText("")
        if self._prompt_family is not None:
            self._prompt_drafts[self._prompt_family] = self.prompt_edit.toPlainText()
        self._prompt_family = "jev" if self.provider_combo.currentData() == "vjev" else "llm"
        self.prompt_edit.setPlainText(self._prompt_drafts[self._prompt_family])
        self.image_side.setEnabled(self._prompt_family != "jev")
        self.image_side.setToolTip(
            "Jev używa stałych widoków 1120 px zgodnie ze sprawdzoną regułą."
            if self._prompt_family == "jev"
            else ""
        )
        self.prompt_hint.setText(
            "Instrukcje dla pięciu widoków Jev; program dodaje 9 pytań decyzyjnych. "
            "Jev nie generuje JSON. Zmiana promptu może zmienić skuteczność "
            "i wiarygodność kalibracji — przebadano prompt domyślny."
            if self._prompt_family == "jev"
            else "Część merytoryczna promptu wysyłanego do modelu dla każdej strony. "
            "Wymagany format odpowiedzi (JSON) program dokleja automatycznie — "
            "nie opisuj go tutaj."
        )

    def _default_prompt(self) -> str:
        return JEV_PROMPT_INSTRUCTIONS if self._prompt_family == "jev" else PROMPT_INSTRUCTIONS

    def _on_refresh_models(self) -> None:
        if self._models_worker is not None:
            return
        try:
            url = normalize_ai_endpoint(self.ollama_url.text(), "http://localhost:11434", "Ollamy")
        except ValueError as exc:
            self.ollama_status.setText(str(exc))
            self.ollama_install_help.setVisible(False)
            return
        self.refresh_models.setEnabled(False)
        self.ollama_status.setText("Sprawdzanie Ollamy i listy modeli…")
        self.ollama_install_help.setText(_OLLAMA_INSTALL_HELP)
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
            self.ollama_status.setText(f"Ollama działa — znaleziono {len(models)} modeli.")
            self.ollama_install_help.setVisible(False)
        else:
            self.ollama_status.setText("Ollama działa, ale nie ma pobranego żadnego modelu.")
            self.ollama_install_help.setText(
                "Uruchom w PowerShell: <code>ollama pull gemma4:12b</code>, a potem odśwież listę."
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
            "Zatrzymywanie lokalnego Jev…"
            if stop_local
            else "Łączenie / ładowanie lokalnego modelu…"
            if self.provider_combo.currentData() == "vjev"
            else "Łączenie…"
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

    def _on_test_finished(self, ok: bool, message: str) -> None:
        prefix = "✔ " if ok else "✘ "
        self.test_result.setText(prefix + message)
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
            QMessageBox.critical(self, "Niepoprawne ustawienia AI", str(exc))
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
                "Magazyn poświadczeń",
                "Nie udało się zapisać klucza API w magazynie poświadczeń systemu.\n"
                "Nie zapisano wszystkich kluczy. Sprawdź dostęp do magazynu i spróbuj ponownie.",
            )
            return
        config.save()
        self.accept()

    # -- sprzątanie --------------------------------------------------------

    def _update_busy_state(self) -> None:
        busy = self._test_worker is not None or self._models_worker is not None
        self.buttons.setEnabled(not busy)
        self.provider_combo.setEnabled(not busy)
        self.stack.setEnabled(not busy)
        self.test_button.setEnabled(self._test_worker is None)
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
                "Trwa sprawdzanie połączenia",
                "Zaczekaj na zakończenie bieżącego testu usługi AI, a następnie zamknij okno.",
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
        self.setWindowTitle("Uwaga: model online")
        self.setModal(True)
        layout = QVBoxLayout(self)
        message = QLabel(
            "<b>Dane opuszczą ten komputer.</b><br><br>"
            "Wybrana konfiguracja nie jest lokalna — każda analizowana strona "
            "dokumentu będzie wysyłana przez sieć do zewnętrznej usługi AI "
            "(dostawcy chmurowego albo zdalnej Ollamy). Jeżeli dokumenty zawierają "
            "dane osobowe lub poufne, "
            "upewnij się, że masz do tego podstawę (np. zgodę administratora "
            "danych)."
        )
        message.setWordWrap(True)
        message.setStyleSheet("color: #c62828;")
        layout.addWidget(message)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Anuluj")
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
            self.accept_button.setText(f"Rozumiem zagrożenie ({self._remaining})")
            self.accept_button.setEnabled(False)
        else:
            self.accept_button.setText("Rozumiem zagrożenie")
            self.accept_button.setEnabled(True)


def _hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #666; font-size: 11px;")
    return label


def _online_warning_label() -> QLabel:
    label = QLabel(
        "⚠ Model online — analizowane dokumenty będą wysyłane przez internet "
        "do zewnętrznego dostawcy."
    )
    label.setWordWrap(True)
    label.setStyleSheet("color: #c62828; font-weight: 600;")
    return label
