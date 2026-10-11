"""Application text catalogs, independent of Qt and safe for worker threads.

Keys are stable identifiers; each entry contains Polish and English text.
Named placeholders allow translators to reorder sentences. The language is
selected at startup and remains fixed until the next application launch.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

SUPPORTED_LANGUAGES = ("pl", "en")
_language = "pl"


def set_language(language: str) -> None:
    global _language  # noqa: PLW0603 -- one process-wide locale, fixed after startup
    _language = language if language in SUPPORTED_LANGUAGES else "pl"


def get_language() -> str:
    return _language


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    directory = resources.files("signum") / "locales"
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.name.endswith(".json"):
            part = json.loads(path.read_text(encoding="utf-8"))
            if entries.keys() & part.keys():
                raise ValueError(f"Duplicate translation key in {path.name}")
            entries.update(part)
    return entries


def tr(key: str, **values: object) -> str:
    """Resolve a catalog key at use time, then substitute named values.

    Unknown keys fail explicitly so missing translations cannot ship unnoticed.
    Literal braces (for example JSON in prompts) are preserved without values.
    """
    translations = catalog()[key]
    text = translations.get(_language, translations["pl"])
    return text.format(**values) if values else text


def translate_error(text: str) -> str:
    """Resolve standalone runtime error codes; preserve external diagnostics verbatim."""
    return tr(text) if text.startswith("runtime.") and text in catalog() else text
