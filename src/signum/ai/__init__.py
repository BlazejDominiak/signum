"""Warstwa modeli wizyjnych AI: Ollama (lokalnie) oraz API chmurowe."""

from __future__ import annotations

from typing import TYPE_CHECKING

from signum.ai.anthropic_client import AnthropicVisionModel
from signum.ai.base import AIConnectionError, AIError, AIResponseError, VisionModel
from signum.ai.jev_client import JevVisionModel
from signum.ai.ollama_client import OllamaVisionModel
from signum.ai.openai_client import OpenAIVisionModel
from signum.config import get_api_key

if TYPE_CHECKING:
    from signum.config import AppConfig

__all__ = [
    "AIConnectionError",
    "AIError",
    "AIResponseError",
    "AnthropicVisionModel",
    "JevVisionModel",
    "OllamaVisionModel",
    "OpenAIVisionModel",
    "VisionModel",
    "create_vision_model",
]


def create_vision_model(config: AppConfig, api_key: str | None = None) -> VisionModel:
    """Fabryka modelu wizyjnego na podstawie konfiguracji aplikacji.

    ``api_key`` przekazuje się wprost (np. z dialogu ustawień przed zapisem);
    domyślnie klucz jest pobierany z systemowego magazynu poświadczeń.
    """
    key = api_key if api_key is not None else (get_api_key(config.provider) or "")
    if config.provider == "ollama":
        return OllamaVisionModel(
            base_url=config.ollama_url,
            model=config.ollama_model,
            timeout_s=config.timeout_s,
            num_ctx=config.ollama_num_ctx,
            api_key=key,
            runtime_dir=config.ollama_runtime_dir,
            additional_analysis=config.ollama_additional_analysis,
        )
    if config.provider == "openai":
        return OpenAIVisionModel(
            base_url=config.openai_base_url,
            api_key=key,
            model=config.openai_model,
            timeout_s=config.timeout_s,
        )
    if config.provider == "anthropic":
        return AnthropicVisionModel(
            api_key=key,
            model=config.anthropic_model,
            timeout_s=config.timeout_s,
            base_url=config.anthropic_base_url,
        )
    if config.provider == "vjev":
        return JevVisionModel(
            base_url=config.api_base_url,
            api_key=key,
            model=getattr(config, f"{config.provider}_model"),
            timeout_s=config.timeout_s,
            runtime_dir=config.vjev_runtime_dir,
            additional_analysis=config.vjev_additional_analysis,
            hitl_margin=config.vjev_hitl_margin,
        )
    raise ValueError(f"Nieznany dostawca AI: {config.provider!r}")
