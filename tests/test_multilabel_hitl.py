"""Multilabel decisions, uncertainty, human review and file routing contracts."""

from __future__ import annotations

import csv
import io
import json
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt

from signum.ai.jev_signature import THRESHOLD, parse_signature_views
from signum.ai.model_profiles import ModelProfile
from signum.ai.text_classifiers import JevK5TextClassifier, VeniceTextClassifier
from signum.config import AppConfig
from signum.core.classification import (
    DEFAULT_CATEGORIES,
    DEFAULT_INSTRUCTIONS,
    ClassificationBatch,
    ClassificationRow,
    apply_classification,
    confirm_categories,
    make_question,
)
from signum.core.classification_calibration import policy_for, question_identity
from signum.core.collection_session import load_collection, save_collection
from signum.core.filing import build_filing_plan, execute_filing
from signum.core.models import DocumentStatus
from signum.core.pipeline import BatchResult, CancelToken, DocumentAnalyzer
from signum.report.export import build_csv, build_html
from signum.ui.classification_panel import ClassificationPanel, LabelReviewDialog
from tests.test_filing import collection
from tests.test_jev_client import _quality_answer

LABELS = {"c01": "Umowy", "c02": "Finanse", "c03": "Raporty"}


def test_multiple_labels_and_uncertain_rejection_are_preserved():
    row = ClassificationRow(Path("x.pdf"), "model", 0, threshold=0.4, hitl_margin=0.1)
    apply_classification(row, {"label_scores": {"c01": 0.95, "c02": 0.5, "c03": 0.3}}, LABELS)
    assert row.selected_categories == ["Umowy", "Finanse"]
    assert row.confidence is None
    assert row.hitl and len(row.review_reasons) == 2
    assert all("Umowy;" not in reason for reason in row.review_reasons)
    assert row.label_scores["Raporty"] == 0.3


@pytest.mark.parametrize(
    "score,selected,hitl",
    [
        (0.1, False, False),
        (0.3, False, True),
        (0.399, False, True),
        (0.4, True, True),
        (0.5, True, True),
        (0.501, True, False),
        (0.95, True, False),
    ],
)
def test_threshold_boundaries(score, selected, hitl):
    row = ClassificationRow(Path("x.pdf"), "model", 0, threshold=0.4, hitl_margin=0.1)
    apply_classification(row, {"label_scores": {"c01": score}}, {"c01": "A"})
    assert bool(row.selected_categories) == selected
    assert row.hitl == hitl


@pytest.mark.parametrize(
    "scores",
    [
        {"c01": 0.8},
        {"c01": 0.8, "c02": 0.8, "c03": 0.8, "unknown": 0.9},
        {"c01": True, "c02": 0.8, "c03": 0.8},
        {"c01": float("nan"), "c02": 0.8, "c03": 0.8},
        {"c01": 1.1, "c02": 0.8, "c03": 0.8},
    ],
)
def test_malformed_scores_cannot_publish_partial_labels(scores):
    row = ClassificationRow(Path("x.pdf"), "model", 0, threshold=0.4)
    with pytest.raises(ValueError):
        apply_classification(row, {"label_scores": scores}, LABELS)
    assert not row.category and not row.label_scores


def test_uncalibrated_scores_and_generated_choices_require_review():
    row = ClassificationRow(Path("x.pdf"), "model", 0)
    apply_classification(row, {"label_scores": dict.fromkeys(LABELS, 0.95)}, LABELS)
    assert row.hitl and row.threshold is None and not row.category
    assert len(row.label_scores) == 3
    apply_classification(row, {"choices": ["c01", "c03"]}, LABELS)
    assert row.hitl and row.selected_categories == ["Umowy", "Raporty"]


