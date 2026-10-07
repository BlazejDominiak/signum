"""Regression coverage for configurable models, consent, file access and stage timings."""

from __future__ import annotations

import csv
import io
import json
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from signum.ai.model_profiles import ModelProfile, dump_profiles, load_profiles
from signum.ai.text_classifiers import APITextClassifier, VeniceTextClassifier
from signum.config import AppConfig
from signum.core.classification import (
    DEFAULT_INSTRUCTIONS,
    LEGACY_DEFAULT_INSTRUCTIONS,
    ClassificationRow,
    TextDocument,
    make_question,
    run_classification,
    write_classification_report,
)
from signum.ui.classification_panel import ClassificationPanel
from signum.ui.models_dialog import ModelsDialog


def test_profiles_roundtrip_custom_models_and_disabled_selection(isolated_config):
    profiles = [
        ModelProfile("one", model="my-vision-model:latest"),
        ModelProfile(
            "two",
            name="My API",
            provider="api",
            model="custom-model",
            url="https://models.example.test/v1",
            enabled=False,
        ),
    ]
    cfg = AppConfig(classification_models=dump_profiles(profiles))
    cfg.save()
    assert load_profiles(AppConfig.load()) == profiles
    assert len(load_profiles(AppConfig())) == 1
    assert load_profiles(AppConfig())[0].provider == "ollama"
    assert len(load_profiles(AppConfig(classification_provider="all"))) == 3
    assert load_profiles(AppConfig(classification_models='{"invalid": true}')) == []


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "decisions"])
def test_custom_api_endpoint_model_and_credentials(monkeypatch, protocol):
    profile = ModelProfile(
        "custom",
        provider="api",
        model="user-model",
        url="https://service.example.test/v1",
        api_format=protocol,
    )
    if protocol == "decisions":
        client = VeniceTextClassifier(
            AppConfig(), threading.Event(), lambda _: None, profile, "private-test-key"
        )
        payload = {"answers": {"document_type": {"choice": "c01"}}}
        route = "/decisions"
    else:
        client = APITextClassifier(profile, AppConfig(), "private-test-key")
        payload = (
            {"content": [{"type": "text", "text": '{"category":"c01"}'}]}
            if protocol == "anthropic"
            else {"choices": [{"message": {"content": '{"category":"c01"}'}}]}
        )
        route = "/messages" if protocol == "anthropic" else "/chat/completions"
    post = Mock(return_value=Mock(status_code=200, json=Mock(return_value=payload)))
    monkeypatch.setattr(client.session, "post", post)
    try:
        result = client.classify(
            "Source document", make_question([("One", ""), ("Two", "")], DEFAULT_INSTRUCTIONS)
        )
        assert result["choice"] == "c01"
        assert post.call_args.args[0] == profile.url + route
        assert post.call_args.kwargs["json"]["model"] == "user-model"
        assert post.call_args.kwargs["allow_redirects"] is False
        header = "x-api-key" if protocol == "anthropic" else "Authorization"
        assert "private-test-key" in client.session.headers[header]
    finally:
        client.close()


def test_models_dialog_edits_refreshes_and_saves_independent_secrets(qtbot, monkeypatch):
    written = {}
    monkeypatch.setattr("signum.ui.models_dialog.get_api_key", lambda _: "old-secret")
    monkeypatch.setattr(
        "signum.ui.models_dialog.set_api_key", lambda slot, key: written.update({slot: key})
    )
    dialog = ModelsDialog(AppConfig(), [ModelProfile("a", model="first", key_slot="ollama")])
    qtbot.addWidget(dialog)
    dialog.model.setEditText("custom-choice")
    dialog._models_loaded(True, ["installed-one", "installed-two"])
    assert dialog.model.currentText() == "custom-choice"
    assert dialog.model.count() == 2
    dialog._duplicate()
    dialog.name.setText("Second API")
    dialog.provider.setCurrentIndex(dialog.provider.findData("api"))
    dialog.url.setText("https://models.example.test/v1")
    dialog.model.setEditText("second")
    dialog.key.setText("new-secret")
    dialog.list.item(0).setCheckState(Qt.CheckState.Unchecked)
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    first, second = dialog.profiles
    assert first.model == "custom-choice" and not first.enabled
    assert second.model == "second" and second.enabled
    assert written[first.credential_slot] == "old-secret"
    assert written[second.credential_slot] == "new-secret"
    assert "ollama" not in written
    serialized = dump_profiles(dialog.profiles)
    assert "old-secret" not in serialized and "new-secret" not in serialized


