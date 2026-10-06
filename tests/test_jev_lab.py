"""Leakage, calibration and corpus integrity checks for the research calculator."""

import hashlib
import importlib
import json
from itertools import pairwise
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[1] / "experiments" / "jev50"


def test_publisher_and_document_splits_are_disjoint():
    original = (LAB / "labels.json").read_bytes()
    parameters = json.loads((LAB / "heuristic.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(original).hexdigest() == parameters["labels_sha256"]
    samples = json.loads(original)["samples"]
    assert len(samples) == 100
    assert len({s["pdf_sha256"] for s in samples}) == 100
    assert len({s["id"] for s in samples}) == 100
    assert sum(s["has_signature"] for s in samples) == 50
    for field in ["group", "pdf_sha256", "document"]:
        dev = {s[field] for s in samples if s["split"] == "dev"}
        test = {s[field] for s in samples if s["split"] == "test"}
        assert not dev & test
    for split, count in [("dev", 30), ("test", 20)]:
        part = [s for s in samples if s["split"] == split]
        assert len(part) == count * 2
        assert sum(s["has_signature"] for s in part) == count


def test_training_never_requests_holdout_features(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(LAB))
    fit = importlib.import_module("fit_jev50")
    labels = json.loads((LAB / "labels.json").read_text(encoding="utf-8"))
    development = {s["id"] for s in labels["samples"] if s["split"] == "dev"}
    # Synthetic scores make fitting independent of local inference artifacts.
    truth = {s["id"]: s["has_signature"] for s in labels["samples"]}
    called = set()

    def features(_rows, sample):
        assert sample in development, "The fitting routine accessed held-out evidence"
        called.add(sample)
        return (
            {"synthetic": 0.8 if truth[sample] else 0.2},
            {"synthetic": 1.0},
            {"synthetic": {"requests": 1}},
        )

    monkeypatch.setattr(fit, "ROOT", tmp_path)
    monkeypatch.setattr(fit, "read_rows", lambda: dict.fromkeys(range(800)))
    monkeypatch.setattr(fit, "features", features)
    (tmp_path / "labels.json").write_bytes((LAB / "labels.json").read_bytes())
    fit.main()
    assert called == development
    with pytest.raises(RuntimeError, match="Frozen config exists"):
        fit.main()


def test_calculator_is_monotone_and_rejects_invalid_evidence(monkeypatch):
    monkeypatch.syspath_prepend(str(LAB))
    calculator = importlib.import_module("calculator")
    parameters = json.loads((LAB / "heuristic.json").read_text(encoding="utf-8"))
    decisions = [calculator.calculate(0.1, value / 100, parameters) for value in range(101)]
    assert all(
        first.calibrated_probability <= second.calibrated_probability
        for first, second in pairwise(decisions)
    )
    assert not decisions[0].has_signature
    assert decisions[-1].has_signature
    for invalid in [None, True, "0.5", float("nan"), float("inf"), -0.1, 1.1]:
        with pytest.raises(ValueError):
            calculator.calculate(invalid, 0.2, parameters)


def test_raw_recovery_only_removes_the_known_client_key_error(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(LAB))
    fit = importlib.import_module("fit_jev50")
    rows = [
        {
            "sample": "sample-a",
            "view": "full",
            "state": "default",
            "scores": {},
            "response": {"answers": {"binary": {"probabilities": {"present": 0.73}}}},
            "error": "KeyError('probs')",
        },
        {
            "sample": "sample-b",
            "view": "full",
            "state": "default",
            "scores": {},
            "response": {"answers": {"binary": {"probabilities": {"present": 0.12}}}},
            "error": "ValueError('another failure')",
        },
    ]
    monkeypatch.setattr(fit, "ROOT", tmp_path)
    raw = "\n".join(json.dumps(row) for row in rows)
    (tmp_path / "jev_raw.jsonl").write_text(raw, encoding="utf-8")
    recovered = fit.read_rows()
    assert set(recovered) == {("sample-a", "full", "default")}
    assert recovered[("sample-a", "full", "default")]["scores"]["choice"] == 0.73
    assert (tmp_path / "jev_raw.jsonl").read_text(encoding="utf-8") == raw


def test_confirmation_and_both_parameters_remain_frozen_and_disjoint():
    lock = json.loads((LAB / "confirmation_protocol.json").read_text())
    for file, key in [
        ("labels_confirmation.json", "labels_sha256"),
        ("heuristic.json", "primary_sha256"),
        ("heuristic_quality.json", "quality_sha256"),
    ]:
        assert hashlib.sha256((LAB / file).read_bytes()).hexdigest() == lock[key]
    old = json.loads((LAB / "labels.json").read_text())["samples"]
    fresh = json.loads((LAB / "labels_confirmation.json").read_text())["samples"]
    assert len(fresh) == len({s["pdf_sha256"] for s in fresh}) == 20
    assert sum(s["has_signature"] for s in fresh) == 10
    for field in ["group", "pdf_sha256", "document", "id"]:
        assert not {s[field] for s in old} & {s[field] for s in fresh}
    assert all(s["group"] != "lomza.bip.net.pl" for s in fresh)


def test_quality_calculator_matches_predefined_feature_and_requires_consensus(monkeypatch):
    monkeypatch.syspath_prepend(str(LAB))
    quality = importlib.import_module("calculator_quality")
    fit = importlib.import_module("fit_jev50")
    parameters = json.loads((LAB / "heuristic_quality.json").read_text())
    scores = {
        view: {
            "handwritten": 0.1,
            "initials": 0.1,
            "execution": 0.1,
            "pen_strokes": 0.1,
            "choice": 0.99,
            "absence": 0.8,
            "notes": 0.1,
            "empty": 0.5,
        }
        for view in [*quality.VIEWS, "bottom"]
    }
    # One confident binary answer without the other visual evidence is insufficient.
    decision = quality.calculate_quality(scores, parameters)
    assert not decision["has_signature"]
    scores["tr"].update(handwritten=0.9, execution=0.8, pen_strokes=0.85)
    rows = {("page", view, "default"): {"scores": s, "elapsed_s": 1} for view, s in scores.items()}
    decision = quality.calculate_quality(scores, parameters)
    assert decision["has_signature"]
    assert decision["score"] == fit.features(rows, "page")[0]["tiles5.max_mean"]
    for invalid in [None, True, "0.5", float("nan"), float("inf"), -0.1, 1.1]:
        scores["tr"]["choice"] = invalid
        with pytest.raises(ValueError):
            quality.calculate_quality(scores, parameters)


def test_production_protocol_and_calibration_match_the_frozen_experiment():
    from signum.ai import jev_signature
    from signum.ai.jev_prompts import JEV_PROMPT_INSTRUCTIONS

    protocol = json.loads((LAB / "protocol.json").read_text(encoding="utf-8"))
    parameters = json.loads((LAB / "heuristic_quality.json").read_text(encoding="utf-8"))
    assert protocol["questions"] == jev_signature.QUALITY_QUESTIONS
    assert protocol["states"]["default"] == JEV_PROMPT_INSTRUCTIONS
    assert parameters["threshold"] == jev_signature.THRESHOLD
    assert parameters["calibration"]["intercept"] == jev_signature.INTERCEPT
    assert parameters["calibration"]["slope"] == jev_signature.SLOPE
