"""Localized classification controls preserve model contracts and user-owned text."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from signum.ai.base import AIResponseError, PageAnalysis
from signum.ai.basic_analysis import parse_basic_analysis
from signum.ai.jev_additional import CATEGORIES, category_questions, enrich_analysis
from signum.ai.jev_client import _parse_decisions
from signum.ai.jev_prompts import decision_questions
from signum.ai.model_profiles import ModelProfile
from signum.config import AppConfig
from signum.i18n import set_language
from signum.ui.classification_panel import ClassificationPanel
from signum.ui.models_dialog import ModelsDialog


def test_english_classification_preserves_saved_task(qtbot, monkeypatch, tmp_path):
    categories = [["Umowa użytkownika", "Opis użytkownika"], ["Inne", "Pozostałe pliki"]]
    instructions = "Nie zmieniaj mojej instrukcji."
    AppConfig(
        classification_categories=json.dumps(categories), classification_prompt=instructions
    ).save()
    monkeypatch.setattr(
        "signum.ui.classification_panel.session_path", lambda: tmp_path / "collection.json"
    )
    set_language("en")
    panel = ClassificationPanel()
    qtbot.addWidget(panel)

    assert panel.start_button.text() == "Categorize"
    assert panel.categories.horizontalHeaderItem(0).text() == "Label"
    assert panel.category_values()[:2] == [tuple(row) for row in categories]
    assert panel.prompt.toPlainText() == instructions
    panel.save_preferences()
    saved = AppConfig.load()
    assert json.loads(saved.classification_categories)[:2] == categories
    assert saved.classification_prompt == instructions


def test_english_model_editor_preserves_profile_values(qtbot, monkeypatch):
    monkeypatch.setattr("signum.ui.models_dialog.get_api_key", lambda _: "")
    profile = ModelProfile(
        "my-id", name="Mój model", model="gemma4:12b", threshold=0.731, hitl_margin=0.043
    )
    set_language("en")
    dialog = ModelsDialog(AppConfig(), [profile])
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "AI settings"
    assert dialog.custom_thresholds.text() == "Custom thresholds"
    assert dialog.provider.currentData() == "ollama"
    dialog._store()
    assert dialog.profiles == [profile]


def test_jev_localizes_descriptions_without_changing_questions_or_scores():
    response = {
        "answers": {
            "handwritten": {"type": "noul", "noul": 0.8},
            "initials": {"type": "noul", "noul": 0.1},
            "stamp": {"type": "noul", "noul": 0.2},
            "document_type": {"type": "choice", "choice": "contract"},
        }
    }
    polish_questions = decision_questions()
    polish_categories = category_questions()
    polish = _parse_decisions(response)
    set_language("en")
    english = _parse_decisions(response)
    assert (polish.description, english.description) == ("Umowa", "Contract")
    assert polish.signatures == english.signatures
    assert decision_questions() == polish_questions
    assert category_questions() == polish_categories

    def decide(_image, _prompt, _questions):
        return {
            "answers": {
                key: {"type": "noul", "noul": 0.9 if key == "contract" else 0.1}
                for key in CATEGORIES
            }
        }

    with Image.new("RGB", (20, 20)) as image:
        result = enrich_analysis(image, PageAnalysis("", ()), decide)
    assert result.description == "Contract"
    assert not result.signatures


def test_english_presence_errors_and_review_reasons_keep_decision_scores():
    set_language("en")
    with pytest.raises(AIResponseError, match="Invalid presence score: signature_probability"):
        parse_basic_analysis('{"signature_probability": null, "stamp_probability": 0}')
    result = parse_basic_analysis(
        '{"signature_probability": 0.49, "stamp_probability": 0}',
        threshold=0.5,
        hitl_margin=0.05,
    )
    assert not result.signatures
    assert result.signature_score == 0.49
    assert result.review_reasons
    assert "signature/initials presence" in result.review_reasons[0]
