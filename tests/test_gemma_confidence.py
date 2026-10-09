"""Gemma confidence is a declared score, with selective rather than unconditional HITL."""
import json
from unittest.mock import Mock

import pytest

from signum.ai.text_classifiers import GemmaTextClassifier
from signum.config import AppConfig
from signum.core.classification import (
    ClassificationBatch,
    ClassificationRow,
    apply_classification,
    make_question,
    write_classification_report,
)
from signum.core.collection_session import load_collection, save_collection


@pytest.mark.parametrize("scores", [{"c01": .96, "c02": .03}, {"c01": .96},
                                   {"c01": .96, "c02": True}])
def test_gemma_requests_confidence_for_every_label_in_one_response(monkeypatch, scores):
    monkeypatch.setattr("signum.ai.text_classifiers.OllamaVisionModel", Mock())
    client = GemmaTextClassifier(AppConfig(
        classification_ollama_url="https://models.example.test",
        classification_ollama_model="gemma",
    ), api_key="")
    post = Mock(return_value=Mock(status_code=200, json=lambda: {
        "message": {"content": json.dumps({"label_scores": scores})},
    }))
    monkeypatch.setattr(client.session, "post", post)
    question = make_question([("Contract", ""), ("Finance", "")], "Select all")
    try:
        if scores == {"c01": .96, "c02": .03}:
            assert client.classify("evidence", question) == {
                "label_scores": scores, "score_source": "declared",
            }
        else:
            with pytest.raises(ValueError):
                client.classify("evidence", question)
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        assert "confidence" in payload["messages"][0]["content"]
        assert payload["format"]["properties"]["label_scores"]["required"] == ["c01", "c02"]
    finally:
        client.close()


@pytest.mark.parametrize("score,hitl", [(.99, False), (.71, True), (.10, False)])
def test_declared_confidence_controls_hitl_and_survives_export(tmp_path, score, hitl):
    row = ClassificationRow(tmp_path / "document.pdf", "gemma", 0, threshold=.70, hitl_margin=.03)
    apply_classification(row, {
        "label_scores": {"c01": score, "c02": .01}, "score_source": "declared",
    }, {"c01": "Contract", "c02": "Finance"})
    assert row.hitl == hitl
    assert row.score_source == "declared"
    assert row.selected_categories == (["Contract"] if score >= .70 else [])
    batch = ClassificationBatch(rows=[row])
    saved = tmp_path / "collection.json"
    save_collection([row.path], batch, saved)
    _, restored = load_collection(saved)
    assert restored.rows[0] == row
    report = tmp_path / "report.csv"
    write_classification_report(report, batch)
    assert "declared" in report.read_text(encoding="utf-8-sig")


def test_gemma_calibration_applies_only_to_the_evaluated_model_and_question():
    from dataclasses import replace

    from signum.ai.model_profiles import ModelProfile
    from signum.core.classification import DEFAULT_CATEGORIES, DEFAULT_INSTRUCTIONS
    from signum.core.classification_calibration import policy_for

    profile = ModelProfile("gemma", model="gemma4:12b")
    question = make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS)
    policy = policy_for(profile, question)
    assert policy["score_source"] == "declared"
    assert policy["threshold"] == .65 and policy["hitl_margin"] == .05
    assert policy_for(replace(profile, model="gemma4:e2b"), question) == {}
    assert policy_for(replace(profile, url="https://models.example.test"), question) == {}
    assert policy_for(profile, make_question([("A", ""), ("B", "")], "Custom")) == {}