def test_human_review_preserves_evidence_and_can_choose_no_labels(tmp_path):
    row = ClassificationRow(tmp_path / "x.pdf", "model", 0, threshold=0.4, hitl_margin=0.1)
    apply_classification(row, {"label_scores": dict.fromkeys(LABELS, 0.5)}, LABELS)
    confirm_categories(row, ["Umowy", "Finanse"])
    assert not row.hitl and row.model_review_reasons and len(row.label_scores) == 3
    assert row.model_category == "Umowy; Finanse; Raporty"
    confirm_categories(row, [])
    assert row.selected_categories == [] and row.category == ""
    batch = ClassificationBatch(rows=[row], categories=[(v, "") for v in LABELS.values()])
    saved = tmp_path / "collection.json"
    save_collection([row.path], batch, saved)
    _, restored = load_collection(saved)
    assert restored.rows == [row]


def test_venice_requests_independent_noul_scores(monkeypatch):
    client = VeniceTextClassifier(AppConfig(), threading.Event(), lambda _: None, api_key="")
    q = make_question([("A", "a"), ("B", "b")], "Select all")
    request = Mock(
        return_value=Mock(
            status_code=200,
            json=lambda: {
                "answers": {
                    "c01": {"type": "noul", "noul": 0.95},
                    "c02": {"type": "noul", "noul": 0.9},
                }
            },
        )
    )
    monkeypatch.setattr(client.session, "post", request)
    result = client.classify("evidence", q)
    assert result["label_scores"] == {"c01": 0.95, "c02": 0.9}
    questions = request.call_args.kwargs["json"]["questions"]
    assert all(v["type"] == "noul" for v in questions.values())
    assert all(
        "A: a" in v["instructions"] and "B: b" in v["instructions"] for v in questions.values()
    )
    client.close()


def test_local_model_discards_batch_if_cancelled(monkeypatch):
    from signum.core.classification import ClassificationCancelledError

    cancel = threading.Event()
    client = JevK5TextClassifier(AppConfig(), cancel)
    calls = []

    def answer(*args):
        calls.append(args)
        cancel.set()
        return {"type": "noul", "noul": 0.9}

    monkeypatch.setattr(client, "_request", answer)
    with pytest.raises(ClassificationCancelledError):
        client.classify("evidence", make_question([("A", ""), ("B", "")], "Select all"))
    assert len(calls) == 1


def test_local_model_submits_all_labels_in_one_request(monkeypatch):
    client = JevK5TextClassifier(AppConfig(), threading.Event())
    question = make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS)
    response = {"answers": {key: {"type": "noul", "noul": .95}
                            for key in question["criteria"]}}
    request = Mock(return_value=response)
    monkeypatch.setattr(client, "_request", request)
    result = client.classify("evidence", question)
    assert len(result["label_scores"]) == 12
    request.assert_called_once()
    assert request.call_args.args[0] == "classify_many"
    assert set(request.call_args.args[2]) == set(question["criteria"])
    assert all(q["type"] == "noul" for q in request.call_args.args[2].values())


def test_local_model_prepares_the_complete_list_in_one_request(monkeypatch):
    client = JevK5TextClassifier(AppConfig(), threading.Event())
    request = Mock(return_value={"text": "shorter"})
    monkeypatch.setattr(client, "_request", request)
    question = make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS)
    assert client.prepare("evidence", question) == "shorter"
    request.assert_called_once()
    assert request.call_args.args[0] == "prepare_many"
    assert len(request.call_args.args[2]) == 12


def test_copy_routes_each_label_but_move_waits_for_one_destination(tmp_path):
    files, batch, root = collection(tmp_path)
    confirm_categories(batch.rows[0], ["Umowy", "Finanse"])
    plan = build_filing_plan(files[:1], batch, "model", 0, root, "copy")
    assert plan.ready == 2
    result = execute_filing(plan, threading.Event())
    assert len(result.completed) == 2 and files[0].exists()
    assert {x.target.parent.name for x in result.completed} == {"Umowy", "Finanse"}
    plan = build_filing_plan(files[:1], batch, "model", 0, root, "move")
    assert not plan.ready and "Wiele etykiet" in plan.entries[0].skip


def test_unreviewed_hitl_is_not_filed(tmp_path):
    files, batch, root = collection(tmp_path)
    batch.rows[0].hitl = True
    plan = build_filing_plan(files[:1], batch, "model", 0, root, "copy")
    assert not plan.ready and "HITL" in plan.entries[0].skip


