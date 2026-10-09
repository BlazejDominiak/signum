"""Eksport wyników do samowystarczalnego raportu HTML oraz CSV.

Raport HTML zawiera wycinki podpisów osadzone jako base64 — pojedynczy plik
można przesłać dalej bez żadnych zależności. CSV służy do dalszej obróbki
(Excel, import do systemów obiegu dokumentów).
"""

from __future__ import annotations

import base64
import csv
import html
import io
import json
from datetime import datetime
from pathlib import Path

from signum import __version__
from signum.core.models import DocumentResult, DocumentStatus
from signum.core.pipeline import BatchResult

_STATUS_LABELS = {
    DocumentStatus.OK: "OK",
    DocumentStatus.ERROR: "BŁĄD",
    DocumentStatus.CANCELLED: "ANULOWANO",
    DocumentStatus.PENDING: "OCZEKUJE",
}

_CSS = """
body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 2rem auto; max-width: 70rem;
       color: #1a1a2e; background: #fafafa; }
h1 { font-size: 1.5rem; } h2 { font-size: 1.1rem; margin: 0 0 .3rem; }
.summary { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 1rem 0 2rem; }
.summary div { background: #fff; border: 1px solid #e0e0e8; border-radius: 8px;
               padding: .8rem 1.2rem; }
.summary b { display: block; font-size: 1.4rem; }
.doc { background: #fff; border: 1px solid #e0e0e8; border-radius: 8px;
       padding: 1rem 1.2rem; margin-bottom: 1rem; }
.badge { display: inline-block; border-radius: 999px; padding: .15rem .7rem;
         font-size: .8rem; font-weight: 600; color: #fff; vertical-align: middle; }
.signed { background: #2e7d32; } .unsigned { background: #757575; }
.review { background: #946000; }
.error { background: #c62828; } .cancelled { background: #9e9e9e; }
.path { color: #666; font-size: .8rem; word-break: break-all; }
.finding { display: flex; gap: 1rem; align-items: center; border-top: 1px solid #eee;
           padding: .6rem 0; }
.finding img { max-height: 90px; max-width: 320px; border: 1px solid #ccc;
               border-radius: 4px; background: #fff; }
.finding img.overview { max-height: 150px; max-width: 120px; }
.meta { color: #444; font-size: .9rem; }
footer { color: #888; font-size: .8rem; margin-top: 2rem; }
"""


def build_html(batch: BatchResult) -> str:
    """Buduje pełny raport HTML z partii wyników."""
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>",
        "<meta http-equiv='Content-Security-Policy' "
        "content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'\">",
        "<title>Signum — raport z analizy podpisów</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>Signum — raport z analizy podpisów</h1>",
        _summary_html(batch),
    ]
    if batch.abort_error:
        parts.append(
            f"<p class='meta' style='color:#c62828'><b>Partię przerwano:</b> "
            f"{html.escape(batch.abort_error)}</p>"
        )
    parts.extend(_document_html(result) for result in batch.results)
    parts.append(
        f"<footer>Wygenerowano {generated} przez Signum {__version__}; "
        f"model: {html.escape(batch.model_name or '—')}. "
        "Signum wykorzystuje AI i może zwrócić wynik błędny lub niepełny. "
        "Wykrywa oznaki obecności podpisów, ale nie potwierdza ich autentyczności, "
        "ważności prawnej lub kryptograficznej ani integralności dokumentu. "
        "Każdy wynik wymaga ręcznej weryfikacji w dokumencie źródłowym i nie "
        "powinien być jedyną podstawą decyzji. Raport może zawierać poufne fragmenty "
        "dokumentów i powinien być chroniony tak samo jak dokumenty źródłowe."
        "</footer></body></html>"
    )
    return "".join(parts)


def _summary_html(batch: BatchResult) -> str:
    total = len(batch.results)
    ok = sum(1 for r in batch.results if r.status == DocumentStatus.OK)
    unsigned = sum(1 for r in batch.results if r.signature_verdict == "NIE")
    return (
        "<div class='summary'>"
        f"<div><b>{total}</b>plików</div>"
        f"<div><b>{batch.signed_count}</b>z podpisami</div>"
        f"<div><b>{unsigned}</b>bez podpisów</div>"
        f"<div><b>{batch.error_count}</b>błędów</div>"
        f"<div><b>{batch.duration_s:.2f}&nbsp;s</b>łącznie</div>"
        f"<div><b>{batch.preparation_s:.2f}&nbsp;s</b>przygotowanie</div>"
        f"<div><b>{batch.loading_s:.2f}&nbsp;s</b>ładowanie modelu</div>"
        f"<div><b>{batch.inference_s:.2f}&nbsp;s</b>działanie modelu</div>"
        f"<div><b>{ok}</b>przetworzonych</div>"
        "</div>"
    )


