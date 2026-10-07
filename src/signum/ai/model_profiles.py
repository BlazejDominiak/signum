"""User-defined model configurations for document classification."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from signum.config import AppConfig
from signum.network import is_loopback_endpoint, normalize_ai_endpoint

API_FORMATS = {
    "openai": "Chat Completions (OpenAI-compatible)",
    "anthropic": "Messages (Anthropic)",
    "decisions": "Decisions (Jev / Venice)",
}


@dataclass
class ModelProfile:
    id: str
    name: str = ""
    provider: str = "ollama"
    url: str = "http://localhost:11434"
    model: str = ""
    enabled: bool = True
    api_format: str = "openai"
    key_slot: str = ""
    python: str = ""
    model_dir: str = ""
    runtime: str = ""
    packages: str = ""

    @property
    def label(self) -> str:
        return self.name.strip() or self.model or Path(self.model_dir).name or "Nowy model"

    @property
    def local(self) -> bool:
        if self.provider == "jevk5":
            return True
        return is_loopback_endpoint(self.url) and not (
            self.provider == "ollama" and self.model.lower().endswith("cloud")
        )

    @property
    def credential_slot(self) -> str:
        return self.key_slot or f"classification-{self.id}"

    def validate(self) -> None:
        if not self.id or self.provider not in {"ollama", "api", "jevk5"}:
            raise ValueError("Wybierz rodzaj połączenia.")
        if self.provider == "jevk5":
            if not all((self.python, self.model_dir, self.runtime, self.packages)):
                raise ValueError("Przygotuj JevK5: Składniki AI → JevK5 → Instaluj / napraw.")
            return
        if not self.model.strip():
            raise ValueError("Wpisz nazwę modelu.")
        if not self.url.strip():
            raise ValueError("Wpisz adres API.")
        self.url = normalize_ai_endpoint(self.url, "", "AI")
        if self.api_format not in API_FORMATS:
            raise ValueError("Wybierz format API.")


def load_profiles(config: AppConfig) -> list[ModelProfile]:
    if config.classification_models:
        try:
            raw = json.loads(config.classification_models)
            if not isinstance(raw, list):
                raise ValueError("Nieprawidłowa lista modeli.")
            result = []
            allowed = {f.name for f in fields(ModelProfile)}
            for item in raw:
                if not isinstance(item, dict):
                    raise ValueError("Nieprawidłowa konfiguracja modelu.")
                profile = ModelProfile(**{k: v for k, v in item.items() if k in allowed})
                if any(
                    type(getattr(profile, f.name)) is not (bool if f.name == "enabled" else str)
                    for f in fields(ModelProfile)
                ):
                    raise ValueError("Nieprawidłowe pola konfiguracji modelu.")
                profile.validate()
                result.append(profile)
            if len({p.id for p in result}) != len(result):
                raise ValueError("Powtórzone identyfikatory modeli.")
            return result
        except (ValueError, TypeError, KeyError):
            # Never silently enable a remote service from a damaged profile list.
            return []

    # One-time migration of the old choice; new installations start with Ollama only.
    legacy = config.classification_provider
    choices = ["venice", "jevk5", "gemma"] if legacy == "all" else [legacy]
    profiles = []
    for choice in choices:
        if choice == "venice":
            profiles.append(
                ModelProfile(
                    id="venice",
                    provider="api",
                    url="https://api.venice.ai/api/v1",
                    model="jev-latest",
                    api_format="decisions",
                    key_slot="venice",
                )
            )
        elif choice == "jevk5":
            profiles.append(
                ModelProfile(
                    id="jevk5",
                    provider="jevk5",
                    name="JevK5",
                    python=config.classification_jev_python,
                    model_dir=config.classification_jev_model_dir,
                    runtime=config.classification_jev_runtime,
                    packages=config.classification_jev_packages,
                )
            )
        else:
            profiles.append(
                ModelProfile(
                    id="gemma",
                    url=config.classification_ollama_url,
                    model=config.classification_ollama_model,
                    key_slot="ollama",
                )
            )
    return profiles


def dump_profiles(profiles: list[ModelProfile]) -> str:
    return json.dumps([asdict(profile) for profile in profiles], ensure_ascii=False)