def test_review_dialog_supports_multiple_labels_and_visible_hitl(qtbot):
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    row = ClassificationRow(Path("x.pdf"), "model", 0, threshold=0.4, hitl_margin=0.1)
    apply_classification(row, {"label_scores": {"c01": 0.95, "c02": 0.5, "c03": 0.1}}, LABELS)
    panel._row_done(row)
    assert panel.table.item(0, 6).text() == "HITL"
    assert "Finanse" in panel.table.item(0, 6).toolTip()
    dialog = LabelReviewDialog(row, list(LABELS.values()), panel)
    qtbot.addWidget(dialog)
    assert dialog.selected_labels() == ["Umowy", "Finanse"]
    dialog.labels.item(2).setCheckState(Qt.CheckState.Checked)
    assert len(dialog.selected_labels()) == 3


@pytest.mark.parametrize(
    "score,hitl",
    [(0.1, False), (0.435, True), (0.534, True), (0.535, True), (0.635, True), (0.95, False)],
)
def test_signature_hitl_does_not_change_optimized_decision(score, hitl):
    result = parse_signature_views([_quality_answer(score, stamp=0)] * 5)
    assert result.signature_threshold == THRESHOLD == 0.535
    assert result.signature_score == score
    assert bool(result.signatures) == (score >= 0.535)
    assert bool(result.review_reasons) == hitl


def test_uncertain_negative_signature_survives_pipeline_and_reports(tmp_path):
    from PIL import Image

    from signum.ai.jev_client import JevVisionModel
    from tests.test_jev_client import _response

    path = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(path)
    model = JevVisionModel("http://localhost:8800/v1", "vjev-vision")
    model._session.request = Mock(return_value=_response(_quality_answer(0.5, stamp=0)))
    result = DocumentAnalyzer(model, 1, 768).analyze(path, CancelToken())
    assert result.status == DocumentStatus.OK and not result.is_signed and result.hitl
    assert result.page_decision_scores == {1: 0.5}
    assert "HITL" in result.signature_label and "0.535" in result.review_summary
    batch = BatchResult(results=[result])
    assert "HITL" in build_html(batch)
    rows = list(csv.DictReader(io.StringIO(build_csv(batch)), delimiter=";"))
    assert rows[0]["hitl"] and "0.535" in rows[0]["powody_hitl"]




def test_custom_prompt_never_inherits_another_calibration():
    profile = ModelProfile(
        "v",
        provider="api",
        url="https://api.venice.ai/api/v1",
        model="jev-latest",
        api_format="decisions",
    )
    assert policy_for(profile, make_question([("A", ""), ("B", "")], "Custom")) == {}


def test_bundled_profile_is_bound_to_model_and_reviews_only_near_threshold(monkeypatch):
    from importlib import resources
    policies = json.loads(
        (resources.files("signum.core") / "classification_profiles.json").read_text("utf-8")
    )
    question = make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS)
    venice = ModelProfile("v", provider="api", url="https://api.venice.ai/api/v1",
                          model="jev-latest", api_format="decisions")
    policy = policy_for(venice, question)
    assert policy["threshold"] == .74 and policy["hitl_margin"] == .03
    assert not policy["review_reason"] and not policy["review_labels"]
    assert policy["status"] == "threshold_review"
    venice.model = "other-model"
    assert policy_for(venice, question) == {}
    local = ModelProfile("j", provider="jevk5", model_dir="weights", runtime="runtime")
    identity = next(p["local_identity"] for p in policies if p["model"] == "jevk5")
    monkeypatch.setattr("signum.core.classification_calibration.local_identity",
                        lambda *_: identity)
    assert policy_for(local, question)["threshold"] == .83
    monkeypatch.setattr("signum.core.classification_calibration.local_identity",
                        lambda *_: "different-weights")
    assert policy_for(local, question) == {}


def test_profile_warning_keeps_high_scores_in_review_until_human_confirms():
    row = ClassificationRow(Path("x.pdf"), "model", 0, threshold=.74, hitl_margin=.22,
                            calibration_warning="HITL — walidacja wymaga sprawdzenia.")
    apply_classification(row, {"label_scores": {"a": .99, "b": .01}}, {"a": "A", "b": "B"})
    assert row.selected_categories == ["A"] and row.hitl
    assert row.review_reasons == [row.calibration_warning]
    confirm_categories(row, ["A", "B"])
    assert not row.hitl and row.model_review_reasons


