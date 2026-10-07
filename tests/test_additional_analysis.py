"""Extra analysis must not change the frozen presence decision or invent locations."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from PIL import Image

from signum.ai.base import AIResponseError, PageAnalysis, VisualSignature
from signum.ai.basic_analysis import parse_basic_analysis
from signum.ai.jev_additional import CATEGORIES, connected_cells, enrich_analysis, grid_boxes
from signum.ai.ollama_client import OllamaVisionModel
from signum.core.models import SignatureKind


def nouls(values):
    return {"answers": {key: {"type": "noul", "noul": value} for key, value in values.items()}}


def test_grid_has_exact_coverage_and_does_not_wrap_rows():
    boxes = grid_boxes(403, 507)
    assert len(boxes) == 20
    assert sum((right - left) * (bottom - top) for left, top, right, bottom in boxes) == 403 * 507
    assert boxes[-1][2:] == (403, 507)
    assert connected_cells({3, 4}) == [[3], [4]]
    assert connected_cells({5, 6, 9, 10}) == [[5, 6, 9, 10]]


@pytest.mark.parametrize("verified", [0.1, 0.95])
def test_four_corner_fragments_fuse_and_verification_preserves_basic(verified):
    original = VisualSignature(SignatureKind.HANDWRITTEN, 97, None)
    basic = PageAnalysis("", (original,), 0.973)
    values = dict.fromkeys(CATEGORIES, 0.01)
    values.update(contract=0.99, medical=0.93)
    calls = [nouls(values)]
    for cell in range(20):
        calls.append(nouls({"fragment": 0.9 if cell in {5, 6, 9, 10} else 0.01, "stamp": 0.01}))
    calls.append(nouls({"signature": verified, "single_signature": 0.98, "stamp": 0.01}))
    if verified < 0.5:
        calls.append(calls[-1])
    decide = Mock(side_effect=calls)
    result = enrich_analysis(Image.new("RGB", (400, 500)), basic, decide)
    assert result.description == "Umowa; Dokumentacja medyczna"
    assert result.signature_probability == basic.signature_probability
    assert len(result.signatures) == 1
    assert result.signatures[0].kind == original.kind
    assert decide.call_count == (22 if verified > 0.5 else 23)
    if verified > 0.5:
        assert result.signatures[0].confidence == round(verified * 100)
        assert result.signatures[0].box_2d == (150, 187, 650, 813)
    else:
        assert result.signatures == basic.signatures


def test_negative_basic_never_triggers_grid_or_becomes_signed():
    decide = Mock(return_value=nouls(dict.fromkeys(CATEGORIES, 0.1)))
    basic = PageAnalysis("", (), 0.03)
    result = enrich_analysis(Image.new("RGB", (400, 500)), basic, decide)
    assert result.signatures == ()
    assert result.signature_probability == 0.03
    assert result.description == "Rodzaj nierozpoznany"
    assert decide.call_count == 1


def test_tight_support_can_verify_mark_while_preview_keeps_wide_context():
    basic = PageAnalysis("", (VisualSignature(SignatureKind.HANDWRITTEN, 97, None),), 0.97)
    calls = [nouls(dict.fromkeys(CATEGORIES, 0.1))]
    calls.extend(nouls({"fragment": 0.9 if i == 5 else 0.01, "stamp": 0.01}) for i in range(20))
    calls.extend(
        [
            nouls({"signature": 0.2, "single_signature": 0.2, "stamp": 0.01}),
            nouls({"signature": 0.9, "single_signature": 0.9, "stamp": 0.01}),
        ]
    )
    result = enrich_analysis(Image.new("RGB", (400, 500)), basic, Mock(side_effect=calls))
    assert result.signatures[0].box_2d == (150, 187, 450, 563)
    assert result.signatures[0].confidence == 90
    assert result.signature_probability == basic.signature_probability


def test_cancellation_stops_before_next_grid_request():
    decide = Mock(return_value=nouls(dict.fromkeys(CATEGORIES, 0.1)))
    check = Mock(side_effect=[None, RuntimeError("cancelled")])
    basic = PageAnalysis("", (VisualSignature(SignatureKind.HANDWRITTEN, 95, None),), 0.95)
    with pytest.raises(RuntimeError, match="cancelled"):
        enrich_analysis(Image.new("RGB", (400, 500)), basic, decide, check)
    assert decide.call_count == 1


@pytest.mark.parametrize("bad", [True, None, "0.9", -0.1, 1.1, float("nan")])
def test_malformed_basic_result_is_error_not_absence(bad):
    with pytest.raises(AIResponseError):
        parse_basic_analysis(json.dumps({"signature_probability": bad, "stamp_probability": 0.1}))


def test_ollama_basic_omits_description_boxes_and_full_custom_prompt():
    model = OllamaVisionModel("http://localhost:11434", "gemma4:12b", additional_analysis=False)
    post = Mock(
        return_value=Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "message": {"content": '{"signature_probability":0.1,"stamp_probability":0.9}'},
                    "eval_count": 15,
                    "prompt_eval_duration": 123,
                    "done_reason": "stop",
                }
            ),
        )
    )
    model._session.post = post
    result = model.analyze_page(b"jpeg", "CUSTOM FULL ANALYSIS WITH COORDINATES")
    payload = post.call_args.kwargs["json"]
    assert "CUSTOM" not in payload["messages"][0]["content"]
    assert payload["think"] is False
    assert set(payload["format"]["properties"]) == {"signature_probability", "stamp_probability"}
    assert result.description == ""
    assert result.signature_probability == 0.1
    assert [s.kind for s in result.signatures] == [SignatureKind.STAMP]
    assert result.signatures[0].box_2d is None
    assert model.last_metrics[0]["eval_count"] == 15
