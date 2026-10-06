"""Kontrakt obrazów i decyzji Jev; bez serwera, klucza i pobierania wag."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from PIL import Image

from signum.ai import create_vision_model
from signum.ai.base import AIConnectionError, AIResponseError
from signum.ai.jev_client import JevVisionModel
from signum.ai.jev_prompts import JEV_PROMPT_INSTRUCTIONS
from signum.ai.jev_signature import QUALITY_QUESTIONS, parse_signature_views
from signum.ai.prompts import PROMPT_FORMAT, build_page_prompt
from signum.config import AppConfig
from signum.core.models import DocumentResult, DocumentStatus, SignatureFinding, SignatureKind
from signum.core.pipeline import CancelToken, DocumentAnalyzer


def _answer(handwritten: float = 0.9, initials: float = 0.2, stamp: float = 0.8) -> dict:
    return {
        "answers": {
            "handwritten": {"type": "noul", "noul": handwritten},
            "initials": {"type": "noul", "noul": initials},
            "stamp": {"type": "noul", "noul": stamp},
            "document_type": {"type": "choice", "choice": "contract"},
        }
    }


def _response(body: object, status: int = 200) -> Mock:
    return Mock(status_code=status, json=Mock(return_value=body))


def _quality_answer(score: float = 0.9, stamp: float = 0.8) -> dict:
    answers = {
        key: {"type": "noul", "noul": stamp if key == "stamp" else score}
        for key in QUALITY_QUESTIONS
        if key != "binary"
    }
    answers["initials"]["noul"] = 0.1
    answers["binary"] = {
        "type": "choice",
        "choice": "present" if score >= 0.5 else "absent",
        "probabilities": {"present": score, "absent": 1 - score},
    }
    return {"answers": answers}


@pytest.mark.parametrize("provider", ["vjev"])
def test_obraz_i_niezalezne_decyzje_w_kontrakcie_dostawcy(provider: str) -> None:
    config = AppConfig(provider=provider)
    model = create_vision_model(config, api_key="test-key")
    assert isinstance(model, JevVisionModel)
    request = Mock(return_value=_response(_answer()))
    model._session.request = request

    result = model.analyze_page(b"test-jpeg", "Custom instructions")

    assert result.description == "Umowa"
    assert [(sig.kind, sig.confidence, sig.box_2d) for sig in result.signatures] == [
        (SignatureKind.HANDWRITTEN, 90, None),
        (SignatureKind.STAMP, 80, None),
    ]
    args, kwargs = request.call_args
    assert args == ("POST", f"{config.api_base_url}/systemone")
    assert kwargs["allow_redirects"] is False
    payload = kwargs["json"]
    assert "temperature" not in payload and "max_tokens" not in payload
    assert payload["model"] == getattr(config, f"{provider}_model")
    assert all(
        payload["questions"][kind]["type"] == "noul"
        for kind in ("handwritten", "initials", "stamp")
    )
    blocks = payload["state"]
    encoded = blocks[1]["source"]["data"]
    assert "messages" not in payload
    assert not model._session.trust_env
    assert blocks[0]["text"] == "Custom instructions"
    assert base64.b64decode(encoded) == b"test-jpeg"
    assert model._session.headers["Authorization"] == "Bearer test-key"


@pytest.mark.parametrize("bad", [None, True, "0.9", -0.1, 1.1, float("nan"), float("inf")])
def test_bledna_ocena_nie_jest_brakiem_podpisu(bad: object) -> None:
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    data = _answer()
    data["answers"]["handwritten"]["noul"] = bad
    model._session.request = Mock(return_value=_response(data))
    with pytest.raises(AIResponseError):
        model.analyze_page(b"jpeg")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"answers": []},
        {"answers": {}},
        {"answers": {"handwritten": {"type": "noul", "noul": 0.9}}},
    ],
)
def test_niepelna_odpowiedz_to_blad(body: dict) -> None:
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    model._session.request = Mock(return_value=_response(body))
    with pytest.raises(AIResponseError):
        model.analyze_page(b"jpeg")


def test_negatywne_decyzje_i_prog() -> None:
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    model._session.request = Mock(
        side_effect=[
            _response(_answer(0.49, 0.1, 0.01)),
            _response(_answer(0.5, 0.1, 0.01)),
        ]
    )
    assert not model.analyze_page(b"jpeg").signatures
    assert model.analyze_page(b"jpeg").signatures[0].confidence == 50


def test_test_polaczenia_sprawdza_obraz_i_model() -> None:
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    request = Mock(
        side_effect=[
            _response({"models": [{"id": "vjev-vision", "vision": True}]}),
            _response(_answer()),
        ]
    )
    model._session.request = request
    assert "test obrazu" in model.check_connection()
    assert request.call_count == 2
    payload = request.call_args.kwargs["json"]
    image = base64.b64decode(payload["state"][1]["source"]["data"])
    assert Image.open(io.BytesIO(image)).size == (64, 64)


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "other-model", "vision": True},
        {"id": "vjev-vision", "vision": False},
        {"id": "vjev-vision", "vision": True, "stub": True},
    ],
)
def test_nieakceptuje_innego_modelu_tekstowego_ani_stub(entry: dict) -> None:
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    request = Mock(return_value=_response({"models": [entry]}))
    model._session.request = request
    with pytest.raises(AIResponseError):
        model.check_connection()
    assert request.call_count == 1


@pytest.mark.parametrize("status", [401, 403, 422, 429, 500, 302])
def test_bledy_http(status: int) -> None:
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    model._session.request = Mock(return_value=_response({}, status))
    with pytest.raises(AIResponseError, match=str(status)):
        model.analyze_page(b"jpeg")


def test_utrata_polaczenia_przerywa_partie() -> None:
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    model._session.request = Mock(side_effect=requests.exceptions.ConnectionError("offline"))
    with pytest.raises(AIConnectionError):
        model.analyze_page(b"jpeg")


def test_prompt_decyzyjny_nie_zawiera_schematu_llm() -> None:
    assert build_page_prompt("LLM custom", "vjev", "Jev custom") == "Jev custom"
    assert build_page_prompt("LLM custom", "vjev") == JEV_PROMPT_INSTRUCTIONS
    assert PROMPT_FORMAT in build_page_prompt("LLM custom", "anthropic")


def test_decyzje_lacza_sie_z_podpisami_cyfrowymi(
    tmp_path: Path,
    signed_pdf_bytes: bytes,
) -> None:
    path = tmp_path / "signed.pdf"
    path.write_bytes(signed_pdf_bytes)
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    model._session.request = Mock(return_value=_response(_quality_answer()))
    analyzer = DocumentAnalyzer(model, max_pages=1, image_max_side=768)

    result = analyzer.analyze(path, CancelToken())

    assert result.status == DocumentStatus.OK
    assert result.pages_analyzed == 1
    assert {finding.kind for finding in result.findings} == {
        SignatureKind.HANDWRITTEN,
        SignatureKind.STAMP,
        SignatureKind.DIGITAL,
    }
    visual = [finding for finding in result.findings if finding.kind != SignatureKind.DIGITAL]
    assert all(finding.crop_png is None for finding in visual)
    assert result.page_signature_probabilities[1] > 0.99


def test_quality_negative_retains_probability_and_stamp_is_not_a_signature() -> None:
    analysis = parse_signature_views([_quality_answer(0.1)] * 5)
    result = DocumentResult(
        path=Path("stamp.pdf"),
        findings=[SignatureFinding(sig.kind, 1, sig.confidence) for sig in analysis.signatures],
    )
    assert not result.is_signed
    assert analysis.signature_probability is not None and analysis.signature_probability < 0.01


def test_quality_requires_all_views_and_rejects_invalid_scores() -> None:
    with pytest.raises(AIResponseError):
        parse_signature_views([_quality_answer()] * 4)
    for invalid in [None, True, float("nan"), float("inf"), -0.1, 1.1]:
        row = _quality_answer()
        row["answers"]["binary"]["probabilities"]["present"] = invalid
        with pytest.raises(AIResponseError):
            parse_signature_views([row] * 5)


def test_quality_pipeline_can_cancel_between_views(tmp_path: Path) -> None:
    path = tmp_path / "scan.jpg"
    Image.new("RGB", (400, 500), "white").save(path)
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    cancel = CancelToken()

    def answer(*args, **kwargs):
        cancel.cancel()
        return _response(_quality_answer())

    model._session.request = Mock(side_effect=answer)
    from signum.core.pipeline import BatchCancelledError

    with pytest.raises(BatchCancelledError):
        DocumentAnalyzer(model, 1, 1120).analyze(path, cancel)
    assert model._session.request.call_count == 1