def test_profile_propagates_through_real_batch(tmp_path, text_pdf_bytes):
    from signum.core.classification import run_classification
    path = tmp_path / "sample.pdf"
    path.write_bytes(text_pdf_bytes)
    client = Mock()
    client.classify.return_value = {"label_scores": {"c01": .9, "c02": .85}}
    client.loading_s = 0
    batch = run_classification(
        [path], [("A", ""), ("B", "")], "Choose all", ["profile"], 1,
        threading.Event(), lambda _: client, lambda text, _: text,
        policies={"profile": {"threshold": .8, "hitl_margin": .1, "id": "measured",
                              "review_reason": "HITL — validation", "review_labels": []}},
    )
    assert not batch.error and len(batch.rows) == 1
    row = batch.rows[0]
    assert row.selected_categories == ["A", "B"] and row.hitl
    assert row.threshold == .8 and row.calibration_id == "measured"


def test_packaged_windows_app_includes_the_calibration_resource():
    root = Path(__file__).resolve().parents[1]
    assert "classification_profiles.json" in (root / "packaging/signum.spec").read_text("utf-8")


def test_top3_ranks_scores_and_retains_omitted_evidence():
    labels = dict(zip(("a", "b", "c", "d", "e"), ("A", "B", "C", "D", "E"), strict=True))
    row = ClassificationRow(Path("x.pdf"), "model", 0, threshold=0.4, hitl_margin=0.1)
    apply_classification(
        row, {"label_scores": {"a": 0.97, "b": 0.99, "c": 0.96, "d": 0.98, "e": 0.1}}, labels
    )
    assert row.selected_categories == ["B", "D", "A"]
    assert row.label_scores["C"] == 0.96
    assert not row.hitl


def test_top3_ties_are_stable_and_does_not_fill_below_threshold():
    labels = {"c04": "D", "c02": "B", "c01": "A", "c03": "C"}
    row = ClassificationRow(Path("x.pdf"), "model", 0, threshold=0.8)
    apply_classification(row, {"label_scores": dict.fromkeys(labels, 0.95)}, labels)
    assert row.selected_categories == ["A", "B", "C"]
    apply_classification(
        row, {"label_scores": {"c04": 0.9, "c02": 0.3, "c01": 0.2, "c03": 0.1}}, labels
    )
    assert row.selected_categories == ["D"]


def test_top3_intentional_fourth_omission_does_not_trigger_threshold_warning():
    row = ClassificationRow(Path("x.pdf"), "model", 0, threshold=0.4, hitl_margin=0.1)
    labels = {key: key.upper() for key in ("a", "b", "c", "d")}
    apply_classification(
        row, {"label_scores": {"a": 0.99, "b": 0.98, "c": 0.97, "d": 0.45}}, labels
    )
    assert not row.hitl and row.selected_categories == ["A", "B", "C"]
    apply_classification(
        row, {"label_scores": {"a": 0.99, "b": 0.98, "c": 0.49, "d": 0.45}}, labels
    )
    assert row.hitl and len(row.review_reasons) == 1
    assert "C;" in row.review_reasons[0]


def test_generated_choices_keep_the_models_order_and_are_capped():
    row = ClassificationRow(Path("x.pdf"), "model", 0)
    apply_classification(
        row, {"choices": ["d", "b", "a", "c"]}, dict(zip("abcd", "ABCD", strict=True))
    )
    assert row.selected_categories == ["D", "B", "A"] and row.hitl


