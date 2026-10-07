"""Adres i klucz muszą trafić do faktycznie wybranego transportu."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from signum.ai import create_vision_model
from signum.ai.base import AIResponseError
from signum.ai.openai_client import OpenAIVisionModel
from signum.config import AppConfig


@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500, 502, 503])
def test_openai_preflight_odrzuca_bledy(status: int) -> None:
    model = OpenAIVisionModel("http://localhost:8000/v1", "", "test")
    model._session.get = Mock(return_value=Mock(status_code=status))
    with pytest.raises(AIResponseError, match=str(status)):
        model.check_connection()


@pytest.mark.parametrize("status", [404, 405])
def test_openai_proxy_bez_listy_modeli_ma_jawny_komunikat(status: int) -> None:
    model = OpenAIVisionModel("http://localhost:8000/v1", "", "test")
    model._session.get = Mock(return_value=Mock(status_code=status))
    assert "niepotwierdzona" in model.check_connection()


def test_claude_uzywa_wlasnego_adresu_i_natywnych_blokow_obrazu() -> None:
    model = create_vision_model(AppConfig(
        provider="anthropic", anthropic_base_url="https://claude.example.test/custom/v1",
        anthropic_model="custom-claude",
    ), api_key="test-key")
    post = Mock(return_value=Mock(status_code=200, json=Mock(return_value={
        "content": [{"type": "text", "text": '{"description":"Pismo","signatures":[]}'}],
    })))
    model._session.post = post
    assert model.analyze_page(b"jpeg").description == "Pismo"
    args, kwargs = post.call_args
    assert args == ("https://claude.example.test/custom/v1/messages",)
    assert kwargs["headers"]["x-api-key"] == "test-key"
    assert kwargs["allow_redirects"] is False
    assert kwargs["json"]["model"] == "custom-claude"
    assert kwargs["json"]["messages"][0]["content"][0]["type"] == "image"
    get = Mock(return_value=Mock(status_code=200))
    model._session.get = get
    model.check_connection()
    assert get.call_args.args == ("https://claude.example.test/custom/v1/models?limit=1",)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_lokalne_api_moze_dzialac_bez_klucza(provider: str) -> None:
    config = AppConfig(provider=provider)
    setattr(config, f"{provider}_base_url", "http://localhost:8000/v1")
    model = create_vision_model(config, api_key="")
    assert not config.requires_api_key
    assert not model._session.trust_env
    assert "Authorization" not in model._headers()
    assert "x-api-key" not in model._headers()
    model._session.get = Mock(return_value=Mock(status_code=200))
    assert model.check_connection()


def test_ollama_z_kluczem_uwierzytelnia_rowniez_liste_modeli(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    model = create_vision_model(AppConfig(), api_key="gateway-key")
    assert model._session.headers["Authorization"] == "Bearer gateway-key"
    model._session.get = Mock(return_value=Mock(
        status_code=200, json=Mock(return_value={"version": "test"}),
    ))
    list_models = Mock(return_value=["gemma4:12b"])
    monkeypatch.setattr("signum.ai.ollama_client.OllamaVisionModel.list_models", list_models)
    model.check_connection()
    assert list_models.call_args.kwargs["api_key"] == "gateway-key"