def test_connection_test_uses_unsaved_fields_without_saving_keys(qtbot, monkeypatch):
    captured = []
    client = Mock(classify=Mock(return_value={"choice": "c01"}))
    monkeypatch.setattr("signum.ui.models_dialog.get_api_key", lambda _: "")
    monkeypatch.setattr(
        "signum.ui.models_dialog.set_api_key", lambda *a: pytest.fail("Test must not save keys")
    )

    def factory(profile, config, cancel, **kwargs):
        captured.append((profile, kwargs["api_key"]))
        return client

    monkeypatch.setattr("signum.ui.models_dialog.create_text_classifier", factory)
    dialog = ModelsDialog(AppConfig(), [ModelProfile("a", model="original")])
    qtbot.addWidget(dialog)
    dialog.provider.setCurrentIndex(dialog.provider.findData("api"))
    dialog.url.setText("https://draft.example.test/v1")
    dialog.model.setEditText("draft-model")
    dialog.key.setText("draft-key")
    dialog._test()
    qtbot.waitUntil(lambda: dialog.worker is None, timeout=5000)
    assert captured[0][0].url == "https://draft.example.test/v1"
    assert captured[0][0].model == "draft-model"
    assert captured[0][1] == "draft-key"
    assert client.close.call_count == 1
    assert "Połączenie działa" in dialog.message.text()


@pytest.mark.parametrize("saved", ["", LEGACY_DEFAULT_INSTRUCTIONS, "My custom instructions"])
def test_prompt_visible_and_only_old_default_is_migrated(qtbot, isolated_config, saved):
    AppConfig(classification_prompt=saved).save()
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    assert not panel.prompt.isHidden()
    expected = saved if saved == "My custom instructions" else DEFAULT_INSTRUCTIONS
    assert panel.prompt.toPlainText() == expected


def test_pdf_open_works_for_queue_and_repeated_result_rows(
    qtbot,
    isolated_config,
    tmp_path,
    text_pdf_bytes,
    monkeypatch,
):
    path = tmp_path / "name with spaces.pdf"
    path.write_bytes(text_pdf_bytes)
    opened = []
    monkeypatch.setattr(
        "signum.ui.classification_panel.QDesktopServices.openUrl",
        lambda url: opened.append(Path(url.toLocalFile())) or True,
    )
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    panel.add_files([path])
    panel.table.cellDoubleClicked.emit(0, 0)
    panel.table.setRowCount(0)
    panel._row_done(ClassificationRow(path, panel.profiles[0].id, 0))
    panel._row_done(ClassificationRow(path, panel.profiles[0].id, 1))
    panel.table.cellDoubleClicked.emit(1, 2)
    assert opened == [path, path]


def test_classification_confirm_lists_only_selected_remote_targets_and_rejects(
    qtbot,
    isolated_config,
    tmp_path,
    text_pdf_bytes,
    monkeypatch,
):
    profiles = [
        ModelProfile("local", model="local"),
        ModelProfile("cloud", model="user-model:cloud"),
        ModelProfile(
            "off", provider="api", url="https://other.example.test/v1", model="off", enabled=False
        ),
    ]
    AppConfig(classification_models=dump_profiles(profiles)).save()
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    path = tmp_path / "one.pdf"
    path.write_bytes(text_pdf_bytes)
    panel.add_files([path])
    seen = []

    class Confirmation:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr("signum.ui.classification_panel.BatchRiskDialog", Confirmation)
    panel.start()
    assert panel.worker is None
    assert len(seen) == 1 and seen[0]["classification"]
    assert len(seen[0]["remote_targets"]) == 1
    assert "user-model:cloud" in seen[0]["remote_targets"][0]
    assert panel.table.rowCount() == 1


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def now(self):
        return self.seconds

    def advance(self, seconds):
        self.seconds += seconds