def test_manual_review_cannot_save_four_labels(qtbot):
    row = ClassificationRow(Path("x.pdf"), "model", 0)
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    dialog = LabelReviewDialog(row, list("ABCD"), panel)
    qtbot.addWidget(dialog)
    for i in range(4):
        dialog.labels.item(i).setCheckState(Qt.CheckState.Checked)
    assert not dialog.save_button.isEnabled()
    assert "4/3" in dialog.selection_hint.text()
    with pytest.raises(ValueError, match="maksymalnie 3"):
        confirm_categories(row, dialog.selected_labels())
    assert row.category_source == "model" and not row.selected_categories
    dialog.labels.item(3).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.save_button.isEnabled()
    confirm_categories(row, dialog.selected_labels())
    assert row.selected_categories == ["A", "B", "C"]


def test_old_unlimited_calibration_is_not_reused(monkeypatch, tmp_path):
    from importlib import resources

    import signum.core.classification_calibration as calibration

    profiles = json.loads(
        (resources.files("signum.core") / "classification_profiles.json").read_text("utf-8")
    )
    for p in profiles:
        p.pop("max_labels", None)
    (tmp_path / "classification_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
    monkeypatch.setattr(calibration.resources, "files", lambda _: tmp_path)
    profile = ModelProfile(
        "v",
        provider="api",
        url="https://api.venice.ai/api/v1",
        model="jev-latest",
        api_format="decisions",
    )
    assert policy_for(profile, make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS)) == {}






def test_error_hitl_opens_error_explanation(qtbot, monkeypatch):
    warning = Mock()
    opening = Mock()
    monkeypatch.setattr("signum.ui.classification_panel.QMessageBox.warning", warning)
    monkeypatch.setattr("signum.ui.classification_panel.QDesktopServices.openUrl", opening)
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    panel._row_done(ClassificationRow(Path("x.pdf"), "model", 0, error="Brak tekstu", hitl=True))
    panel._open_document(0, 6)
    warning.assert_called_once()
    opening.assert_not_called()


@pytest.mark.parametrize(
    "contract_score,report_score,exit_code", [(0.99, 0.01, 0), (0.01, 0.99, 1)]
)
def test_local_runtime_smoke_check_uses_multilabel_scores(
    monkeypatch, tmp_path, contract_score, report_score, exit_code
):
    from signum.app import _self_test_classification

    client = Mock()
    client.prepare.return_value = "contract"
    client.classify.return_value = {"label_scores": {"c01": contract_score, "c02": report_score}}
    monkeypatch.setattr("signum.ai.text_classifiers.JevK5TextClassifier", lambda *args: client)
    monkeypatch.setattr(
        AppConfig, "load", lambda: AppConfig(classification_cache_dir=str(tmp_path))
    )
    assert _self_test_classification() == exit_code
    client.close.assert_called_once()


def _policy_review_row(model, scores):
    from importlib import resources


    policy = next(
        p
        for p in json.loads(
            (resources.files("signum.core") / "classification_profiles.json").read_text("utf-8")
        )
        if p["model"] == model
    )
    assert policy["question_sha256"] == question_identity(
        make_question(list(DEFAULT_CATEGORIES), DEFAULT_INSTRUCTIONS)
    )
    row = ClassificationRow(
        Path("x.pdf"),
        model,
        0,
        threshold=policy["threshold"],
        hitl_margin=policy["hitl_margin"],
        calibration_id=policy["id"],
        calibration_warning=policy["review_reason"],
        review_labels=[DEFAULT_CATEGORIES[int(k[1:]) - 1][0] for k in policy["review_labels"]],
    )
    labels = {f"c{i + 1:02d}": name for i, (name, _) in enumerate(DEFAULT_CATEGORIES)}
    apply_classification(
        row, {"label_scores": {key: scores.get(key, 0.01) for key in labels}}, labels
    )
    return row


@pytest.mark.parametrize("model", ["venice", "jevk5"])
def test_bundled_policy_does_not_flag_high_scores_or_sparse_category_alone(model):
    row = _policy_review_row(model, {"c01": 0.99, "c07": 0.95})
    assert len(row.selected_categories) == 2
    assert not row.hitl and not row.review_reasons


@pytest.mark.parametrize("model,threshold", [("venice", 0.74), ("jevk5", 0.83)])
@pytest.mark.parametrize(
    "offset,expected", [(-0.031, False), (-0.03, True), (0.03, True), (0.031, False)]
)
def test_bundled_policy_keeps_narrow_two_sided_review_band(model, threshold, offset, expected):
    row = _policy_review_row(model, {"c01": threshold + offset})
    assert row.hitl is expected
    assert bool(row.selected_categories) is (offset >= 0)


