"""User decision policies survive editing and drive real classification/detection paths."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
from PIL import Image

from signum.ai import create_vision_model
from signum.ai.model_profiles import ModelProfile, dump_profiles, load_profiles
from signum.config import AppConfig, signature_settings
from signum.core.classification import DEFAULT_CATEGORIES, DEFAULT_INSTRUCTIONS, make_question
from signum.core.classification_calibration import policy_for, refresh_review_policy
from signum.core.collection_session import load_collection, save_collection
from signum.core.models import SignatureKind
from signum.core.pipeline import BatchResult, CancelToken, DocumentAnalyzer
from signum.report.export import build_csv, build_html
from signum.ui.classification_worker import ClassificationWorker
from signum.ui.models_dialog import ModelsDialog
from signum.ui.settings_dialog import SettingsDialog
from tests.test_additional_analysis import CATEGORIES, nouls
from tests.test_jev_client import _quality_answer, _response


@pytest.mark.parametrize("value", [True, "0.4", -0.1, 1.1, float("nan"), float("inf")])
def test_invalid_saved_probabilities_revert_to_defaults(isolated_config, value):
    defaults = AppConfig()
    names = [name for name in defaults.__slots__ if name.endswith(("threshold", "hitl_margin"))]
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(json.dumps(dict.fromkeys(names, value)), encoding="utf-8")
    loaded = AppConfig.load()
    assert all(getattr(loaded, name) == getattr(defaults, name) for name in names)
    profile = ModelProfile("p", model="gemma4:12b", threshold=value)
    assert load_profiles(AppConfig(classification_models=dump_profiles([profile]))) == []


@pytest.mark.parametrize("value", [0, 1, 0.617])
def test_probability_endpoints_and_roundtrip(isolated_config, value):
    cfg = AppConfig(vjev_threshold=value, vjev_hitl_margin=value, ollama_threshold=value)
    cfg.classification_models = dump_profiles([
        ModelProfile("p", model="gemma4:12b", threshold=value, hitl_margin=value),
    ])
    cfg.save()
    loaded = AppConfig.load()
    assert loaded.vjev_threshold == loaded.vjev_hitl_margin == loaded.ollama_threshold == value
    assert load_profiles(loaded)[0].threshold == load_profiles(loaded)[0].hitl_margin == value


def test_signature_dialog_roundtrip_modes_reset_and_cancel(qtbot, monkeypatch):
    monkeypatch.setattr("signum.ui.settings_dialog.get_api_key", lambda _: "")
    cfg = AppConfig()
    dialog = SettingsDialog(cfg)
    qtbot.addWidget(dialog)
    for name, spin in dialog._decision_edits.items():
        assert spin.value() == getattr(cfg, name)
        spin.setValue(0.617)
    dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("vjev"))
    dialog.vjev_additional_analysis.setChecked(True)
    loaded = dialog._collect_config()
    loaded.save()
    loaded = AppConfig.load()
    assert all(getattr(loaded, name) == .617 for name in dialog._decision_edits)
    assert cfg == AppConfig()  # Opening/editing is isolated until the caller accepts.
    dialog._reset_decisions((("vjev_threshold", ""), ("vjev_hitl_margin", "")))
    assert dialog._collect_config().vjev_threshold == .535
    assert dialog._collect_config().vjev_hitl_margin == .10
    assert dialog._collect_config().ollama_threshold == .617
    dialog.reject()
    assert cfg == AppConfig()


def test_classification_dialog_defaults_switch_duplicate_and_reset(qtbot, monkeypatch):
    monkeypatch.setattr("signum.ui.models_dialog.get_api_key", lambda _: "")
    profiles = [
        ModelProfile("gemma", model="gemma4:12b"),
        ModelProfile("venice", provider="api", api_format="decisions", model="jev-latest",
                     url="https://api.venice.ai/api/v1"),
        ModelProfile("jevk5", provider="jevk5", python="python", packages="packages",
                     runtime="runtime", model_dir="model"),
    ]
    dialog = ModelsDialog(AppConfig(), profiles)
    qtbot.addWidget(dialog)
    for index, expected in enumerate(((.65, .05), (.74, .03), (.83, .03))):
        dialog.list.setCurrentRow(index)
        assert (dialog.threshold.value(), dialog.hitl_margin.value()) == expected
        assert not dialog.custom_thresholds.isChecked()
    dialog.custom_thresholds.setChecked(True)
    dialog.threshold.setValue(.812)
    dialog.hitl_margin.setValue(.027)
    dialog._duplicate()
    assert dialog.threshold.value() == .812 and dialog.hitl_margin.value() == .027
    dialog.threshold.setValue(.9)
    dialog.list.setCurrentRow(2)
    assert dialog.threshold.value() == .812
    dialog.reset_thresholds.click()
    assert dialog.threshold.value() == .83 and dialog.hitl_margin.value() == .03
    dialog._store()
    assert dialog.profiles[2].threshold is None and dialog.profiles[2].hitl_margin is None
    assert dialog.profiles[3].threshold == .9
    assert profiles[2].threshold is None


def test_override_drives_worker_and_saved_results_stay_frozen(
    tmp_path, text_pdf_bytes, monkeypatch,
):
    document = tmp_path / "source.pdf"
    document.write_bytes(text_pdf_bytes)
    profile = ModelProfile("custom", model="gemma4:12b", threshold=.7, hitl_margin=.04)
    cfg = AppConfig(classification_models=dump_profiles([profile]))
    client = Mock(loading_s=0)
    client.classify.return_value = {"label_scores": {"c01": .72, "c02": .4}}
    monkeypatch.setattr("signum.ui.classification_worker.create_text_classifier",
                        lambda *args: client)
    batches = []
    worker = ClassificationWorker(cfg, [document], [("A", ""), ("B", "")],
                                  "Custom instructions", ["custom"], 1)
    worker.batch_done.connect(batches.append)
    worker.run()
    assert len(batches) == 1 and not batches[0].error
    row = batches[0].rows[0]
    assert not row.error and row.selected_categories == ["A"] and row.hitl
    assert (row.threshold, row.hitl_margin, row.calibration_id) == (.7, .04, "user-defined")
    path = tmp_path / "collection.json"
    save_collection([document], batches[0], path)
    _, restored = load_collection(path)
    assert refresh_review_policy(restored, [replace(profile, threshold=.9, hitl_margin=.01)]) == 0
    assert restored.rows[0] == row
    cfg.classification_models = dump_profiles([replace(profile, threshold=.9, hitl_margin=.01)])
    worker.run()
    assert not batches[1].rows[0].selected_categories and not batches[1].rows[0].hitl
    assert batches[0].rows[0] == row


def test_default_calibration_is_unchanged_and_custom_prompt_can_use_explicit_values():
    profile = ModelProfile("g", model="gemma4:12b")
    question = make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS)
    assert policy_for(profile, question)["threshold"] == .65
    assert policy_for(profile, question)["hitl_margin"] == .05
    custom = make_question([("A", ""), ("B", "")], "Custom")
    assert policy_for(profile, custom) == {}
    policy = policy_for(replace(profile, threshold=.6, hitl_margin=.02), custom)
    assert policy["threshold"] == .6 and policy["id"] == "user-defined"


def test_jev_changes_decision_and_negative_hitl_reaches_reports(tmp_path):
    path = tmp_path / "scan.png"
    Image.new("RGB", (100, 100), "white").save(path)
    cfg = AppConfig(provider="vjev", vjev_threshold=.7, vjev_hitl_margin=.05,
                    vjev_stamp_threshold=.9)
    model = create_vision_model(cfg, api_key="")
    model._session.request = Mock(return_value=_response(_quality_answer(.68, stamp=.8)))
    result = DocumentAnalyzer(model, 1, 768).analyze(path, CancelToken())
    assert not result.is_signed and not result.findings and result.hitl
    assert result.page_decision_thresholds == {1: .7}
    batch = BatchResult(results=[result], analysis_settings=signature_settings(cfg))
    assert "0.700" in build_html(batch)
    csv_row = next(csv.DictReader(io.StringIO(build_csv(batch)), delimiter=";"))
    assert "0.700" in csv_row["powody_hitl"]
    cfg.vjev_threshold, cfg.vjev_hitl_margin = .6, .01
    model = create_vision_model(cfg, api_key="")
    model._session.request = Mock(return_value=_response(_quality_answer(.68, stamp=.8)))
    result = DocumentAnalyzer(model, 1, 768).analyze(path, CancelToken())
    assert result.is_signed and not result.hitl


def test_ollama_basic_uses_both_thresholds_and_negative_hitl():
    cfg = AppConfig(ollama_additional_analysis=False, ollama_threshold=.7,
                    ollama_stamp_threshold=.9, ollama_hitl_margin=.03)
    model = create_vision_model(cfg, api_key="")
    model._post_chat = Mock(return_value='{"signature_probability":0.68,"stamp_probability":0.8}')
    result = model.analyze_page(b"jpeg")
    assert not result.signatures and result.review_reasons and result.signature_threshold == .7
    assert result.signature_probability == .68


@pytest.mark.parametrize("provider", ["ollama", "openai", "anthropic"])
def test_generated_findings_filter_before_cropping_and_keep_rejected_hitl(provider):
    cfg = AppConfig(provider=provider)
    model = create_vision_model(cfg, api_key="")
    response = json.dumps({"description": "Example", "signatures": [
        {"type": "handwritten", "confidence": 68, "box_2d": [100, 100, 200, 200]},
        {"type": "handwritten", "confidence": 95, "box_2d": [500, 500, 600, 600]},
    ]})
    model._generate = Mock(return_value=response)
    assert len(model.analyze_page(b"jpeg").signatures) == 2
    setattr(cfg, "ollama_full_threshold" if provider == "ollama" else provider + "_threshold", .7)
    setattr(cfg, provider + "_hitl_margin", .03)
    model = create_vision_model(cfg, api_key="")
    model._generate = Mock(return_value=response)
    result = model.analyze_page(b"jpeg")
    assert len(result.signatures) == 1 and result.signatures[0].confidence == 95
    assert result.review_reasons and result.signature_threshold == .7


def test_jev_additional_thresholds_reach_categories_regions_and_verification():
    cfg = AppConfig(provider="vjev", vjev_additional_analysis=True,
                    vjev_category_threshold=.8, vjev_candidate_threshold=.7,
                    vjev_verify_threshold=.8, vjev_single_threshold=.9)
    values = dict.fromkeys(CATEGORIES, .1)
    values.update(contract=.75, medical=.85)
    replies = [_quality_answer(.9, stamp=0)] * 5 + [nouls(values)]
    replies += [nouls({"fragment": .75 if i == 5 else .6, "stamp": .1}) for i in range(20)]
    replies += [nouls({"signature": .85, "single_signature": .85, "stamp": .1})]
    model = create_vision_model(cfg, api_key="")
    model._decide = Mock(side_effect=replies)
    result = model.analyze_image(Image.new("RGB", (400, 500)), 1120)
    assert result.description == "Dokumentacja medyczna"
    assert len(result.signatures) == 1 and result.signatures[0].box_2d is not None
    assert "kilka podpisów" in result.signatures[0].detail
    # A stricter verification threshold removes the crop, not the presence decision.
    cfg.vjev_verify_threshold = .9
    model = create_vision_model(cfg, api_key="")
    model._decide = Mock(side_effect=[*replies, replies[-1]])
    result = model.analyze_image(Image.new("RGB", (400, 500)), 1120)
    assert result.signatures[0].kind == SignatureKind.HANDWRITTEN
    assert result.signatures[0].box_2d is None
