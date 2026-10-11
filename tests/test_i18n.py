"""Localization contracts and saved-language integration, without model requests."""

from __future__ import annotations

import ast
import io
import json
import threading
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from string import Formatter
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QDialog

from signum.ai.text_classifiers import JevK5TextClassifier
from signum.config import AppConfig
from signum.core.models import DocumentResult, DocumentStatus
from signum.core.pipeline import BatchResult
from signum.i18n import catalog, get_language, set_language, tr, translate_error
from signum.local_components import probe_runtime
from signum.report.export import build_html
from signum.ui.main_window import MainWindow
from signum.ui.settings_dialog import SettingsDialog


@pytest.fixture(autouse=True)
def reset_language() -> Iterator[None]:
    set_language("pl")
    try:
        yield
    finally:
        set_language("pl")


def test_catalogs_have_both_languages_and_matching_placeholders() -> None:
    formatter = Formatter()
    entries = catalog()
    assert entries
    for key, translations in entries.items():
        assert set(translations) == {"pl", "en"}, key
        assert all(isinstance(text, str) and text.strip() for text in translations.values()), key
        fields = []
        for language in ("pl", "en"):
            fields.append(
                Counter(
                    (name, spec, conversion)
                    for _, name, spec, conversion in formatter.parse(translations[language])
                    if name is not None
                )
            )
        assert fields[0] == fields[1], key


def test_every_literal_translation_key_exists() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "signum"
    entries = catalog()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                assert node.args[0].value in entries, f"{path}:{node.lineno}"


@pytest.mark.parametrize("language", ["pl", "en"])
def test_language_persists(language: str) -> None:
    AppConfig(language=language).save()
    assert AppConfig.load().language == language


def test_unknown_saved_language_falls_back_to_polish(isolated_config: Path) -> None:
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(json.dumps({"language": "unknown"}), encoding="utf-8")
    assert AppConfig.load().language == "pl"
    set_language("unknown")
    assert get_language() == "pl"


@pytest.mark.parametrize(
    "language,tab,action",
    [
        ("pl", "Sprawdzanie podpisów", "Dodaj pliki…"),
        ("en", "Signature detection", "Add files…"),
    ],
)
def test_main_window_uses_saved_language(qtbot, language: str, tab: str, action: str) -> None:
    AppConfig(language=language).save()
    window = MainWindow()
    qtbot.addWidget(window)
    assert get_language() == language
    assert window.mode_tabs.tabText(0) == tab
    assert window.act_add_files.text() == action


def test_top_bar_saves_language_for_next_launch(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    for tab in (0, 1):
        window.mode_tabs.setCurrentIndex(tab)
        assert window.language_combo.isVisible()
        assert window.mode_tabs.cornerWidget().isAncestorOf(window.language_combo)
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    assert AppConfig.load().language == "en"
    assert get_language() == "pl"
    monkeypatch.setattr("signum.ui.settings_dialog.get_api_key", lambda provider: "")
    monkeypatch.setattr("signum.ui.settings_dialog.set_api_key", lambda provider, key: None)
    dialog = SettingsDialog(window._config)
    qtbot.addWidget(dialog)
    assert not hasattr(dialog, "language_combo")
    dialog._on_save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert AppConfig.load().language == "en"
    assert get_language() == "pl"
    assert dialog.windowTitle() == tr("settings.title")


def test_english_signature_report_preserves_user_content() -> None:
    set_language("en")
    result = DocumentResult(
        Path("zażółć.pdf"),
        status=DocumentStatus.OK,
        title="Umowa źródłowa",
        page_count=2,
        pages_analyzed=1,
    )
    report = build_html(BatchResult(results=[result]))
    assert "lang='en'" in report
    assert "signature analysis report" in report
    assert "analyzed 1/2 pages" in report
    assert "Umowa źródłowa" in report
    assert "zażółć.pdf" in report


@pytest.mark.parametrize(
    "language,expected",
    [
        ("pl", "CUDA niedostępna"),
        ("en", "CUDA unavailable"),
    ],
)
def test_runtime_probe_translates_external_error_code(
    language: str,
    expected: str,
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_language(language)
    python = tmp_path / "python.exe"
    python.touch()
    process = Mock(returncode=1)
    process.communicate.return_value = (
        json.dumps({"ok": False, "message": "runtime.cuda_unavailable"}),
        "",
    )
    process.poll.return_value = 1
    monkeypatch.setattr("signum.local_components.subprocess.Popen", Mock(return_value=process))
    with pytest.raises(ValueError, match=expected):
        probe_runtime("jevk5", str(python), "packages", "model", "runtime", tmp_path / "cache")


@pytest.mark.parametrize(
    "language,expected",
    [
        ("pl", "Skróć prompt"),
        ("en", "Shorten the prompt"),
    ],
)
def test_text_worker_translates_error_code(language: str, expected: str, monkeypatch) -> None:
    set_language(language)
    client = JevK5TextClassifier(AppConfig(), threading.Event())
    client.process = Mock(stdin=io.StringIO())
    client.replies.put(json.dumps({"ok": False, "error": "runtime.prompt_too_long"}))
    monkeypatch.setattr(client, "_start", lambda: None)
    with pytest.raises(ValueError, match=expected):
        client._request("prepare", "document", {})


def test_external_diagnostic_text_is_not_translated() -> None:
    set_language("en")
    assert translate_error("runtime.unknown_error") == "runtime.unknown_error"
    assert (
        translate_error("CUDA error 999: device unavailable")
        == "CUDA error 999: device unavailable"
    )