def test_review_policy_refresh_preserves_labels_manual_work_and_errors():
    from copy import deepcopy

    from signum.core.classification_calibration import refresh_review_policy

    model = "venice"
    auto = _policy_review_row(model, {"c01": 0.99, "c07": 0.95})
    auto.hitl = True
    auto.hitl_margin = 0.22
    auto.calibration_warning = "Old blanket warning"
    auto.review_reasons = [auto.calibration_warning]
    auto.calibration_id = "multilabel120-venice-20261009-top3-v2"
    reviewed = deepcopy(auto)
    confirm_categories(reviewed, [DEFAULT_CATEGORIES[0][0]])
    failed = deepcopy(auto)
    failed.error = "Brak tekstu"
    unknown = deepcopy(auto)
    unknown.calibration_id = "unrelated-model-measurement"
    batch = ClassificationBatch(
        rows=[auto, reviewed, failed, unknown],
        categories=list(DEFAULT_CATEGORIES),
        instructions=DEFAULT_INSTRUCTIONS,
    )
    old_auto = deepcopy(auto)
    untouched = deepcopy(batch.rows[1:])
    profile = ModelProfile(
        "venice",
        provider="api",
        url="https://api.venice.ai/api/v1",
        model="jev-latest",
        api_format="decisions",
    )
    assert refresh_review_policy(batch, [profile]) == 1
    assert auto.selected_categories == old_auto.selected_categories
    assert auto.label_scores == old_auto.label_scores and auto.threshold == old_auto.threshold
    assert not auto.hitl and not auto.review_reasons
    assert auto.hitl_margin == 0.03
    assert batch.rows[1:] == untouched
    assert refresh_review_policy(batch, [profile]) == 0


def test_review_policy_refresh_never_changes_labels_or_custom_prompt():
    from copy import deepcopy

    from signum.core.classification_calibration import refresh_review_policy

    row = _policy_review_row("venice", {"c01": 0.99})
    row.calibration_id = "multilabel120-venice-20261009-top3-v2"
    row.hitl = True
    row.category = "Different previous assignment"
    row.assigned_categories = [row.category]
    batch = ClassificationBatch(
        rows=[row], categories=list(DEFAULT_CATEGORIES), instructions=DEFAULT_INSTRUCTIONS
    )
    profile = ModelProfile(
        "venice",
        provider="api",
        url="https://api.venice.ai/api/v1",
        model="jev-latest",
        api_format="decisions",
    )
    before = deepcopy(row)
    assert refresh_review_policy(batch, [profile]) == 0
    assert row == before
    row.category = DEFAULT_CATEGORIES[0][0]
    row.assigned_categories = [row.category]
    batch.instructions = "Changed instructions"
    assert refresh_review_policy(batch, [profile]) == 0


def test_ui_restores_old_hitl_with_current_policy_and_saves_it(qtbot, monkeypatch):
    from signum.ai.model_profiles import dump_profiles

    row = _policy_review_row("venice", {"c01": 0.99, "c07": 0.95})
    row.path = Path("H:/recorded.pdf")
    row.hitl = True
    row.review_reasons = ["Old blanket warning"]
    row.calibration_warning = row.review_reasons[0]
    row.calibration_id = "multilabel120-venice-20261009-top3-v2"
    batch = ClassificationBatch(
        rows=[row], categories=list(DEFAULT_CATEGORIES), instructions=DEFAULT_INSTRUCTIONS
    )
    profile = ModelProfile(
        "venice",
        provider="api",
        url="https://api.venice.ai/api/v1",
        model="jev-latest",
        api_format="decisions",
    )
    config = AppConfig(classification_models=dump_profiles([profile]))
    config.save()
    save_collection([row.path], batch)
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    assert not panel.rows[0].hitl and panel.table.item(0, 6).text() == "OK"
    assert panel.rows[0].selected_categories == row.selected_categories
    assert not load_collection()[1].rows[0].hitl
