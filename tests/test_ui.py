"""Testy dymne GUI (pytest-qt, platforma offscreen)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from signum.core.models import DocumentResult, DocumentStatus, SignatureFinding, SignatureKind
from signum.ui.main_window import BatchRiskDialog, MainWindow
from signum.ui.settings_dialog import OnlineWarningDialog, SettingsDialog

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def window(qtbot, isolated_config):  # type: ignore[no-untyped-def]
    win = MainWindow()
    qtbot.addWidget(win)
    return win


class TestMainWindow:
    def test_ujemny_wynik_jev_ma_prawdopodobienstwo_i_zakres_analizy(
        self,
        window: MainWindow,
        docs_dir: Path,
    ) -> None:
        from PySide6.QtWidgets import QLabel

        window._add_documents([docs_dir])
        result = DocumentResult(
            window._files[0],
            status=DocumentStatus.OK,
            page_count=10,
            pages_analyzed=2,
            page_signature_probabilities={1: 0.172, 2: 0.03},
        )
        window._fill_result_row(0, result)
        window._show_details(result)
        assert window.table.item(0, 3).text() == "17.2%"
        assert "BADANEJ" in window.table.item(0, 2).text()
        labels = " ".join(label.text() for label in window.details_container.findChildren(QLabel))
        assert "strona 1: 17.2%" in labels
        assert "Pozostałe strony mogą zawierać podpisy" in labels

    def test_otwieranie_zrodla_uzywa_lokalnego_pliku(
        self, window: MainWindow, monkeypatch, tmp_path
    ):
        urls = []
        monkeypatch.setattr(
            "signum.ui.main_window.QDesktopServices.openUrl", lambda url: urls.append(url) or True
        )
        path = tmp_path / "source.pdf"
        window._open_source_document(path)
        assert urls[0].isLocalFile()
        assert Path(urls[0].toLocalFile()) == path.resolve()

    def test_stan_poczatkowy(self, window: MainWindow) -> None:
        assert window.table.rowCount() == 0
        assert not window.act_process.isEnabled()
        assert not window.act_cancel.isEnabled()
        assert window._left_stack.currentIndex() == 0  # podpowiedź drag&drop

    def test_dodanie_dokumentow(self, window: MainWindow, docs_dir: Path) -> None:
        window._add_documents([docs_dir])
        assert window.table.rowCount() == 5  # 2×pdf + 2×skan + 1 w podfolderze
        assert window.act_process.isEnabled()
        assert window._left_stack.currentIndex() == 1  # tabela widoczna
        # plik .txt pominięty
        names = [window.table.item(r, 0).text() for r in range(window.table.rowCount())]
        assert "notatka.txt" not in names

    def test_duplikaty_nie_sa_dodawane(self, window: MainWindow, docs_dir: Path) -> None:
        window._add_documents([docs_dir])
        count = window.table.rowCount()
        window._add_documents([docs_dir])
        assert window.table.rowCount() == count

    def test_wiersz_wyniku_podpisany(self, window: MainWindow, docs_dir: Path) -> None:
        window._add_documents([docs_dir])
        result = DocumentResult(
            path=window._files[0],
            status=DocumentStatus.OK,
            title="Umowa najmu",
            findings=[
                SignatureFinding(
                    kind=SignatureKind.HANDWRITTEN, page=1, confidence=88, crop_png=_PNG
                )
            ],
            page_count=1,
            pages_analyzed=1,
        )
        window._on_file_done(0, result)
        assert window.table.item(0, 1).text() == "Umowa najmu"
        assert window.table.item(0, 2).text() == "PODPISANY (1)"
        assert window.table.item(0, 3).text() == "88%"
        assert window.table.item(0, 4).text() == "OK"

    def test_wiersz_wyniku_blad(self, window: MainWindow, docs_dir: Path) -> None:
        window._add_documents([docs_dir])
        result = DocumentResult(
            path=window._files[0], status=DocumentStatus.ERROR, error="zepsuty plik"
        )
        window._on_file_done(0, result)
        assert window.table.item(0, 4).text() == "Błąd"
        assert window.table.item(0, 4).toolTip().startswith("zepsuty plik")
        assert "czytniku PDF" in window.table.item(0, 4).toolTip()

    def test_panel_szczegolow_z_wycinkiem(self, window: MainWindow, docs_dir: Path) -> None:
        window._add_documents([docs_dir])
        result = DocumentResult(
            path=window._files[0],
            status=DocumentStatus.OK,
            title="Protokół",
            findings=[
                SignatureFinding(kind=SignatureKind.STAMP, page=2, confidence=75, crop_png=_PNG)
            ],
            page_count=2,
            pages_analyzed=2,
        )
        window._on_file_done(0, result)
        window.table.selectRow(0)
        texts = _collect_labels(window)
        assert any("Protokół" in t for t in texts)
        assert any("pieczątka" in t.lower() for t in texts)
        assert any("75%" in t for t in texts)

    def test_wyczysc(self, window: MainWindow, docs_dir: Path) -> None:
        window._add_documents([docs_dir])
        window._on_clear()
        assert window.table.rowCount() == 0
        assert window._files == []
        assert window._left_stack.currentIndex() == 0

    def test_plakietka_online_ukryta_dla_ollamy(self, window: MainWindow) -> None:
        assert not window.online_badge.isVisibleTo(window)

    def test_plakietka_online_widoczna_dla_chmury(self, qtbot, isolated_config) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        config = AppConfig()
        config.provider = "openai"
        config.save()
        win = MainWindow()
        qtbot.addWidget(win)
        assert win.online_badge.isVisibleTo(win)

    def test_plakietka_online_widoczna_dla_zdalnej_ollamy(self, qtbot, isolated_config) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        config = AppConfig(ollama_url="https://ollama.example.test")
        config.save()
        win = MainWindow()
        qtbot.addWidget(win)
        assert win.online_badge.isVisibleTo(win)

    def test_jedno_ostrzezenie_przed_cala_partia(
        self, window: MainWindow, docs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window._add_documents([docs_dir])
        calls = 0

        def reject_risk() -> bool:
            nonlocal calls
            calls += 1
            return False

        monkeypatch.setattr(window, "_confirm_batch_risk", reject_risk)

        window._on_process()

        assert calls == 1
        assert len(window._files) == 5
        assert window._worker is None


class TestSettingsDialog:
    @pytest.mark.parametrize("provider", ["ollama", "openai", "anthropic", "vjev"])
    def test_adres_model_i_klucz_dla_kazdego_dostawcy(
        self,
        qtbot,
        monkeypatch,
        provider,
    ) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        monkeypatch.setattr("signum.ui.settings_dialog.get_api_key", lambda _: None)
        config = AppConfig(provider=provider)
        dialog = SettingsDialog(config)
        qtbot.addWidget(dialog)
        assert dialog._provider() == provider
        assert dialog.provider_combo.currentData() == (
            "api" if provider in {"openai", "anthropic"} else provider
        )
        if provider == "ollama":
            dialog.ollama_url.setText("https://model.example.test")
            dialog.ollama_model.setEditText("my-vision-model")
        else:
            dialog._url_edits[provider].setText("https://model.example.test/v1")
            dialog._model_edits[provider].setText("my-vision-model")
        dialog._key_edits[provider].setText("draft-key")
        collected = dialog._collect_config()
        assert collected.api_base_url.startswith("https://model.example.test")
        assert getattr(collected, f"{provider}_model") == "my-vision-model"
        assert dialog._current_api_key() == "draft-key"
        assert "api_key" not in collected.__dataclass_fields__

    def test_przelaczanie_zachowuje_osobne_prompty_llm_i_jev(
        self,
        qtbot,
        monkeypatch,
    ) -> None:  # type: ignore[no-untyped-def]
        from signum.ai.jev_prompts import JEV_PROMPT_INSTRUCTIONS
        from signum.config import AppConfig

        monkeypatch.setattr("signum.ui.settings_dialog.get_api_key", lambda _: None)
        dialog = SettingsDialog(AppConfig())
        qtbot.addWidget(dialog)
        dialog.prompt_edit.setPlainText("LLM instructions")
        dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("vjev"))
        assert dialog.prompt_edit.toPlainText() == JEV_PROMPT_INSTRUCTIONS
        dialog.prompt_edit.setPlainText("Jev instructions")
        dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("api"))
        dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("vjev"))
        assert dialog.prompt_edit.toPlainText() == "Jev instructions"
        dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("api"))
        assert dialog.prompt_edit.toPlainText() == "LLM instructions"
        config = dialog._collect_config()
        assert config.custom_prompt == "LLM instructions"
        assert config.jev_custom_prompt == "Jev instructions"

    @pytest.mark.parametrize("provider", ["vjev"])
    def test_testuj_uzywa_niezapisanych_ustawien_i_klucza(
        self,
        qtbot,
        monkeypatch,
        provider,
    ) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        captured = []

        def check(model):  # type: ignore[no-untyped-def]
            captured.append((model._base_url, model._model, model._api_key))
            return "test OK"

        monkeypatch.setattr("signum.ui.settings_dialog.get_api_key", lambda _: None)
        monkeypatch.setattr("signum.ai.jev_client.JevVisionModel.check_connection", check)
        dialog = SettingsDialog(AppConfig(provider=provider))
        qtbot.addWidget(dialog)
        dialog._url_edits[provider].setText("https://draft.example.test/v1")
        dialog._model_edits[provider].setText("draft-model")
        dialog._key_edits[provider].setText("draft-key")
        dialog.test_button.click()
        qtbot.waitUntil(lambda: dialog._test_worker is None)
        assert captured == [("https://draft.example.test/v1", "draft-model", "draft-key")]
        assert "test OK" in dialog.test_result.text()

    def test_przycisk_zatrzymania_jev_uzywa_biezacego_katalogu(
        self,
        qtbot,
        monkeypatch,
    ) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        captured = []

        def stop(model):  # type: ignore[no-untyped-def]
            captured.append((model._base_url, model._runtime_dir))
            return "Jev zatrzymany"

        monkeypatch.setattr("signum.ui.settings_dialog.get_api_key", lambda _: None)
        monkeypatch.setattr("signum.ai.jev_client.JevVisionModel.stop_local", stop)
        dialog = SettingsDialog(AppConfig(provider="vjev"))
        qtbot.addWidget(dialog)
        dialog._url_edits["vjev"].setText("http://127.0.0.1:8877/v1")
        dialog.vjev_runtime_dir.setText("H:/test/runtime")
        dialog.stop_jev_button.click()
        qtbot.waitUntil(lambda: dialog._test_worker is None)
        assert captured == [("http://127.0.0.1:8877/v1", "H:/test/runtime")]
        assert "Jev zatrzymany" in dialog.test_result.text()

    def test_zapis_i_usuniecie_kluczy_tylko_w_magazynie(
        self,
        qtbot,
        isolated_config,
        monkeypatch,
    ) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        keys = {}
        monkeypatch.setattr("signum.ui.settings_dialog.get_api_key", lambda _: None)
        monkeypatch.setattr("signum.ui.settings_dialog.set_api_key", keys.__setitem__)
        dialog = SettingsDialog(AppConfig(provider="vjev"))
        qtbot.addWidget(dialog)
        dialog._key_edits["anthropic"].setText("private-test-key")
        dialog._key_edits["vjev"].setText("remove-me")
        from PySide6.QtWidgets import QPushButton

        clear = next(
            button
            for button in dialog._key_edits["vjev"].parent().findChildren(QPushButton)
            if button.text() == "Wyczyść"
        )
        clear.click()
        dialog._on_save()
        assert keys["anthropic"] == "private-test-key"
        assert keys["vjev"] == ""
        assert "private-test-key" not in isolated_config.read_text(encoding="utf-8")
        assert AppConfig.load().provider == "vjev"

    def test_test_polaczenia_chroni_watek_przed_zamknieciem_dialogu(
        self,
        qtbot,
        isolated_config,
        monkeypatch,
    ) -> None:  # type: ignore[no-untyped-def]
        import threading

        from signum.config import AppConfig

        started = threading.Event()
        release = threading.Event()

        def check(_model):  # type: ignore[no-untyped-def]
            started.set()
            release.wait(5)
            return "OK"

        monkeypatch.setattr("signum.ui.settings_dialog.get_api_key", lambda _: None)
        monkeypatch.setattr("signum.ai.jev_client.JevVisionModel.check_connection", check)
        dialog = SettingsDialog(AppConfig(provider="vjev"))
        qtbot.addWidget(dialog)
        dialog.show()
        dialog._on_test_clicked()
        try:
            qtbot.waitUntil(started.is_set)
            dialog.reject()
            dialog._on_save()
            assert dialog.isVisible()
            assert not dialog.buttons.isEnabled()
            assert not isolated_config.exists()
        finally:
            release.set()
            qtbot.waitUntil(lambda: dialog._test_worker is None)
        assert dialog.buttons.isEnabled()
        dialog.reject()
        assert not dialog.isVisible()

    def test_wczytuje_i_zbiera_konfiguracje(self, qtbot, isolated_config) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        config = AppConfig.load()
        dialog = SettingsDialog(config)
        qtbot.addWidget(dialog)
        assert dialog.provider_combo.currentData() == "ollama"
        assert dialog.ollama_model.currentText() == "gemma4:12b"

        dialog.max_pages.setValue(42)
        collected = dialog._collect_config()
        assert collected.max_pages_per_doc == 42
        assert config.max_pages_per_doc != 42

    def test_zmiana_dostawcy_przelacza_strone(self, qtbot, isolated_config) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        dialog = SettingsDialog(AppConfig.load())
        qtbot.addWidget(dialog)
        dialog.provider_combo.setCurrentIndex(1)  # openai
        assert dialog.stack.currentIndex() == 1
        assert dialog._collect_config().provider == "openai"

    def test_prompt_programu_domyslny_i_wlasny(self, qtbot, isolated_config) -> None:  # type: ignore[no-untyped-def]
        from signum.ai.prompts import PROMPT_INSTRUCTIONS
        from signum.config import AppConfig

        dialog = SettingsDialog(AppConfig.load())
        qtbot.addWidget(dialog)
        assert dialog.prompt_edit.toPlainText() == PROMPT_INSTRUCTIONS
        # Domyślna treść jest zapisywana jako pusta (= podążaj za aktualizacjami).
        assert dialog._collect_config().custom_prompt == ""
        dialog.prompt_edit.setPlainText("Szukaj też adnotacji przy słowie Podpis.")
        assert dialog._collect_config().custom_prompt == "Szukaj też adnotacji przy słowie Podpis."

    def test_zbyt_dlugi_prompt_jest_odrzucany(self, qtbot, isolated_config) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        dialog = SettingsDialog(AppConfig.load())
        qtbot.addWidget(dialog)
        dialog.prompt_edit.setPlainText("x" * 20_001)

        with pytest.raises(ValueError):
            dialog._collect_config()

    def test_num_ctx_wczytanie_i_zapis(self, qtbot, isolated_config) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        config = AppConfig.load()
        config.ollama_num_ctx = 16384
        dialog = SettingsDialog(config)
        qtbot.addWidget(dialog)
        assert dialog.ollama_num_ctx.value() == 16384
        dialog.ollama_num_ctx.setValue(32768)
        assert dialog._collect_config().ollama_num_ctx == 32768


class TestOnlineWarningDialog:
    def test_odliczanie_odblokowuje_przycisk(self, qtbot) -> None:  # type: ignore[no-untyped-def]
        dialog = OnlineWarningDialog()
        qtbot.addWidget(dialog)
        assert not dialog.accept_button.isEnabled()
        assert "(3)" in dialog.accept_button.text()
        for _ in range(dialog.COUNTDOWN_S):
            dialog._tick()
        assert dialog.accept_button.isEnabled()
        assert dialog.accept_button.text() == "Rozumiem zagrożenie"


class TestBatchRiskDialog:
    def test_wymaga_obu_potwierdzen(self, qtbot) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        dialog = BatchRiskDialog(AppConfig(), 12)
        qtbot.addWidget(dialog)

        assert not dialog.accept_button.isEnabled()
        assert "12 dokumentów" in _dialog_text(dialog)
        assert "Tryb lokalny" in _dialog_text(dialog)
        assert "edukacyjne" in _dialog_text(dialog)
        assert "nie nadaje się do użytku w organizacjach" in _dialog_text(dialog)
        assert len(dialog._acknowledgements) == 2

        dialog.purpose_ack.setChecked(True)
        assert not dialog.accept_button.isEnabled()
        dialog.processing_ack.setChecked(True)
        assert dialog.accept_button.isEnabled()
        dialog.purpose_ack.setChecked(False)
        assert not dialog.accept_button.isEnabled()

    def test_tryb_online_ostrzega_o_wysylce(self, qtbot) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        config = AppConfig(provider="openai")
        dialog = BatchRiskDialog(config, 3)
        qtbot.addWidget(dialog)

        text = _dialog_text(dialog)
        assert "Tryb zdalny" in text
        assert "przez internet do usług stron trzecich" in text
        assert "przetwarzana" in dialog.processing_ack.accessibleName()

    def test_zdalna_ollama_jest_trybem_online(self, qtbot) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        config = AppConfig(ollama_url="https://ollama.example.test")
        dialog = BatchRiskDialog(config, 2)
        qtbot.addWidget(dialog)

        assert "Tryb zdalny" in _dialog_text(dialog)
        assert "opuszczą komputer" in _dialog_text(dialog)

    def test_ollama_cloud_nie_jest_przetwarzaniem_lokalnym(self, qtbot) -> None:  # type: ignore[no-untyped-def]
        from signum.config import AppConfig

        dialog = BatchRiskDialog(AppConfig(ollama_model="gemma4:31b-cloud"), 2)
        qtbot.addWidget(dialog)

        assert "Tryb zdalny" in _dialog_text(dialog)
        assert "przez internet do usług stron trzecich" in _dialog_text(dialog)


def _collect_labels(window: MainWindow) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in window.details_container.findChildren(QLabel) if label.text()]


def _dialog_text(dialog: BatchRiskDialog) -> str:
    from PySide6.QtWidgets import QLabel

    return " ".join(label.text() for label in dialog.findChildren(QLabel))
