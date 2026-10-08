"""Functional checks for independent classification and reproducible model comparison."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path

import pytest

from signum.ai.text_classifiers import VeniceTextClassifier, conservative_text_limit
from signum.config import AppConfig
from signum.core.classification import (
    DEFAULT_CATEGORIES,
    DEFAULT_INSTRUCTIONS,
    ClassificationCancelledError,
    extract_document,
    make_question,
    run_classification,
    write_classification_report,
)
from signum.ui.main_window import MainWindow


def test_custom_categories_and_bounds():
    question = make_question([("Oferta", "Sprzedaż"), ("Inne", "")], "Wybierz rodzaj pisma.")
    assert question["criteria"] == {"c01": "Oferta: Sprzedaż", "c02": "Inne"}
    for categories in (
        [("X", "")],
        [("X", ""), ("x", "")],
        [("x" + str(i), "") for i in range(13)],
    ):
        with pytest.raises(ValueError):
            make_question(categories, "Wybierz")


def test_comparison_prepares_once_and_releases_models(tmp_path, text_pdf_bytes):
    paths = [tmp_path / "one.pdf", tmp_path / "two.pdf"]
    for path in paths:
        path.write_bytes(text_pdf_bytes)
    events, calls, preparations = [], [], []

    class Client:
        def __init__(self, model):
            self.model = model
            events.append((model, "open"))

        def classify(self, text, question):
            calls.append((self.model, text, question))
            return {"choice": "c01", "confidence": 0.8}

        def close(self):
            events.append((self.model, "close"))

    def prepare(text, question):
        preparations.append(text)
        return text[:100]

    batch = run_classification(
        paths,
        list(DEFAULT_CATEGORIES),
        DEFAULT_INSTRUCTIONS,
        ["jevk5", "gemma", "venice"],
        2,
        threading.Event(),
        Client,
        prepare,
    )
    assert not batch.error and not batch.cancelled
    assert len(preparations) == 2
    assert events == [
        (m, stage) for m in ("jevk5", "gemma", "venice") for stage in ("open", "close")
    ]
    assert len(batch.rows) == 12
    assert len(calls) == 12  # no unmeasured warmup requests
    for path in paths:
        assert len({r.text_sha256 for r in batch.rows if r.path == path}) == 1
    assert all(r.category == DEFAULT_CATEGORIES[0][0] for r in batch.rows)
    report = tmp_path / "report.json"
    write_classification_report(report, batch)
    exported = json.loads(report.read_text(encoding="utf-8"))
    assert all("text" not in doc for doc in exported["documents"])
    assert exported["repeats"] == 2


def test_cancel_closes_current_model_and_does_not_start_next(tmp_path, text_pdf_bytes):
    path = tmp_path / "document.pdf"
    path.write_bytes(text_pdf_bytes)
    cancel = threading.Event()
    closed = []

    class Client:
        def prepare_model(self):
            cancel.set()  # user cancels while loading

        def classify(self, text, question):
            pytest.fail("Cancelled before inference")

        def close(self):
            closed.append(True)

    batch = run_classification(
        [path],
        list(DEFAULT_CATEGORIES),
        DEFAULT_INSTRUCTIONS,
        ["gemma", "venice"],
        1,
        cancel,
        lambda _: Client(),
        lambda text, _: text,
    )
    assert batch.cancelled and not batch.rows and closed == [True]


def test_no_text_does_not_become_a_category(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    doc = extract_document(path, threading.Event())
    assert not doc.text and "OCR" in doc.error


def test_venice_rate_wait_is_cancellable_without_sending(monkeypatch):
    monkeypatch.setattr("signum.ai.text_classifiers.venice_key", lambda _: "test-only")
    cancel = threading.Event()
    client = VeniceTextClassifier(AppConfig(), cancel, lambda _: cancel.set())
    client.starts = deque([time.monotonic()] * 100)
    monkeypatch.setattr(client.session, "post", lambda *a, **kw: pytest.fail("must not send"))
    try:
        with pytest.raises(ClassificationCancelledError):
            client.classify("text", make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS))
    finally:
        client.close()


def test_tokenizer_fallback_preserves_valid_unicode():
    text = "Zażółć 🐈" * 2000
    question = make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS)
    short = conservative_text_limit(text, question)
    assert text.startswith(short) and len(short) < len(text)
    assert "�" not in short


def test_separate_queues_and_persisted_custom_categories(qtbot, isolated_config, docs_dir: Path):
    from PySide6.QtWidgets import QTableWidgetItem

    window = MainWindow()
    qtbot.addWidget(window)
    panel = window.classification
    panel.add_files([docs_dir])
    assert len(panel.files) == 2
    assert not window._files
    panel.categories.setItem(0, 0, QTableWidgetItem("Moja kategoria"))
    panel.prompt.setPlainText("Wybierz kategorię dla mojego archiwum.")
    panel.save_preferences()
    window._remember_dir(docs_dir)  # the signature tab must preserve the other tab's settings
    saved = AppConfig.load()
    assert json.loads(saved.classification_categories)[0][0] == "Moja kategoria"
    assert saved.classification_prompt == "Wybierz kategorię dla mojego archiwum."
    assert window.mode_tabs.count() == 2
    window.mode_tabs.setCurrentIndex(1)
    assert not window.signature_toolbar.isVisibleTo(window)


def test_remote_ollama_is_identified_for_run_confirmation(qtbot, isolated_config):
    config = AppConfig(classification_ollama_url="https://ollama.example.test")
    config.save()
    window = MainWindow()
    qtbot.addWidget(window)
    panel = window.classification
    assert not panel.profiles[0].local
    assert panel.profiles[0].label == config.classification_ollama_model


def test_result_colors_and_metrics_survive_duplicate_additions(
    qtbot, isolated_config, docs_dir: Path
):
    from PySide6.QtCore import Qt

    from signum.core.classification import ClassificationRow

    AppConfig(classification_provider="all").save()
    window = MainWindow()
    qtbot.addWidget(window)
    panel = window.classification
    panel.add_files([docs_dir])
    path = panel.files[0]
    original = panel.categories.item(0, 0).text()
    panel.table.setRowCount(0)
    panel._row_done(ClassificationRow(path, "venice", 0, original, elapsed_s=1.25))
    assert panel.table.item(0, 2).data(Qt.ItemDataRole.UserRole) == 0
    panel.categories.item(0, 0).setText("Zmieniona kategoria")
    panel._row_done(ClassificationRow(path, "gemma", 0, original, elapsed_s=2.5))
    assert panel.table.item(1, 2).data(Qt.ItemDataRole.UserRole) == 0
    assert panel.metric_cards["venice"].value.text() == "1.25 s"
    panel.add_files([docs_dir])
    assert len(panel.rows) == 2
    assert panel.metric_cards["venice"].value.text() == "1.25 s"
    assert panel.progress.value() == 2
    panel.clear()
    assert panel.result_stack.currentIndex() == 0


def test_cancelled_comparison_shows_partial_time_and_progress(qtbot, isolated_config, docs_dir):
    from signum.core.classification import ClassificationBatch, ClassificationRow, TextDocument

    AppConfig(classification_provider="all").save()
    window = MainWindow()
    qtbot.addWidget(window)
    panel = window.classification
    panel.add_files([docs_dir])
    panel.table.setRowCount(0)
    panel._expected_rows = 6
    row = ClassificationRow(panel.files[0], "venice", 0, elapsed_s=3, wait_s=2)
    panel._row_done(row)
    panel._batch_done(ClassificationBatch(
        rows=[row], documents=[TextDocument(p) for p in panel.files], cancelled=True
    ))
    assert panel.progress.maximum() == 6 and panel.progress.value() == 1
    assert not panel.table.isColumnHidden(4)
    assert "Działanie: 3.00 s" in panel.metric_cards["venice"].detail.text()
    assert panel.status.text() == "Anulowano."
