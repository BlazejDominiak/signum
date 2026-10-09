"""Connection probes verify model access without evaluating document labels."""
from __future__ import annotations

import threading
from functools import partial
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QWidget

from signum.ai.model_profiles import ModelProfile
from signum.ai.text_classifiers import (
    APITextClassifier,
    GemmaTextClassifier,
    JevK5TextClassifier,
    VeniceTextClassifier,
)
from signum.config import AppConfig
from signum.setup_local_ai import LocalAIPreparer
from signum.ui.models_dialog import TextConnectionTestWorker


@pytest.mark.parametrize("provider", ["venice", "jevk5"])
@pytest.mark.parametrize("score", [0.0, 0.5, 1.0])
def test_decisions_connection_accepts_any_valid_score(provider, score):
    answer = {"type": "noul", "noul": score}
    if provider == "venice":
        client = VeniceTextClassifier(AppConfig(), threading.Event(), Mock(), api_key="test-key")
        client.session.post = Mock(return_value=Mock(
            status_code=200, json=Mock(return_value={"answers": {"document_type": answer}}),
        ))
    else:
        client = JevK5TextClassifier(AppConfig(), threading.Event())
        client._request = Mock(return_value=answer)
    try:
        client.check_connection()
        if provider == "venice":
            call = client.session.post.call_args
            assert call.args[0].endswith("/decisions")
            assert client.session.headers["Authorization"] == "Bearer test-key"
            payload = call.kwargs["json"]
            assert payload["model"] == "jev-latest"
            question = payload["questions"]["document_type"]
        else:
            question = client._request.call_args.args[2]
        assert question["type"] == "noul"
        assert "criteria" not in question
        assert "categor" not in question["instructions"].lower()
    finally:
        client.close()


@pytest.mark.parametrize("answer", [{}, {"type": "noul"}, {"type": "noul", "noul": float("nan")}])
def test_decisions_connection_rejects_invalid_protocol(answer):
    client = JevK5TextClassifier(AppConfig(), threading.Event())
    client._request = Mock(return_value=answer)
    with pytest.raises(ValueError):
        client.check_connection()


def make_chat_client(protocol, monkeypatch):
    profile = ModelProfile(
        "probe", provider="api", api_format=protocol if protocol != "ollama" else "openai",
        model="selected-model", url="https://models.example.test/v1",
    )
    if protocol != "ollama":
        return APITextClassifier(profile, AppConfig(), "test-key")
    monkeypatch.setattr("signum.ai.text_classifiers.OllamaVisionModel", Mock())
    return GemmaTextClassifier(AppConfig(
        classification_ollama_url=profile.url, classification_ollama_model=profile.model,
    ), api_key="test-key")


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "ollama"])
@pytest.mark.parametrize("content", ["Connection works.", ""])
def test_chat_connection_accepts_text_without_categories(protocol, content, monkeypatch):
    client = make_chat_client(protocol, monkeypatch)
    payloads = {
        "openai": {"choices": [{"message": {"content": content}}]},
        "anthropic": {"content": [{"type": "text", "text": content}]},
        "ollama": {"message": {"content": content}},
    }
    client.session.post = Mock(return_value=Mock(
        status_code=200, json=Mock(return_value=payloads[protocol]),
    ))
    try:
        if content:
            client.check_connection()
        else:
            with pytest.raises(ValueError, match="treści odpowiedzi"):
                client.check_connection()
        sent = client.session.post.call_args.kwargs["json"]
        assert sent["model"] == "selected-model"
        assert "format" not in sent
        assert "categor" not in str(sent).lower()
        assert "json" not in str(sent).lower()
    finally:
        client.close()


@pytest.mark.parametrize("protocol", ["decisions", "openai", "anthropic", "ollama"])
def test_connection_rejects_authentication_failure(protocol, monkeypatch):
    if protocol == "decisions":
        client = VeniceTextClassifier(AppConfig(), threading.Event(), Mock(), api_key="bad-key")
    else:
        client = make_chat_client(protocol, monkeypatch)
    client.session.post = Mock(return_value=Mock(status_code=401))
    try:
        with pytest.raises(ValueError, match="HTTP 401"):
            client.check_connection()
    finally:
        client.close()


def test_connection_worker_reports_failure_and_closes_client(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    client = Mock(check_connection=Mock(side_effect=ValueError("API zwróciło HTTP 401.")))
    monkeypatch.setattr("signum.ui.models_dialog.create_text_classifier", Mock(return_value=client))
    worker = TextConnectionTestWorker(ModelProfile("a"), AppConfig(), "bad-key", parent)
    results = []
    worker.result.connect(lambda ok, message: results.append((ok, message)))
    worker.run()
    assert len(results) == 1 and not results[0][0]
    assert "401" in results[0][1]
    client.classify.assert_not_called()
    client.close.assert_called_once_with()


@pytest.mark.parametrize("provider", ["jevk5", "ollama"])
@pytest.mark.parametrize("fails", [False, True])
def test_setup_checks_model_connection_without_classifying(provider, fails, tmp_path, monkeypatch):
    client = Mock()
    if fails:
        client.check_connection.side_effect = ValueError("probe failed")
    preparer = LocalAIPreparer(
        tmp_path, Mock(), threading.Event(), check_only=True, custom_model="custom-text",
    )
    if provider == "jevk5":
        monkeypatch.setattr("signum.setup_local_ai.jevk5_files", Mock())
        monkeypatch.setattr("signum.setup_local_ai.probe_runtime", Mock(return_value="OK"))
        monkeypatch.setattr(
            "signum.ai.text_classifiers.JevK5TextClassifier", Mock(return_value=client),
        )
        check = partial(preparer.check_jevk5, AppConfig())
    else:
        monkeypatch.setattr("signum.setup_local_ai.requests.Session", Mock())
        monkeypatch.setattr("signum.ai.ollama_client.OllamaVisionModel.list_models",
                            Mock(return_value=["custom-text"]))
        monkeypatch.setattr(
            "signum.ai.text_classifiers.GemmaTextClassifier", Mock(return_value=client),
        )
        check = partial(preparer.prepare_ollama, {"ollama"}, AppConfig())
    if fails:
        with pytest.raises(ValueError, match="probe failed"):
            check()
        assert not preparer.verified_models
    else:
        check()
    client.check_connection.assert_called_once_with()
    client.classify.assert_not_called()
    client.close.assert_called_once_with()
