"""Testy eksportu raportów HTML i CSV."""

from __future__ import annotations

import base64
import csv
import io
from pathlib import Path

import pytest
from PIL import Image

from signum.core.models import DocumentResult, DocumentStatus, SignatureFinding, SignatureKind
from signum.core.pipeline import BatchResult
from signum.report import build_csv, build_html, write_csv

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg=="
)


def _tiny_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buf, format="JPEG")
    return buf.getvalue()


_JPEG = _tiny_jpeg()


def _batch() -> BatchResult:
    signed = DocumentResult(
        path=Path("C:/docs/umowa.pdf"),
        status=DocumentStatus.OK,
        title="Umowa o dzieło",
        findings=[
            SignatureFinding(
                kind=SignatureKind.HANDWRITTEN,
                page=1,
                confidence=92,
                crop_png=_PNG,
                overview_jpeg=_JPEG,
            ),
            SignatureFinding(
                kind=SignatureKind.DIGITAL,
                page=1,
                confidence=100,
                detail="PAdES / CAdES (ETSI.CAdES.detached); podpisał(a): Jan Testowy",
            ),
        ],
        page_count=2,
        pages_analyzed=2,
        duration_s=12.5,
    )
    unsigned = DocumentResult(
        path=Path("C:/docs/regulamin.pdf"),
        status=DocumentStatus.OK,
        title="Regulamin",
        page_count=1,
        pages_analyzed=1,
    )
    failed = DocumentResult(
        path=Path("C:/docs/zepsuty.pdf"),
        status=DocumentStatus.ERROR,
        error="Nie można odczytać pliku",
    )
    return BatchResult(
        results=[signed, unsigned, failed],
        model_name="Ollama: gemma4:12b",
        started_at=1000.0,
        finished_at=1060.0,
    )


class TestHtml:
    def test_zawiera_kluczowe_elementy(self) -> None:
        html = build_html(_batch())
        assert "Umowa o dzieło" in html
        assert "PODPISANY (2)" in html
        assert "BRAK PODPISU" in html
        assert "BŁĄD" in html
        assert "podpis odręczny" in html
        assert "pewność 92%" in html
        assert "Jan Testowy" in html
        assert "Ollama: gemma4:12b" in html

    def test_wycinki_osadzone_jako_base64(self) -> None:
        html = build_html(_batch())
        assert "data:image/png;base64," in html
        assert base64.b64encode(_PNG).decode("ascii") in html

    def test_miniatura_strony_osadzona(self) -> None:
        html = build_html(_batch())
        assert "data:image/jpeg;base64," in html
        assert base64.b64encode(_JPEG).decode("ascii") in html
        assert "miniatura strony z zaznaczonym znaleziskiem" in html

    def test_html_escape(self) -> None:
        batch = _batch()
        batch.results[0].title = "<script>alert(1)</script>"
        html = build_html(batch)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_raport_nie_ujawnia_pelnej_sciezki(self) -> None:
        html = build_html(_batch())
        assert "C:/docs" not in html
        assert "umowa.pdf" in html
        assert "Content-Security-Policy" in html

    def test_informacja_o_przerwaniu(self) -> None:
        batch = _batch()
        batch.abort_error = "Brak połączenia z Ollamą"
        assert "Brak połączenia z Ollamą" in build_html(batch)

    def test_raport_przypomina_o_recznej_weryfikacji(self) -> None:
        html = build_html(_batch())
        assert "może zwrócić wynik błędny lub niepełny" in html
        assert "wymaga ręcznej weryfikacji" in html
        assert "nie potwierdza ich autentyczności" in html


class TestCsv:
    def test_jev_zapisuje_ocene_ujemna_i_nie_udaje_zliczania(self) -> None:
        import json

        result = DocumentResult(
            Path("page.pdf"),
            status=DocumentStatus.OK,
            page_count=10,
            pages_analyzed=1,
            page_signature_probabilities={1: 0.172},
        )
        batch = BatchResult(results=[result])
        rows = list(csv.reader(io.StringIO(build_csv(batch)), delimiter=";"))
        assert rows[1][4] == ""
        assert json.loads(rows[1][7]) == {"1": 0.172}
        assert rows[1][8:10] == ["1", "10"]
        assert rows[0][10:] == ["przygotowanie_s", "ladowanie_s", "dzialanie_s", "lacznie_s"]
        assert rows[1][10:] == ["0.0", "0.0", "0.0", "0.0"]
        html = build_html(batch)
        assert "strona 1: 17.2%" in html
        assert "Nie zbadano wszystkich stron" in html

    def test_write_csv_bez_podwojnych_crlf(self, tmp_path: Path) -> None:
        # Regresja: write_text na Windows tłumaczy \n → \r\n, co przy
        # CRLF w treści dawało \r\r\n (puste wiersze w Excelu).
        target = tmp_path / "raport.csv"
        write_csv(target, _batch())
        raw = target.read_bytes()
        assert b"\r\r\n" not in raw
        assert raw.count(b"\r\n") == 4  # nagłówek + 3 wiersze
        assert raw.startswith(b"\xef\xbb\xbf")  # BOM dla Excela

    def test_struktura_i_wartosci(self) -> None:
        rows = list(csv.reader(io.StringIO(build_csv(_batch())), delimiter=";"))
        assert rows[0][:4] == ["plik", "tytul", "status", "podpisany"]
        assert len(rows) == 4
        signed_row = rows[1]
        assert signed_row[1] == "Umowa o dzieło"
        assert signed_row[3] == "TAK"
        assert signed_row[4] == "2"
        assert rows[2][3] == "NIE"
        assert rows[3][2] == "BŁĄD"

    @pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
    def test_neutralizuje_formuly_excela(self, prefix: str) -> None:
        batch = _batch()
        batch.results[0].title = prefix + "SUM(A1:A2)"
        rows = list(csv.reader(io.StringIO(build_csv(batch)), delimiter=";"))
        assert rows[1][1].startswith("'")
