"""Wykrywanie podpisów cyfrowych w strukturze PDF (bez udziału modelu AI).

Obecność podpisu cyfrowego to fakt strukturalny — pole formularza typu
``/Sig`` z wypełnioną wartością ``/V``. Odczytujemy go deterministycznie
przez pypdf zamiast pytać model wizyjny. Rozpoznajemy wszystkie podtypy
spotykane w praktyce (``/SubFilter``): PAdES/CAdES, CMS/PKCS#7 (adbe),
X.509 oraz znaczniki czasu RFC 3161, a także podpisy certyfikujące (DocMDP)
i podpisy praw użycia (UR3). Nie weryfikujemy kryptograficznej poprawności
podpisów — sprawdzamy wyłącznie ich obecność.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

_SUBFILTER_LABELS = {
    "/ETSI.CAdES.detached": "PAdES / CAdES (ETSI.CAdES.detached)",
    "/adbe.pkcs7.detached": "CMS / PKCS#7 (adbe.pkcs7.detached)",
    "/adbe.pkcs7.sha1": "PKCS#7 SHA-1 (adbe.pkcs7.sha1)",
    "/adbe.x509.rsa_sha1": "X.509 RSA-SHA1 (adbe.x509.rsa_sha1)",
    "/ETSI.RFC3161": "znacznik czasu (ETSI.RFC3161)",
}
MAX_FIELD_DEPTH = 64
MAX_FIELD_OBJECTS = 5000
MAX_WIDGET_SCAN_PAGES = 10_000
MAX_PDF_TEXT_LENGTH = 1000


@dataclass(slots=True)
class DigitalSignature:
    """Jeden podpis cyfrowy znaleziony w strukturze PDF."""

    field_name: str
    kind_label: str  # opis podtypu, np. "PAdES / CAdES (…)"
    signer: str | None = None
    signing_time: str | None = None  # ISO 8601 (bez strefy) albo None
    reason: str | None = None
    certification: bool = False  # podpis certyfikujący (DocMDP)
    page: int | None = None  # 1-bazowy numer strony widgetu podpisu
    rect_pt: tuple[float, float, float, float] | None = None  # (x0, y0, x1, y1) w pkt

    @property
    def detail(self) -> str:
        parts = [self.kind_label]
        if self.certification:
            parts.append("podpis certyfikujący (DocMDP)")
        if self.signer:
            parts.append(f"podpisał(a): {self.signer}")
        if self.signing_time:
            parts.append(f"data: {self.signing_time}")
        if self.reason:
            parts.append(f"powód: {self.reason}")
        return "; ".join(parts)


@dataclass(slots=True)
class DigitalScanResult:
    """Wynik skanu struktury PDF pod kątem podpisów cyfrowych."""

    signatures: list[DigitalSignature] = field(default_factory=list)
    empty_signature_fields: list[str] = field(default_factory=list)  # pola bez podpisu
    notes: list[str] = field(default_factory=list)  # np. formularz XFA, szyfrowanie


@dataclass(slots=True)
class _WalkState:
    visited_refs: set[tuple[int, int]] = field(default_factory=set)
    object_count: int = 0
    limit_reported: bool = False


def scan_digital_signatures(path: Path) -> DigitalScanResult:
    """Skanuje PDF pod kątem podpisów cyfrowych.

    Nigdy nie rzuca wyjątku dla uszkodzonych plików — problemy trafiają
    do ``notes`` (detekcja wizyjna może nadal zadziałać).
    """
    result = DigitalScanResult()
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                result.notes.append("PDF zaszyfrowany — pominięto analizę struktury")
                return result
        _scan_reader(reader, result)
    except Exception as exc:
        result.notes.append(f"Nie udało się przeanalizować struktury PDF: {exc}")
    return result


def _scan_reader(reader: PdfReader, result: DigitalScanResult) -> None:
    root = _resolve(reader.trailer.get("/Root"))
    if not isinstance(root, DictionaryObject):
        return
    acro_form = _resolve(root.get("/AcroForm"))
    if isinstance(acro_form, DictionaryObject):
        if acro_form.get("/XFA") is not None:
            result.notes.append("dokument zawiera formularz XFA")
        fields = _resolve(acro_form.get("/Fields"))
        if isinstance(fields, ArrayObject):
            state = _WalkState()
            for field_ref in fields:
                _walk_field(
                    field_ref,
                    parent_name="",
                    reader=reader,
                    result=result,
                    state=state,
                    depth=0,
                )

    # Podpis praw użycia (usage rights, np. Adobe Reader Extensions).
    perms = _resolve(root.get("/Perms"))
    if isinstance(perms, DictionaryObject) and _resolve(perms.get("/UR3")) is not None:
        result.signatures.append(
            DigitalSignature(field_name="(UR3)", kind_label="podpis praw użycia (UR3)")
        )


def _walk_field(
    field_ref: Any,
    parent_name: str,
    reader: PdfReader,
    result: DigitalScanResult,
    state: _WalkState,
    depth: int,
    inherited_type: str = "",
) -> None:
    if depth > MAX_FIELD_DEPTH or state.object_count >= MAX_FIELD_OBJECTS:
        if not state.limit_reported:
            result.notes.append("ograniczono analizę nadmiernie złożonej hierarchii pól PDF")
            state.limit_reported = True
        return
    if isinstance(field_ref, IndirectObject):
        reference = (field_ref.idnum, field_ref.generation)
        if reference in state.visited_refs:
            return
        state.visited_refs.add(reference)
    state.object_count += 1
    field_obj = _resolve(field_ref)
    if not isinstance(field_obj, DictionaryObject):
        return
    partial = str(field_obj.get("/T", "")).strip()[:MAX_PDF_TEXT_LENGTH]
    full_name = (f"{parent_name}.{partial}" if parent_name and partial else partial or parent_name)[
        :MAX_PDF_TEXT_LENGTH
    ]

    kids = _resolve(field_obj.get("/Kids"))
    field_type = str(field_obj.get("/FT", inherited_type))
    # Dzieci z nazwą/typem/wartością są polami; pozostałe widgety opisują
    # wygląd tego samego pola i nie mogą mnożyć liczby podpisów.
    child_fields = []
    if isinstance(kids, ArrayObject):
        for kid in kids:
            child = _resolve(kid)
            if isinstance(child, DictionaryObject) and any(
                key in child for key in ("/T", "/FT", "/V", "/Kids")
            ):
                child_fields.append(kid)
    for kid in child_fields:
        _walk_field(kid, full_name, reader, result, state, depth + 1, field_type)

    if field_type != "/Sig" or (child_fields and "/V" not in field_obj):
        return

    value = _resolve(field_obj.get("/V"))
    if not isinstance(value, DictionaryObject):
        result.empty_signature_fields.append(full_name or "(bez nazwy)")
        return

    sig = DigitalSignature(
        field_name=full_name or "(bez nazwy)",
        kind_label=_classify_subfilter(value),
        signer=_text_or_none(value.get("/Name")),
        signing_time=_parse_pdf_date(_text_or_none(value.get("/M"))),
        reason=_text_or_none(value.get("/Reason")),
        certification=_is_certification(value),
    )
    sig.page, sig.rect_pt = _find_widget(field_obj, field_ref, reader)
    result.signatures.append(sig)


def _classify_subfilter(value: DictionaryObject) -> str:
    subfilter = str(value.get("/SubFilter", "")).strip()[:200]
    if subfilter in _SUBFILTER_LABELS:
        return _SUBFILTER_LABELS[subfilter]
    if subfilter:
        return f"podpis cyfrowy ({subfilter.lstrip('/')})"
    return "podpis cyfrowy (nieokreślony podtyp)"


def _is_certification(value: DictionaryObject) -> bool:
    reference = _resolve(value.get("/Reference"))
    if not isinstance(reference, ArrayObject):
        return False
    for item in reference:
        obj = _resolve(item)
        if isinstance(obj, DictionaryObject) and str(obj.get("/TransformMethod", "")) == "/DocMDP":
            return True
    return False


def _find_widget(
    field_obj: DictionaryObject, field_ref: Any, reader: PdfReader
) -> tuple[int | None, tuple[float, float, float, float] | None]:
    """Szuka widgetu (annotacji) pola podpisu: numer strony + prostokąt.

    Pole może być scalone z widgetem (jeden słownik) albo mieć widgety
    w ``/Kids``. Porównujemy referencje pośrednie z ``/Annots`` stron.
    """
    wanted: set[tuple[int, int]] = set()
    if isinstance(field_ref, IndirectObject):
        wanted.add((field_ref.idnum, field_ref.generation))
    kids = _resolve(field_obj.get("/Kids"))
    if isinstance(kids, ArrayObject):
        for kid in kids:
            if isinstance(kid, IndirectObject):
                wanted.add((kid.idnum, kid.generation))

    for page_index, page in enumerate(reader.pages):
        if page_index >= MAX_WIDGET_SCAN_PAGES:
            break
        annots = _resolve(page.get("/Annots"))
        if not isinstance(annots, ArrayObject):
            continue
        for annot in annots:
            if not isinstance(annot, IndirectObject):
                continue
            if (annot.idnum, annot.generation) not in wanted:
                continue
            annot_obj = _resolve(annot)
            rect = _rect_or_none(annot_obj)
            return page_index + 1, rect
    return None, None


def _rect_or_none(obj: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(obj, DictionaryObject):
        return None
    rect = _resolve(obj.get("/Rect"))
    if not isinstance(rect, ArrayObject) or len(rect) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in rect)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        return None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if x1 - x0 < 1 or y1 - y0 < 1:  # niewidoczny podpis (rect zerowy)
        return None
    return x0, y0, x1, y1


_PDF_DATE = re.compile(
    r"D:(?P<y>\d{4})(?P<mo>\d{2})?(?P<d>\d{2})?(?P<h>\d{2})?(?P<mi>\d{2})?(?P<s>\d{2})?"
)


def _parse_pdf_date(raw: str | None) -> str | None:
    """``D:20260712143000+02'00'`` → ``2026-07-12 14:30:00``."""
    if not raw:
        return None
    match = _PDF_DATE.match(raw.strip())
    if not match:
        return raw[:100]
    g = match.groupdict()
    date = f"{g['y']}-{g['mo'] or '01'}-{g['d'] or '01'}"
    if g["h"]:
        return f"{date} {g['h']}:{g['mi'] or '00'}:{g['s'] or '00'}"
    return date


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()[:MAX_PDF_TEXT_LENGTH]
    return text or None


def _resolve(obj: Any) -> Any:
    """Rozwiązuje referencje pośrednie pypdf."""
    if isinstance(obj, IndirectObject):
        return obj.get_object()
    return obj
