"""Wspólne fixtures: dokumenty testowe generowane w locie (bez binariów w repo)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests import docfactory

# Testy GUI muszą działać headless (CI).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def signed_pdf_bytes() -> bytes:
    return docfactory.make_digitally_signed_pdf()


@pytest.fixture(scope="session")
def pades_pdf_bytes() -> bytes:
    return docfactory.make_digitally_signed_pdf(pades=True)


@pytest.fixture(scope="session")
def invisible_signed_pdf_bytes() -> bytes:
    return docfactory.make_digitally_signed_pdf(visible=False)


@pytest.fixture(scope="session")
def empty_field_pdf_bytes() -> bytes:
    return docfactory.make_pdf_with_empty_sig_field()


@pytest.fixture(scope="session")
def text_pdf_bytes() -> bytes:
    return docfactory.make_text_pdf()


@pytest.fixture()
def docs_dir(
    tmp_path: Path,
    signed_pdf_bytes: bytes,
    text_pdf_bytes: bytes,
) -> Path:
    """Katalog z mieszanką dokumentów (PDF + obrazy + plik nieobsługiwany)."""
    (tmp_path / "aneks_podpisany.pdf").write_bytes(signed_pdf_bytes)
    (tmp_path / "faktura.pdf").write_bytes(text_pdf_bytes)
    docfactory.make_signed_scan().save(tmp_path / "skan_protokol.png")
    docfactory.make_clean_scan().save(tmp_path / "skan_regulamin.jpg")
    (tmp_path / "notatka.txt").write_text("to nie dokument", encoding="utf-8")
    sub = tmp_path / "podfolder"
    sub.mkdir()
    docfactory.make_clean_scan().save(sub / "zalacznik.png")
    return tmp_path


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Przekierowuje plik konfiguracji do katalogu tymczasowego."""
    import signum.config as config_module

    target = tmp_path / "config" / "settings.json"
    monkeypatch.setattr(config_module, "config_file", lambda: target)
    monkeypatch.setattr(config_module, "config_dir", lambda: target.parent)
    return target
