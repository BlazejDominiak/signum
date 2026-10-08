"""User-facing installation and repair entry point, shared with installer preparation."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from signum.ai.base import AIConnectionError
from signum.config import AppConfig
from signum.local_components import COMPONENT_LABELS, THIRD_PARTY_NOTICE, find_ollama, jevk5_files
from signum.setup_local_ai import run_setup_dialog


class ComponentsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Składniki AI — instalacja i naprawa")
        self.resize(830, 620)
        layout = QVBoxLayout(self)
        intro = QLabel("Wybierz lokalne składniki do instalacji lub sprawdzenia.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.choices: dict[str, QCheckBox] = {}
        self.states: dict[str, QLabel] = {}
        for key, label in COMPONENT_LABELS.items():
            check = QCheckBox(label)
            self.choices[key] = check
            layout.addWidget(check)
            status = QLabel()
            status.setTextFormat(Qt.TextFormat.PlainText)
            self.states[key] = status
            layout.addWidget(status)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("Inny model z biblioteki Ollamy, np. nazwa:tag")
        layout.addWidget(self.custom)
        library = QLabel('<a href="https://ollama.com/library">Przeglądaj modele Ollamy</a>')
        library.setOpenExternalLinks(True)
        layout.addWidget(library)
        layout.addWidget(QLabel("Folder modeli, bibliotek i plików tymczasowych:"))
        row = QHBoxLayout()
        self.directory = QLineEdit(config.ai_directory)
        row.addWidget(self.directory, 1)
        browse = QPushButton("Wybierz folder…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)
        space = QLabel(
            "Przeznacz 20 GB na Ollamę z modelem i po 35 GB na Jev / JevK5. "
            "Działająca Ollama zachowuje swój folder modeli."
        )
        space.setWordWrap(True)
        layout.addWidget(space)
        note = QLabel(THIRD_PARTY_NOTICE)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.ollama_directory = QLineEdit(config.ollama_models_directory)
        self.ollama_directory.setPlaceholderText("Niestandardowy folder modeli istniejącej Ollamy")
        layout.addWidget(self.ollama_directory)
        details = QPushButton("Szczegóły instalacji")
        details.setCheckable(True)
        optional = (space, note, library, self.custom, self.ollama_directory)
        for widget in optional:
            widget.hide()
        details.toggled.connect(lambda shown: [widget.setVisible(shown) for widget in optional])
        layout.addWidget(details)
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        actions = QHBoxLayout()
        for text, check_only in (("Sprawdź", True), ("Instaluj / napraw", False)):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, check=check_only: self._run(check))
            actions.addWidget(button)
        close = QPushButton("Zamknij")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._refresh()

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder składników AI", self.directory.text())
        if path:
            self.directory.setText(path)

    def _refresh(self) -> None:
        self.states["ollama"].setText(
            "Wykryto program — wymaga testu"
            if find_ollama(self.config)
            else "Nie wykryto programu; test sprawdzi działającą usługę"
        )
        for key in ("ollama\\small", "ollama\\large"):
            self.states[key].setText("Sprawdź dostępność i działanie modelu")
        for key in ("jev", "jevk5"):
            try:
                if key == "jevk5":
                    jevk5_files(self.config)
                else:
                    from signum.ai.local_vjev import _runtime_paths  # noqa: PLC0415

                    _runtime_paths(self.config.vjev_runtime_dir)
                state = "Wykryto pliki — wymaga testu bibliotek i modelu"
            except (ValueError, RuntimeError, AIConnectionError):
                state = "Niekompletna lub niewykryta instalacja — wybierz Instaluj / napraw"
            self.states[key].setText(state)

    def _run(self, check_only: bool) -> None:
        selected = {key for key, check in self.choices.items() if check.isChecked()}
        custom = self.custom.text().strip()
        if custom or selected & {"ollama\\small", "ollama\\large"}:
            selected.add("ollama")
        if not selected:
            self.result_label.setText("Zaznacz składniki do sprawdzenia lub instalacji.")
            return
        if custom.endswith("cloud"):
            self.result_label.setText(
                "Model chmurowy skonfiguruj w Ustawieniach AI; nie wymaga pobierania."
            )
            return
        args = [
            "--setup-local-ai",
            "--ai-components",
            ",".join(sorted(selected)),
            "--ai-directory",
            self.directory.text().strip(),
            "--check-only" if check_only else "--repair",
        ]
        if self.ollama_directory.text().strip():
            args += ["--ollama-model-directory", self.ollama_directory.text().strip()]
        if custom:
            args += ["--ollama-model", custom]
        # Only a configured local endpoint is handed to preparation; never a cloud URL.
        from signum.network import is_loopback_endpoint  # noqa: PLC0415

        if is_loopback_endpoint(self.config.ollama_url):
            args += ["--existing-ollama-url", self.config.ollama_url]
        try:
            ok = run_setup_dialog(args) == 0
        except Exception as exc:
            QMessageBox.warning(self, "Składniki AI", str(exc))
            return
        loaded = AppConfig.load()
        for field in fields(AppConfig):
            setattr(self.config, field.name, getattr(loaded, field.name))
        self._refresh()
        outcomes = {}
        try:
            report = Path(self.directory.text()) / "setup-result.json"
            data = json.loads(report.read_text(encoding="utf-8"))
            outcomes = data.get("components", {})
        except (OSError, ValueError, AttributeError):
            pass
        for key in selected:
            state = outcomes.get("ollama" if key.startswith("ollama") else key)
            self.states[key].setText(
                "Test działania: OK" if state == "ready" or (state is None and ok)
                else "Niegotowy — szczegóły w logu"
            )
        self.result_label.setText(
            "Testy zakończone poprawnie."
            if ok
            else "Nie wszystkie składniki przeszły test. Szczegóły: "
            + str(Path(self.directory.text()) / "setup.log")
        )
