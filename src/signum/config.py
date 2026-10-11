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
import math
from dataclasses import asdict, dataclass, fields
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any

import keyring
import keyring.errors
import platformdirs

from signum import APP_NAME
from signum.i18n import tr

logger = logging.getLogger(__name__)

KEYRING_SERVICE = APP_NAME
PROVIDERS = ("ollama", "openai", "anthropic", "vjev")
MAX_MODEL_NAME_LENGTH = 200
MAX_CUSTOM_PROMPT_LENGTH = 20_000


def config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False, roaming=True))


def config_file() -> Path:
    return config_dir() / "settings.json"


def default_ai_directory() -> Path:
    # Prefer the large data drive when present; no drive letter is required.
    if Path("H:/").is_dir():
        return Path("H:/Tools/SignumAI")
    return Path(platformdirs.user_documents_dir()) / "SignumAI"


def default_cache_directory() -> str:
    return str(default_ai_directory() / "cache" / "classification")


@dataclass(slots=True)
class AppConfig:
    """Wszystkie trwałe ustawienia aplikacji (bez sekretów)."""

    language: str = "pl"
    provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:12b"
    ollama_num_ctx: int = 8192  # okno kontekstu (domyślne Ollamy to zaledwie 4096)
    ollama_runtime_dir: str = ""  # opcjonalna samodzielna Ollama z instalatora
    ollama_additional_analysis: bool = True  # dotychczasowy opis i wycinki
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_model: str = "claude-sonnet-5"
    vjev_base_url: str = "http://localhost:8800/v1"
    vjev_model: str = "vjev-vision"
    ollama_models_directory: str = ""
    ai_directory: str = dataclass_field(default_factory=lambda: str(default_ai_directory()))
    vjev_runtime_dir: str = ""
    vjev_additional_analysis: bool = False  # eksperymentalne kategorie i lokalizacja
    timeout_s: int = 300
    max_pages_per_doc: int = 10
    model_image_max_side: int = 1120
    custom_prompt: str = ""  # część merytoryczna promptu; pusta = domyślna
    jev_custom_prompt: str = ""  # instrukcje decyzji vjev
    recursive_folders: bool = True
    last_dir: str = ""
    classification_provider: str = "gemma"  # legacy selection
    classification_selection: str = "selected"
    classification_models: str = ""  # JSON profiles; API keys stay in keyring
    classification_categories: str = ""  # JSON names + descriptions; empty uses examples
    vjev_hitl_margin: float = 0.10
    vjev_threshold: float = 0.535
    vjev_stamp_threshold: float = 0.5
    vjev_category_threshold: float = 0.6
    vjev_candidate_threshold: float = 0.5
    vjev_verify_threshold: float = 0.65
    vjev_single_threshold: float = 0.5
    ollama_threshold: float = 0.5  # presence-only mode
    ollama_stamp_threshold: float = 0.5
    ollama_full_threshold: float = 0.0  # retain all generated findings by default
    ollama_hitl_margin: float = 0.0
    openai_threshold: float = 0.0
    openai_hitl_margin: float = 0.0
    anthropic_threshold: float = 0.0
    anthropic_hitl_margin: float = 0.0
    classification_prompt: str = ""
    classification_ollama_url: str = "http://localhost:11434"
    classification_ollama_model: str = "gemma4:12b"
    classification_env_file: str = ""
    classification_jev_python: str = ""
    classification_jev_model_dir: str = ""
    classification_jev_runtime: str = ""
    classification_jev_packages: str = ""
    classification_cache_dir: str = dataclass_field(default_factory=default_cache_directory)

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
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            logger.warning("Nie można wczytać %s (%s) — używam domyślnych", path, exc)
            return cls()
        if not isinstance(raw, dict):
            logger.warning("Konfiguracja %s nie jest obiektem JSON — używam domyślnych", path)
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
        if config.language not in {"pl", "en"}:
            config.language = defaults.language
        for name in (f.name for f in fields(cls) if isinstance(getattr(defaults, f.name), float)):
            value = raw.get(name, getattr(defaults, name))
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                value = getattr(defaults, name)
            setattr(config, name, float(value))
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
        if config.classification_provider not in {"venice", "jevk5", "gemma", "all"}:
            config.classification_provider = defaults.classification_provider
        config.classification_prompt = config.classification_prompt[:4000]
        config.classification_categories = config.classification_categories[:20000]
        # Migrate stale machine-specific defaults; preserve real existing installs.
        for name in (
            "vjev_runtime_dir",
            "classification_env_file",
            "classification_jev_python",
            "classification_jev_model_dir",
            "classification_jev_runtime",
            "classification_jev_packages",
            "classification_cache_dir",
            "ai_directory",
            "ollama_models_directory",
        ):
            value = getattr(config, name)
            if (value and not Path(value).anchor) or (
                value and Path(value).anchor and not Path(Path(value).anchor).exists()
            ):
                setattr(config, name, getattr(defaults, name))
        return config

    def save(self) -> None:
        path = config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(path)


def signature_settings(config: AppConfig) -> str:
    """Snapshot of the effective settings used by one signature run."""
    additional = getattr(config, config.provider + "_additional_analysis", True)
    threshold_name = (
        "ollama_full_threshold"
        if config.provider == "ollama" and additional
        else config.provider + "_threshold"
    )
    values = [
        (tr("core.config.decision_threshold"), getattr(config, threshold_name)),
        ("HITL ±", getattr(config, config.provider + "_hitl_margin")),
    ]
    if config.provider == "vjev" or (config.provider == "ollama" and not additional):
        values.append(
            (
                tr("core.config.stamp_threshold"),
                getattr(config, config.provider + "_stamp_threshold"),
            )
        )
    if config.provider == "vjev" and additional:
        values.extend(
            (label, getattr(config, name))
            for label, name in (
                (tr("core.config.category_threshold"), "vjev_category_threshold"),
                (tr("core.config.region_threshold"), "vjev_candidate_threshold"),
                (tr("core.config.verification_threshold"), "vjev_verify_threshold"),
                (tr("core.config.single_signature_threshold"), "vjev_single_threshold"),
            )
        )
    return tr(
        "core.config.page_limit_image_size_additional_analysis",
        value0=config.max_pages_per_doc,
        value1=1120 if config.provider == "vjev" else config.model_image_max_side,
        value2=tr("core.yes") if additional else tr("core.no"),
    ) + "; ".join(f"{label}: {value:.3f}" for label, value in values)


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
