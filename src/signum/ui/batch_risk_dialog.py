"""Shared confirmation before processing either document queue."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from signum.config import AppConfig
from signum.network import processing_is_local


class _AcknowledgementText(QLabel):
    """Zawijana etykieta, której kliknięcie przełącza powiązane pole."""

    def __init__(self, text: str, checkbox: QCheckBox) -> None:
        super().__init__(text)
        self._checkbox = checkbox
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setBuddy(checkbox)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — API Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._checkbox.click()
        super().mousePressEvent(event)


class BatchRiskDialog(QDialog):
    """Jednorazowe potwierdzenie ryzyka przed analizą całej kolejki dokumentów."""

    def __init__(
        self,
        config: AppConfig,
        file_count: int,
        parent: QWidget | None = None,
        *,
        classification: bool = False,
        remote_targets: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Przed uruchomieniem analizy")
        self.setModal(True)
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)
        heading = QLabel(f"<b>Do analizy wybrano {file_count} dokumentów.</b>")
        layout.addWidget(heading)

        limitations = QLabel(
            "Wyniki kategoryzacji mogą być błędne lub niepełne. Sprawdź je przed użyciem."
            if classification
            else "Signum służy do nauki i eksperymentów z wykrywaniem podpisów. "
            "Wyniki AI mogą być błędne lub niepełne. Program nie potwierdza "
            "autentyczności ani ważności podpisu."
        )
        limitations.setWordWrap(True)
        layout.addWidget(limitations)

        is_local = processing_is_local(config.provider, config.api_base_url)
        if config.provider == "ollama" and config.ollama_model.lower().endswith("cloud"):
            is_local = False
        if remote_targets is not None:
            is_local = not remote_targets
        if is_local:
            processing_text = (
                "Tryb lokalny: wybrane dokumenty będą analizowane przez model AI na tym komputerze."
            )
            processing_ack_text = (
                "Rozumiem, że treść wybranych dokumentów będzie przetwarzana "
                "przez lokalny model AI."
            )
        else:
            processing_text = (
                "Tryb zdalny: wybrane dokumenty opuszczą komputer. Ich treść będzie "
                "przetwarzana przez zewnętrzną usługę AI."
            )
            processing_ack_text = (
                "Rozumiem, że treść wybranych dokumentów będzie przesyłana przez "
                "internet do usług stron trzecich i tam przetwarzana."
            )

        if remote_targets:
            processing_text += "\nAPI: " + ", ".join(remote_targets)
        processing = QLabel(processing_text)
        processing.setTextFormat(Qt.TextFormat.PlainText)
        processing.setWordWrap(True)
        processing.setStyleSheet(f"color: {'#555' if is_local else '#c62828'};")
        layout.addWidget(processing)

        self.purpose_ack = QCheckBox(
            "Rozumiem, że narzędzie jest edukacyjne i nie nadaje się do użytku w organizacjach."
        )
        self.processing_ack = QCheckBox(processing_ack_text)
        self._acknowledgements = (
            self.purpose_ack,
            self.processing_ack,
        )
        for checkbox in self._acknowledgements:
            checkbox.setTristate(False)
            checkbox.setAccessibleName(checkbox.text())
            label = _AcknowledgementText(checkbox.text(), checkbox)
            checkbox.setText("")
            checkbox.stateChanged.connect(self._update_accept_state)
            row = QHBoxLayout()
            row.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label, 1)
            layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.accept_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.accept_button.setText("Rozumiem — uruchom analizę")
        self.accept_button.setEnabled(False)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText("Anuluj")
        cancel_button.setDefault(True)
        layout.addWidget(buttons)

    def _update_accept_state(self) -> None:
        self.accept_button.setEnabled(
            all(checkbox.isChecked() for checkbox in self._acknowledgements)
        )