@pytest.mark.parametrize("cancel_during_request", [False, True])
def test_classification_timings_do_not_double_count_loading(
    monkeypatch,
    tmp_path,
    cancel_during_request,
):
    clock = Clock()
    cancel = threading.Event()
    monkeypatch.setattr("signum.core.classification.time.perf_counter", clock.now)

    def extract(path, cancel):
        clock.advance(2)
        return TextDocument(path, text="Evidence")

    def prepare(text, question):
        clock.advance(1)
        return text

    class Client:
        loading_s = 2

        def prepare_model(self):
            clock.advance(5)

        def classify(self, text, question):
            clock.advance(7)
            if cancel_during_request:
                from signum.core.classification import check_cancel

                cancel.set()
                check_cancel(cancel)
            return {"choice": "c01"}

        def close(self):
            clock.advance(0.5)

    def factory(name):
        assert name == "arbitrary-user-profile"
        clock.advance(0.25)
        return Client()

    monkeypatch.setattr("signum.core.classification.extract_document", extract)
    batch = run_classification(
        [tmp_path / "doc.pdf"],
        [("A", ""), ("B", "")],
        DEFAULT_INSTRUCTIONS,
        ["arbitrary-user-profile"],
        1,
        cancel,
        factory,
        prepare,
        model_labels={"arbitrary-user-profile": "My model"},
    )
    assert batch.preparation_s == 3
    assert batch.setup_seconds["arbitrary-user-profile"] == 7
    assert batch.rows[0].elapsed_s == 5
    assert batch.model_seconds["arbitrary-user-profile"] == 12.75
    assert batch.duration_s == 15.75
    assert batch.cancelled == cancel_during_request
    report = tmp_path / "report.csv"
    write_classification_report(report, batch)
    row = next(csv.DictReader(io.StringIO(report.read_text(encoding="utf-8-sig")), delimiter=";"))
    assert row["model_label"] == "My model"
    assert float(row["preparation_s"]) == 3
    assert float(row["model_loading_s"]) == 7
    assert float(row["batch_total_s"]) == 15.75


def test_failed_model_does_not_prevent_next_selected_model(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "signum.core.classification.extract_document",
        lambda path, _: TextDocument(path, text="Evidence"),
    )
    client = Mock(classify=Mock(return_value={"choice": "c02"}))

    # A simple class intentionally lacks prepare_model.
    class Client:
        def classify(self, text, question):
            return client.classify(text, question)

        def close(self):
            client.close()

    def factory(name):
        if name == "broken":
            raise ValueError("Unavailable")
        return Client()

    batch = run_classification(
        [tmp_path / "doc.pdf"],
        [("A", ""), ("B", "")],
        DEFAULT_INSTRUCTIONS,
        ["broken", "working"],
        1,
        threading.Event(),
        factory,
        lambda text, _: text,
    )
    assert not batch.error
    assert batch.rows[0].error == "Unavailable"
    assert batch.rows[1].category == "B"
    client.close.assert_called_once()


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("tracked_requests", [False, True])
def test_signature_timings_include_partial_failures(
    monkeypatch,
    tmp_path,
    fail,
    tracked_requests,
):
    from signum.ai.base import AIConnectionError, PageAnalysis
    from signum.core.pipeline import CancelToken, DocumentAnalyzer, run_batch
    from tests.test_pipeline import FakeVisionModel

    clock = Clock()
    monkeypatch.setattr("signum.core.pipeline.time.perf_counter", clock.now)
    monkeypatch.setattr("signum.core.pipeline.time.monotonic", clock.now)
    monkeypatch.setattr("signum.core.pipeline.time.time", clock.now)
    model = FakeVisionModel()
    if tracked_requests:
        model.request_seconds = 0.0
    analyzer = DocumentAnalyzer(model, max_pages=1, image_max_side=512)

    def model_call(page, cancel):
        clock.advance(7)
        model.loading_seconds += 3
        if tracked_requests:
            model.request_seconds += 5
        if fail:
            raise AIConnectionError("connection lost")
        return PageAnalysis("", ())

    def process(result, path, cancel):
        clock.advance(2)
        analyzer._analyze_visual_page(result, Mock(number=1), cancel)
        clock.advance(1)

    monkeypatch.setattr(analyzer, "_analyze_page_with_retry", model_call)
    monkeypatch.setattr(analyzer, "_analyze_into", process)
    batch = run_batch([tmp_path / "one.pdf"], analyzer, CancelToken())
    assert batch.loading_s == 3
    assert batch.inference_s == (2 if tracked_requests else 4)
    assert batch.preparation_s == (2 if fail else 3) + (2 if tracked_requests else 0)
    assert batch.duration_s == (9 if fail else 10)
    assert bool(batch.abort_error) == fail
    assert batch.results[0].duration_s == batch.duration_s


def test_reports_do_not_export_pdf_text_or_credentials(tmp_path):
    from signum.core.classification import ClassificationBatch

    batch = ClassificationBatch(
        documents=[TextDocument(Path("doc.pdf"), text="private document contents")],
        model_labels={"user-profile": "Custom API"},
        model_details={"user-profile": {"model": "user-model", "url": "https://api.example.test"}},
    )
    path = tmp_path / "report.json"
    write_classification_report(path, batch)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model_details"]["user-profile"]["model"] == "user-model"
    assert "private document contents" not in path.read_text(encoding="utf-8")
