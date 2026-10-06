"""Konfiguracja aplikacji.

Ustawienia zapisujemy jako JSON w katalogu konfiguracji użytkownika
(``%APPDATA%/Signum`` na Windows). Klucze API NIGDY nie trafiają do pliku —
przechowuje je systemowy magazyn poświadczeń (Windows Credential Manager)
poprzez bibliotekę ``keyring``.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import keyring
import keyring.errors
import platformdirs

from signum import APP_NAME

logger = logging.getLogger(__name__)

KEYRING_SERVICE = APP_NAME
PROVIDERS = ("ollama", "openai", "anthropic", "vjev")
MAX_MODEL_NAME_LENGTH = 200
MAX_CUSTOM_PROMPT_LENGTH = 20_000


def config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False, roaming=True))


def config_file() -> Path:
    return config_dir() / "settings.json"


@dataclass(slots=True)
class AppConfig:
    """Wszystkie trwałe ustawienia aplikacji (bez sekretów)."""

    provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:12b"
    ollama_num_ctx: int = 8192  # okno kontekstu (domyślne Ollamy to zaledwie 4096)
    ollama_runtime_dir: str = ""  # opcjonalna samodzielna Ollama z instalatora
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_model: str = "claude-sonnet-5"
    vjev_base_url: str = "http://localhost:8800/v1"
    vjev_model: str = "vjev-vision"
    vjev_runtime_dir: str = "H:/Tools/SignumJev"
    timeout_s: int = 300
    max_pages_per_doc: int = 10
    model_image_max_side: int = 1120
    custom_prompt: str = ""  # część merytoryczna promptu; pusta = domyślna
    jev_custom_prompt: str = ""  # instrukcje decyzji vjev
    recursive_folders: bool = True
    last_dir: str = ""

    @property
    def api_base_url(self) -> str:
        """Adres API aktualnie wybranego dostawcy."""
        if self.provider == "ollama":
            return self.ollama_url
        return str(getattr(self, f"{self.provider}_base_url"))

    @property
    def requires_api_key(self) -> bool:
        """Serwery on-prem mogą działać bez uwierzytelnienia."""
        from signum.network import is_loopback_endpoint  # noqa: PLC0415

        return self.provider in {"openai", "anthropic"} and not (
            is_loopback_endpoint(self.api_base_url)
        )

    @classmethod
    def load(cls) -> AppConfig:
        """Wczytuje ustawienia; przy braku/uszkodzeniu pliku zwraca domyślne."""
        path = config_file()
        try:
            raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Nie można wczytać %s (%s) — używam domyślnych", path, exc)
            return cls()
        defaults = cls()
        kwargs: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in raw:
                continue
            value = raw[field.name]
            default = getattr(defaults, field.name)
            # ``bool`` jest podklasą ``int``, dlatego typy sprawdzamy dokładnie.
            if type(value) is type(default):
                kwargs[field.name] = value
        config = cls(**kwargs)
        if config.vjev_model == "yah01/vjev-vision":
            config.vjev_model = defaults.vjev_model
        if config.provider not in PROVIDERS:
            config.provider = "ollama"
        config.ollama_num_ctx = min(max(config.ollama_num_ctx, 2048), 262_144)
        config.timeout_s = min(max(config.timeout_s, 30), 3600)
        config.max_pages_per_doc = min(max(config.max_pages_per_doc, 1), 500)
        if config.model_image_max_side not in {768, 1024, 1120, 1400, 1600, 2048}:
            config.model_image_max_side = defaults.model_image_max_side
        for provider in PROVIDERS:
            name = f"{provider}_model"
            value = getattr(config, name).strip() or getattr(defaults, name)
            setattr(config, name, value[:MAX_MODEL_NAME_LENGTH])
        config.custom_prompt = config.custom_prompt[:MAX_CUSTOM_PROMPT_LENGTH]
        config.jev_custom_prompt = config.jev_custom_prompt[:MAX_CUSTOM_PROMPT_LENGTH]
        config.last_dir = config.last_dir[:32_767]
        return config

    def save(self) -> None:
        path = config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(path)


def get_api_key(provider: str) -> str | None:
    """Pobiera klucz API z systemowego magazynu poświadczeń."""
    try:
        return keyring.get_password(KEYRING_SERVICE, f"{provider}_api_key")
    except keyring.errors.KeyringError as exc:
        logger.warning("Magazyn poświadczeń niedostępny: %s", exc)
        return None


def set_api_key(provider: str, key: str) -> None:
    """Zapisuje (lub usuwa, gdy pusty) klucz API w magazynie poświadczeń."""
    entry = f"{provider}_api_key"
    try:
        if key:
            keyring.set_password(KEYRING_SERVICE, entry, key)
        else:
            # Brak klucza do usunięcia nie jest błędem.
            with contextlib.suppress(keyring.errors.PasswordDeleteError):
                keyring.delete_password(KEYRING_SERVICE, entry)
    except keyring.errors.KeyringError as exc:
        logger.warning("Nie można zapisać klucza w magazynie poświadczeń: %s", exc)
        raise
