"""Testy orkiestracji: analiza dokumentu i przetwarzanie partii z atrapą modelu."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from signum.ai.base import AIConnectionError, AIResponseError, VisionModel
from signum.ai.prompts import PAGE_PROMPT
from signum.core.models import DocumentStatus, SignatureKind
from signum.core.pipeline import (
    BatchResult,
    CancelToken,
    DocumentAnalyzer,
    _safe_document_error,
    run_batch,
)
from tests import docfactory


class FakeVisionModel(VisionModel):
    """Deterministyczna atrapa: zawsze zwraca zadany JSON."""

    def __init__(self, response: dict | None = None, fail_with: Exception | None = None):
        self.calls = 0
        self.last_prompt: str | None = None
        self._fail_with = fail_with
        self._response = response or {
            "description": "Umowa testowa",
            "signatures": [
                {"type": "handwritten", "confidence": 92, "box_2d": [800, 600, 880, 900]}
            ],
        }

    @property
    def name(self) -> str:
        return "fake-model"

    def _generate(self, image_jpeg: bytes, prompt: str) -> str:
        self.calls += 1
        self.last_prompt = prompt
        if self._fail_with is not None:
            raise self._fail_with
        return json.dumps(self._response)

    def check_connection(self) -> str:
        return "ok"


def _analyzer(model: VisionModel, max_pages: int = 5) -> DocumentAnalyzer:
    return DocumentAnalyzer(model=model, max_pages=max_pages, image_max_side=512)


def _scan_file(tmp_path: Path) -> Path:
    path = tmp_path / "skan.png"
    docfactory.make_signed_scan().save(path)
    return path


def test_komunikat_bledu_nie_ujawnia_pelnej_sciezki(tmp_path: Path) -> None:
    path = tmp_path / "tajny.pdf"
    message = _safe_document_error(OSError(f"nie można otworzyć {path}"), path)

    assert str(tmp_path) not in message
    assert path.name in message


class TestDocumentAnalyzer:
    @pytest.mark.parametrize("provider", ["openai", "anthropic"])
    @pytest.mark.parametrize("raw", ["{}", '{"signatures":null}'])
    def test_nieprawidlowy_schemat_jest_ponawiany(
        self, tmp_path: Path, provider: str, raw: str,
    ) -> None:
        from signum.ai import create_vision_model
        from signum.config import AppConfig

        model = create_vision_model(AppConfig(provider=provider), api_key="test")
        payload = (
            {"choices": [{"message": {"content": raw}}]} if provider == "openai"
            else {"content": [{"type": "text", "text": raw}]}
        )
        model._session.post = Mock(return_value=Mock(
            status_code=200, json=Mock(return_value=payload),
        ))
        result = _analyzer(model).analyze(_scan_file(tmp_path), CancelToken())
        assert result.status == DocumentStatus.ERROR
        assert model._session.post.call_count == 2

    def test_blad_struktury_pdf_dociera_do_raportow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import csv
        import io

        from signum.report.export import build_csv, build_html

        pdf = tmp_path / "document.pdf"
        pdf.write_bytes(docfactory.make_text_pdf())
        monkeypatch.setattr(
            "signum.core.digital.PdfReader", Mock(side_effect=ValueError("scan error")),
        )
        model = FakeVisionModel(response={"signatures": []})
        result = _analyzer(model).analyze(pdf, CancelToken())
        assert model.calls == 1  # analiza wizualna wciąż dostępna
        assert result.status == DocumentStatus.ERROR
        assert "scan error" in result.error
        report = build_html(BatchResult([result]))
        assert "scan error" in report
        assert "BRAK PODPISU" not in report
        row = next(csv.DictReader(io.StringIO(build_csv(BatchResult([result]))), delimiter=";"))
        assert row["podpisany"] == ""

    def test_blad_pozniejszej_strony_jest_bledem_dokumentu(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from signum.core import rendering

        pdf = tmp_path / "partly-broken.pdf"
        pdf.write_bytes(docfactory.make_text_pdf(pages=3))
        original = rendering._render_page

        def render(document, number):
            if number == 2:
                raise ValueError("broken page")
            return original(document, number)

        monkeypatch.setattr(rendering, "_render_page", render)
        model = FakeVisionModel(response={"signatures": []})
        result = _analyzer(model).analyze(pdf, CancelToken())
        assert result.status == DocumentStatus.ERROR
        assert "broken page" in result.error
        assert result.pages_analyzed == model.calls == 1

    def test_blad_ai_zachowuje_wykryty_podpis_cyfrowy(
        self, tmp_path: Path, signed_pdf_bytes: bytes,
    ) -> None:
        pdf = tmp_path / "signed.pdf"
        pdf.write_bytes(signed_pdf_bytes)
        model = FakeVisionModel(fail_with=AIResponseError("bad response"))
        result = _analyzer(model).analyze(pdf, CancelToken())
        assert result.status == DocumentStatus.ERROR
        assert result.is_signed
        assert result.findings[0].kind == SignatureKind.DIGITAL

    @pytest.mark.parametrize("outcome", ["ok", "cancel", "error", "connection"])
    def test_analiza_nie_gromadzi_obrazow_i_zwalnia_zasoby(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
    ) -> None:
        from signum.ai.base import PageAnalysis
        from signum.core import rendering
        from signum.core.pipeline import BatchCancelledError

        pdf = tmp_path / "long.pdf"
        pdf.write_bytes(docfactory.make_text_pdf(pages=20))
        rendered = []
        documents = []
        original_render = rendering._render_page
        original_open = rendering.pdfium.PdfDocument

        def capture_open(*args, **kwargs):
            document = original_open(*args, **kwargs)
            document.close = Mock(wraps=document.close)
            documents.append(document)
            return document

        def capture_render(document, number):
            for previous in rendered:
                with pytest.raises(ValueError, match="closed"):
                    previous.image.getpixel((0, 0))
            page = original_render(document, number)
            rendered.append(page)
            return page

        cancel = CancelToken()
        model = FakeVisionModel()

        def analyze_image(*args, **kwargs):
            assert len(rendered) == model.calls + 1
            model.calls += 1
            if outcome == "cancel":
                cancel.cancel()
            if outcome == "error":
                raise AIResponseError("invalid")
            if outcome == "connection":
                raise AIConnectionError("offline")
            return PageAnalysis("", ())

        monkeypatch.setattr(rendering.pdfium, "PdfDocument", capture_open)
        monkeypatch.setattr(rendering, "_render_page", capture_render)
        monkeypatch.setattr(model, "analyze_image", analyze_image)
        if outcome in {"cancel", "connection"}:
            with pytest.raises(BatchCancelledError if outcome == "cancel" else AIConnectionError):
                _analyzer(model, 20).analyze(pdf, cancel)
        else:
            # Dwie próby tej samej strony przy błędzie odpowiedzi.
            if outcome == "error":
                monkeypatch.setattr(
                    model, "analyze_image", Mock(side_effect=AIResponseError("bad")),
                )
            result = _analyzer(model, 20).analyze(pdf, cancel)
            assert result.status == (DocumentStatus.OK if outcome == "ok" else DocumentStatus.ERROR)
        assert len(rendered) == (20 if outcome == "ok" else 1)
        for page in rendered:
            with pytest.raises(ValueError, match="closed"):
                page.image.getpixel((0, 0))
        assert len(documents) == 1
        documents[0].close.assert_called_once()

    def test_skan_z_podpisem(self, tmp_path: Path) -> None:
        result = _analyzer(FakeVisionModel()).analyze(_scan_file(tmp_path), CancelToken())
        assert result.status is DocumentStatus.OK
        assert result.title == "Umowa testowa"
        assert result.is_signed
        finding = result.findings[0]
        assert finding.kind is SignatureKind.HANDWRITTEN
        assert finding.confidence == 92
        assert finding.crop_png is not None
        assert finding.crop_png.startswith(b"\x89PNG")
        assert finding.overview_jpeg is not None  # miniatura strony z ramką
        assert finding.overview_jpeg.startswith(b"\xff\xd8")

    def test_pdf_podpisany_cyfrowo_laczy_zrodla(
        self, tmp_path: Path, signed_pdf_bytes: bytes
    ) -> None:
        pdf = tmp_path / "aneks.pdf"
        pdf.write_bytes(signed_pdf_bytes)
        model = FakeVisionModel(response={"description": "Aneks do umowy", "signatures": []})
        result = _analyzer(model).analyze(pdf, CancelToken())
        assert result.status is DocumentStatus.OK
        kinds = [f.kind for f in result.findings]
        assert kinds == [SignatureKind.DIGITAL]
        assert result.findings[0].confidence == 100
        assert result.findings[0].crop_png is not None  # widoczny widget podpisu
        assert result.findings[0].overview_jpeg is not None

    def test_uszkodzony_plik_to_error_nie_wyjatek(self, tmp_path: Path) -> None:
        bad = tmp_path / "zepsuty.pdf"
        bad.write_bytes(b"nie pdf")
        result = _analyzer(FakeVisionModel()).analyze(bad, CancelToken())
        assert result.status is DocumentStatus.ERROR
        assert result.error

    def test_bledna_odpowiedz_jest_ponawiana(self, tmp_path: Path) -> None:
        model = FakeVisionModel(fail_with=AIResponseError("zly json"))
        result = _analyzer(model).analyze(_scan_file(tmp_path), CancelToken())
        assert result.status is DocumentStatus.ERROR
        assert model.calls == 2  # pierwsza próba + jedno ponowienie

    def test_tytul_z_nazwy_pliku_gdy_brak_opisu(self, tmp_path: Path) -> None:
        model = FakeVisionModel(response={"description": "", "signatures": []})
        result = _analyzer(model).analyze(_scan_file(tmp_path), CancelToken())
        assert result.title == "skan"

    def test_prompt_niestandardowy_i_domyslny(self, tmp_path: Path) -> None:
        scan = _scan_file(tmp_path)
        custom = FakeVisionModel(response={"description": "X", "signatures": []})
        DocumentAnalyzer(
            model=custom, max_pages=5, image_max_side=512, prompt="MÓJ PROMPT"
        ).analyze(scan, CancelToken())
        assert custom.last_prompt == "MÓJ PROMPT"

        default = FakeVisionModel(response={"description": "X", "signatures": []})
        _analyzer(default).analyze(scan, CancelToken())
        assert default.last_prompt == PAGE_PROMPT

    def test_limit_stron(self, tmp_path: Path) -> None:
        pdf = tmp_path / "dlugi.pdf"
        pdf.write_bytes(docfactory.make_text_pdf(pages=4))
        model = FakeVisionModel(response={"description": "Faktura", "signatures": []})
        result = _analyzer(model, max_pages=2).analyze(pdf, CancelToken())
        assert result.page_count == 4
        assert result.pages_analyzed == 2
        assert model.calls == 2


class TestRunBatch:
    def test_blad_pliku_nie_przerywa_partii(self, tmp_path: Path) -> None:
        good = _scan_file(tmp_path)
        bad = tmp_path / "zly.pdf"
        bad.write_bytes(b"x")
        batch = run_batch([bad, good], _analyzer(FakeVisionModel()), CancelToken())
        assert batch.abort_error is None
        assert [r.status for r in batch.results] == [DocumentStatus.ERROR, DocumentStatus.OK]

    def test_blad_polaczenia_przerywa_partie(self, tmp_path: Path) -> None:
        files = [_scan_file(tmp_path), tmp_path / "nast1.png", tmp_path / "nast2.png"]
        docfactory.make_clean_scan().save(files[1])
        docfactory.make_clean_scan().save(files[2])
        model = FakeVisionModel(fail_with=AIConnectionError("brak połączenia"))
        batch = run_batch(files, _analyzer(model), CancelToken())
        assert batch.abort_error is not None
        assert batch.results[0].status is DocumentStatus.ERROR
        assert all(r.status is DocumentStatus.CANCELLED for r in batch.results[1:])
        assert len(batch.results) == 3

    def test_anulowanie_oznacza_pozostale(self, tmp_path: Path) -> None:
        files = [_scan_file(tmp_path)]
        cancel = CancelToken()
        cancel.cancel()
        batch = run_batch(files, _analyzer(FakeVisionModel()), cancel)
        assert [r.status for r in batch.results] == [DocumentStatus.CANCELLED]

    def test_callbacki_i_statystyki(self, tmp_path: Path) -> None:
        started: list[str] = []
        done: list[str] = []
        files = [_scan_file(tmp_path)]
        batch = run_batch(
            files,
            _analyzer(FakeVisionModel()),
            CancelToken(),
            on_file_start=lambda i, n, p: started.append(f"{i + 1}/{n} {p.name}"),
            on_file_done=lambda i, r: done.append(r.title),
        )
        assert started == ["1/1 skan.png"]
        assert done == ["Umowa testowa"]
        assert batch.signed_count == 1
        assert batch.error_count == 0
        assert batch.model_name == "fake-model"
        assert isinstance(batch, BatchResult)
