"""Testy wykrywania podpisów cyfrowych w strukturze PDF."""

from __future__ import annotations

from pathlib import Path

import pytest

from signum.core.digital import scan_digital_signatures


@pytest.mark.parametrize("depth", [1, 3])
def test_typ_podpisu_jest_dziedziczony_po_przodkach(
    tmp_path: Path, signed_pdf_bytes: bytes, depth: int,
) -> None:
    import io

    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

    writer = PdfWriter(clone_from=io.BytesIO(signed_pdf_bytes))
    form = writer._root_object["/AcroForm"]
    ref = form["/Fields"][0]
    del ref.get_object()["/FT"]
    for level in range(depth):
        parent = DictionaryObject({
            NameObject("/T"): TextStringObject(f"Parent{level}"),
            NameObject("/Kids"): ArrayObject([ref]),
        })
        parent_ref = writer._add_object(parent)
        ref.get_object()[NameObject("/Parent")] = parent_ref
        ref = parent_ref
    ref.get_object()[NameObject("/FT")] = NameObject("/Sig")
    form[NameObject("/Fields")] = ArrayObject([ref])
    path = tmp_path / "inherited.pdf"
    writer.write(path)

    scan = scan_digital_signatures(path)
    assert len(scan.signatures) == 1
    assert scan.signatures[0].field_name.endswith("Parent0.Signature1")
    assert scan.signatures[0].page == 1
    assert scan.empty_signature_fields == []


def test_widget_dziecko_nie_powiela_podpisu(tmp_path: Path, signed_pdf_bytes: bytes) -> None:
    import io

    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject

    writer = PdfWriter(clone_from=io.BytesIO(signed_pdf_bytes))
    field_ref = writer._root_object["/AcroForm"]["/Fields"][0]
    field = field_ref.get_object()
    widget = DictionaryObject({NameObject("/Parent"): field_ref})
    for name in ("/Type", "/Subtype", "/Rect", "/P", "/AP"):
        if name in field:
            widget[NameObject(name)] = field.pop(name)
    widget_ref = writer._add_object(widget)
    field[NameObject("/Kids")] = ArrayObject([widget_ref])
    writer.pages[0][NameObject("/Annots")] = ArrayObject([widget_ref])
    path = tmp_path / "widget.pdf"
    writer.write(path)
    scan = scan_digital_signatures(path)
    assert len(scan.signatures) == 1
    assert scan.signatures[0].page == 1
    assert scan.signatures[0].rect_pt is not None


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_wykrywa_podpis_pkcs7(tmp_path: Path, signed_pdf_bytes: bytes) -> None:
    result = scan_digital_signatures(_write(tmp_path, "signed.pdf", signed_pdf_bytes))
    assert len(result.signatures) == 1
    sig = result.signatures[0]
    assert sig.field_name == "Signature1"
    assert "adbe.pkcs7.detached" in sig.kind_label
    assert sig.page == 1
    assert sig.rect_pt is not None
    assert sig.signing_time is not None
    assert sig.reason == "Akceptacja aneksu"


def test_wykrywa_podpis_pades(tmp_path: Path, pades_pdf_bytes: bytes) -> None:
    result = scan_digital_signatures(_write(tmp_path, "pades.pdf", pades_pdf_bytes))
    assert len(result.signatures) == 1
    assert "PAdES" in result.signatures[0].kind_label


def test_podpis_niewidoczny_bez_rect(
    tmp_path: Path, invisible_signed_pdf_bytes: bytes
) -> None:
    result = scan_digital_signatures(
        _write(tmp_path, "invisible.pdf", invisible_signed_pdf_bytes)
    )
    assert len(result.signatures) == 1
    assert result.signatures[0].rect_pt is None  # zerowy widget = podpis niewidoczny


def test_puste_pole_podpisu_nie_jest_podpisem(
    tmp_path: Path, empty_field_pdf_bytes: bytes
) -> None:
    result = scan_digital_signatures(_write(tmp_path, "empty.pdf", empty_field_pdf_bytes))
    assert result.signatures == []
    assert result.empty_signature_fields == ["PodpisPracownika"]


def test_pdf_bez_formularza(tmp_path: Path, text_pdf_bytes: bytes) -> None:
    result = scan_digital_signatures(_write(tmp_path, "plain.pdf", text_pdf_bytes))
    assert result.signatures == []
    assert result.empty_signature_fields == []


def test_uszkodzony_pdf_nie_rzuca_wyjatku(tmp_path: Path) -> None:
    result = scan_digital_signatures(_write(tmp_path, "broken.pdf", b"to nie jest pdf"))
    assert result.signatures == []
    assert result.notes  # problem odnotowany zamiast wyjątku


def test_detail_zawiera_kluczowe_informacje(tmp_path: Path, signed_pdf_bytes: bytes) -> None:
    result = scan_digital_signatures(_write(tmp_path, "signed.pdf", signed_pdf_bytes))
    detail = result.signatures[0].detail
    assert "adbe.pkcs7.detached" in detail
    assert "powód: Akceptacja aneksu" in detail
