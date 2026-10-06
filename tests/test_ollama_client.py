"""Testy klienta Ollamy: retry ze structured outputs tylko przy złym JSON-ie.

Wymuszanie schematu gramatyką (``format``) obniża recall detekcji, więc
pierwsze zapytanie idzie bez niego; ``format`` służy wyłącznie jako siatka
bezpieczeństwa, gdy odpowiedź nie zawiera poprawnego obiektu JSON.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from signum.ai.base import AIResponseError
from signum.ai.ollama_client import OllamaVisionModel
from signum.ai.prompts import RESPONSE_SCHEMA

VALID_JSON = json.dumps(
    {
        "description": "Umowa",
        "signatures": [{"type": "handwritten", "confidence": 95, "box_2d": [724, 694, 775, 810]}],
    }
)


class _FakeResponse:
    def __init__(self, content: str, status_code: int = 200) -> None:
        self.status_code = status_code
        self.text = content
        self._content = content

    def json(self) -> dict[str, Any]:
        return {"message": {"content": self._content}}


class _FakePost:
    """Rejestruje kolejne payloady i zwraca zadane z góry odpowiedzi."""

    def __init__(self, *contents: str) -> None:
        self._contents = list(contents)
        self.payloads: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        json: dict[str, Any],
        timeout: int,
        allow_redirects: bool,
    ) -> _FakeResponse:
        assert allow_redirects is False
        self.payloads.append(json)
        return _FakeResponse(self._contents[len(self.payloads) - 1])


def _model() -> OllamaVisionModel:
    return OllamaVisionModel("http://localhost:11434", "gemma4:12b")


class TestGenerateRetry:
    def test_poprawny_json_bez_format_bez_ponowienia(self, monkeypatch: pytest.MonkeyPatch) -> None:
        post = _FakePost(VALID_JSON)
        model = _model()
        monkeypatch.setattr(model._session, "post", post)
        analysis = model.analyze_page(b"jpeg")
        assert len(post.payloads) == 1
        assert "format" not in post.payloads[0]
        assert post.payloads[0]["think"] is False
        assert analysis.signatures[0].confidence == 95

    def test_plotki_markdown_nie_wymuszaja_ponowienia(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        post = _FakePost(f"```json\n{VALID_JSON}\n```")
        model = _model()
        monkeypatch.setattr(model._session, "post", post)
        analysis = model.analyze_page(b"jpeg")
        assert len(post.payloads) == 1
        assert analysis.description == "Umowa"

    def test_zly_json_ponawia_ze_structured_outputs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        post = _FakePost("Przepraszam, nie mogę przeanalizować obrazu.", VALID_JSON)
        model = _model()
        monkeypatch.setattr(model._session, "post", post)
        analysis = model.analyze_page(b"jpeg")
        assert len(post.payloads) == 2
        assert "format" not in post.payloads[0]
        assert post.payloads[1]["format"] is RESPONSE_SCHEMA
        assert analysis.signatures[0].box_2d == (724, 694, 775, 810)

    def test_ponowienie_tez_zle_rzuca_blad_odpowiedzi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        post = _FakePost("nie-json", "nadal nie-json")
        model = _model()
        monkeypatch.setattr(model._session, "post", post)
        with pytest.raises(AIResponseError):
            model.analyze_page(b"jpeg")
        assert len(post.payloads) == 2


@pytest.mark.parametrize("content", ["", "{}", '{"description":"Umowa"}'])
def test_empty_or_incomplete_result_is_retried_not_unsigned(
    content: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model()
    post = _FakePost(content, VALID_JSON)
    monkeypatch.setattr(model._session, "post", post)
    assert model.analyze_page(b"jpeg").signatures
    assert len(post.payloads) == 2
    assert post.payloads[1]["format"] is RESPONSE_SCHEMA


def test_truncated_valid_json_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    class Truncated(_FakeResponse):
        def json(self) -> dict[str, Any]:
            return {"message": {"content": VALID_JSON}, "done_reason": "length"}

    model = _model()
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> _FakeResponse:
        calls.append(kwargs["json"])
        return Truncated(VALID_JSON) if len(calls) == 1 else _FakeResponse(VALID_JSON)

    monkeypatch.setattr(model._session, "post", post)
    assert model.analyze_page(b"jpeg").signatures
    assert len(calls) == 2
    assert calls[1]["options"]["num_predict"] > calls[0]["options"]["num_predict"]


def test_lokalna_ollama_nie_uzywa_proxy_z_otoczenia() -> None:
    assert _model()._session.trust_env is False
    assert OllamaVisionModel("https://ollama.example.test", "model")._session.trust_env is True