def _document_html(result: DocumentResult) -> str:
    badge = _badge(result)
    parts = [
        "<div class='doc'>",
        f"<h2>{html.escape(result.title or result.path.name)} {badge}</h2>",
        f"<div class='path'>{html.escape(result.path.name)}</div>",
    ]
    if result.status == DocumentStatus.ERROR and result.error:
        parts.append(f"<p class='meta' style='color:#c62828'>{html.escape(result.error)}</p>")
    if result.hitl:
        parts.append("<p class='meta'><b>Wymaga sprawdzenia przez człowieka (HITL)</b><br>"
                     + html.escape(result.review_summary).replace("\n", "<br>") + "</p>")
    if result.status == DocumentStatus.OK:
        pages_info = f"{result.pages_analyzed}/{result.page_count} stron"
        parts.append(
            f"<div class='meta'>{html.escape(result.path.name)} — przeanalizowano "
            f"{pages_info} w {result.duration_s:.1f} s</div>"
        )
        if result.pages_analyzed < result.page_count:
            parts.append("<p class='meta'>Nie zbadano wszystkich stron dokumentu.</p>")
        if result.page_signature_probabilities:
            scores = "; ".join(
                f"strona {page}: {value * 100:.1f}%"
                for page, value in result.page_signature_probabilities.items()
            )
            parts.append(
                "<p class='meta'>Prawdopodobieństwo obecności podpisu: "
                + html.escape(scores)
                + "</p>"
            )
        for finding in result.findings:
            image_html = ""
            if finding.crop_png:
                b64 = base64.b64encode(finding.crop_png).decode("ascii")
                image_html = f"<img src='data:image/png;base64,{b64}' alt='wycinek podpisu'>"
            overview_html = ""
            if finding.overview_jpeg:
                b64o = base64.b64encode(finding.overview_jpeg).decode("ascii")
                overview_html = (
                    f"<img class='overview' src='data:image/jpeg;base64,{b64o}' "
                    "alt='miniatura strony z zaznaczonym znaleziskiem' "
                    "title='Miejsce znaleziska na stronie'>"
                )
            detail = f" — {html.escape(finding.detail)}" if finding.detail else ""
            parts.append(
                "<div class='finding'>"
                f"{overview_html}{image_html}"
                f"<div class='meta'><b>{html.escape(finding.kind.label_pl)}</b>, "
                f"strona {finding.page}, pewność {finding.confidence}%{detail}</div>"
                "</div>"
            )
        if not result.findings:
            parts.append(f"<div class='meta'>{result.signature_label}.</div>")
    parts.append("</div>")
    return "".join(parts)


def _badge(result: DocumentResult) -> str:
    style = "signed" if result.is_signed else "unsigned"
    if result.hitl:
        style = "review"
    if result.status != DocumentStatus.OK:
        style = "error" if result.status == DocumentStatus.ERROR else "cancelled"
    return f"<span class='badge {style}'>{html.escape(result.signature_label)}</span>"


def write_html(path: Path, batch: BatchResult) -> None:
    path.write_text(build_html(batch), encoding="utf-8")


def write_csv(path: Path, batch: BatchResult) -> None:
    # newline="" wyłącza translację końców linii — CSV ma już CRLF,
    # a write_text zamieniłby je na CRCRLF (puste wiersze w Excelu).
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        handle.write(build_csv(batch))


def build_csv(batch: BatchResult) -> str:
    """CSV z podsumowaniem per plik (separator ``;`` — zgodny z polskim Excelem)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        [
            "plik",
            "tytul",
            "status",
            "podpisany",
            "liczba_podpisow",
            "rodzaje",
            "max_pewnosc",
            "p_podpisu_na_stronach",
            "przeanalizowane_strony",
            "wszystkie_strony",
            "przygotowanie_s", "ladowanie_s", "dzialanie_s", "lacznie_s",
            "hitl", "powody_hitl", "wyniki_decyzyjne", "progi_decyzyjne",
        ]
    )
    for r in batch.results:
        writer.writerow(
            [
                _safe_csv_cell(r.path.name),
                _safe_csv_cell(r.title),
                _STATUS_LABELS[r.status],
                r.signature_verdict,
                "" if r.page_signature_probabilities else len(r.findings),
                r.kinds_summary,
                r.max_confidence if r.max_confidence is not None else "",
                json.dumps(r.page_signature_probabilities)
                if r.page_signature_probabilities
                else "",
                r.pages_analyzed,
                r.page_count,
                r.preparation_s, r.loading_s, r.inference_s, r.duration_s,
                "HITL" if r.hitl else "", _safe_csv_cell(r.review_summary),
                json.dumps(r.page_decision_scores), json.dumps(r.page_decision_thresholds),
            ]
        )
    return buf.getvalue()


def _safe_csv_cell(value: object) -> str:
    """Neutralizuje tekst interpretowany przez arkusze jako formuła."""
    text = str(value)
    stripped = text.lstrip()
    if text.startswith(("\t", "\r", "\n")) or stripped.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text
