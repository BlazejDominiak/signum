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
from signum.i18n import tr
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
        self.setWindowTitle(tr("main.batch_risk_dialog.before_starting_analysis"))
        self.setModal(True)
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)
        heading = QLabel(
            tr("main.batch_risk_dialog.documents_selected_for_analysis", arg0=file_count)
        )
        layout.addWidget(heading)

        limitations = QLabel(
            tr("main.batch_risk_dialog.classification_results_may_be_incorrect_or_incomplete")
            if classification
            else tr("main.batch_risk_dialog.signum_is_intended_for_learning_and_experimenting")
        )
        limitations.setWordWrap(True)
        layout.addWidget(limitations)

        is_local = processing_is_local(
            config.provider,
            config.api_base_url,
            config.ollama_model,
        )
        if remote_targets is not None:
            is_local = not remote_targets
        if is_local:
            processing_text = tr(
                "main.batch_risk_dialog.local_mode_selected_documents_will_be_analyzed"
            )
            processing_ack_text = tr(
                "main.batch_risk_dialog.i_understand_that_the_content_of_selected"
            )
        else:
            processing_text = tr(
                "main.batch_risk_dialog.remote_mode_selected_documents_will_leave_this"
            )
            processing_ack_text = tr(
                "main.batch_risk_dialog.i_understand_that_the_content_of_selected_161"
            )

        if remote_targets:
            processing_text += "\nAPI: " + ", ".join(remote_targets)
        processing = QLabel(processing_text)
        processing.setTextFormat(Qt.TextFormat.PlainText)
        processing.setWordWrap(True)
        processing.setStyleSheet(f"color: {'#555' if is_local else '#c62828'};")
        layout.addWidget(processing)

        self.purpose_ack = QCheckBox(
            tr("main.batch_risk_dialog.i_understand_that_this_tool_is_educational")
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
        self.accept_button.setText(tr("main.batch_risk_dialog.i_understand_start_analysis"))
        self.accept_button.setEnabled(False)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText(tr("main.batch_risk_dialog.cancel"))
        cancel_button.setDefault(True)
        layout.addWidget(buttons)

    def _update_accept_state(self) -> None:
        self.accept_button.setEnabled(
            all(checkbox.isChecked() for checkbox in self._acknowledgements)
        )
