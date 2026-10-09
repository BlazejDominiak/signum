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
from collections.abc import Sequence
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
.table-wrap { overflow-x: auto; margin: 1rem 0 2rem; }
table { border-collapse: collapse; width: 100%; background: white; }
th, td { text-align: left; vertical-align: top; padding: .6rem; border: 1px solid #ddd; }
th { background: #eef2f7; }
.different { background: #fff0d3; }
footer { color: #888; font-size: .8rem; margin-top: 2rem; }
"""


def build_html(batch: BatchResult | Sequence[BatchResult]) -> str:
    """Buduje pełny raport HTML z partii wyników."""
    runs = _runs(batch)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        "<!DOCTYPE html><html lang='pl'><head><meta charset='utf-8'>",
        "<meta http-equiv='Content-Security-Policy' "
        "content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'\">",
        "<title>Signum — raport z analizy podpisów</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>Signum — raport z analizy podpisów</h1>",
        _timings_html(runs),
        _comparison_html(runs),
    ]
    for index, run in enumerate(runs, 1):
        parts.append(f"<h2>Przebieg {index}: {html.escape(run.model_name or '—')}</h2>")
        parts.append(_summary_html(run))
        if run.abort_error:
            parts.append(
                "<p class='meta error'><b>Partię przerwano:</b> "
                + html.escape(run.abort_error) + "</p>"
            )
        parts.extend(_document_html(result) for result in run.results)
    parts.append(
        f"<footer>Wygenerowano {generated} przez Signum {__version__}; "
        f"modele: {html.escape(', '.join(r.model_name or '—' for r in runs))}. "
        "Signum wykorzystuje AI i może zwrócić wynik błędny lub niepełny. "
        "Wykrywa oznaki obecności podpisów, ale nie potwierdza ich autentyczności, "
        "ważności prawnej lub kryptograficznej ani integralności dokumentu. "
        "Każdy wynik wymaga ręcznej weryfikacji w dokumencie źródłowym i nie "
        "powinien być jedyną podstawą decyzji. Raport może zawierać poufne fragmenty "
        "dokumentów i powinien być chroniony tak samo jak dokumenty źródłowe."
        "</footer></body></html>"
    )
    return "".join(parts)


def _runs(batch: BatchResult | Sequence[BatchResult]) -> list[BatchResult]:
    return [batch] if isinstance(batch, BatchResult) else list(batch)


def _documents(runs: Sequence[BatchResult]) -> dict[Path, list[DocumentResult | None]]:
    documents: dict[Path, list[DocumentResult | None]] = {}
    for index, run in enumerate(runs):
        for result in run.results:
            documents.setdefault(result.path, [None] * len(runs))[index] = result
    return documents


def _agreement(results: Sequence[DocumentResult | None]) -> str:
    if len(results) < 2:
        return ""
    if any(result is None or not result.analysis_complete for result in results):
        return "NIEPEŁNE DANE"
    if len({result.page_count for result in results if result is not None}) != 1:
        return "RÓŻNY ZAKRES STRON"
    verdicts = {result.signature_verdict for result in results if result is not None}
    return "ZGODNE" if len(verdicts) == 1 else "RÓŻNICA"


def _timings_html(runs: Sequence[BatchResult]) -> str:
    parts = ["<h2>Czasy i wyniki modeli</h2><div class='table-wrap'><table><thead><tr>"]
    headings = (
        "Przebieg / model", "Ustawienia analizy", "Dokumenty OK / wszystkie",
        "Podpisane", "HITL", "Błędy",
        "Przygotowanie [s]", "Ładowanie [s]", "Działanie [s]", "Test połączenia [s]",
        "Łącznie [s]", "Średnie działanie / przetworzony plik [s]",
    )
    parts.extend(f"<th>{heading}</th>" for heading in headings)
    parts.append("</tr></thead><tbody>")
    for index, run in enumerate(runs, 1):
        ok = sum(r.status == DocumentStatus.OK for r in run.results)
        processed = sum(r.status in {DocumentStatus.OK, DocumentStatus.ERROR} for r in run.results)
        average = f"{run.inference_s / processed:.3f}" if processed else "—"
        values = (
            f"{index}. {run.model_name}", run.analysis_settings, f"{ok} / {len(run.results)}",
            str(run.signed_count),
            str(sum(r.hitl for r in run.results)), str(run.error_count),
            f"{run.preparation_s:.3f}", f"{run.loading_s:.3f}", f"{run.inference_s:.3f}",
            f"{run.preflight_s:.3f}", f"{run.duration_s:.3f}", average,
        )
        parts.append("<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in values) + "</tr>")
    parts.append(
        "</tbody></table></div><p class='meta'>Suma czasów przebiegów: "
        f"{sum(r.duration_s for r in runs):.3f} s. "
        "Czas łączny obejmuje przygotowanie, ładowanie, test połączenia, "
        "działanie i zwolnienie zasobów. Ładowanie w teście połączenia jest wliczone "
        "wyłącznie do kolumny Ładowanie. Czas działania obejmuje żądania i ponowienia; "
        "dla usług zdalnych obejmuje też transport. "
        "Średnia pomija pliki anulowane. Porównuj czasy przy tym samym zakresie analizy.</p>"
    )
    return "".join(parts)


def _comparison_html(runs: Sequence[BatchResult]) -> str:
    if len(runs) < 2:
        return ""
    parts = ["<h2>Porównanie wyników dokument po dokumencie</h2>",
             "<div class='table-wrap'><table><thead><tr><th>Dokument</th>"]
    parts.extend(f"<th>{i}. {html.escape(run.model_name)}</th>"
                 for i, run in enumerate(runs, 1))
    parts.append("<th>Zgodność obecności podpisu</th></tr></thead><tbody>")
    for index, (path, results) in enumerate(_documents(runs).items(), 1):
        agreement = _agreement(results)
        style = " class='different'" if agreement == "RÓŻNICA" else ""
        parts.append(f"<tr{style}><td>{index}. {html.escape(path.name)}</td>")
        for result in results:
            if result is None:
                parts.append("<td>BRAK WYNIKU</td>")
            else:
                parts.append(
                    f"<td>{_badge(result)}<br>Działanie: {result.inference_s:.3f} s"
                    f"<br>Łącznie: {result.duration_s:.3f} s"
                    f"<br>Strony: {result.pages_analyzed}/{result.page_count}</td>"
                )
        parts.append(f"<td>{agreement}</td></tr>")
    parts.append(
        "</tbody></table></div><p class='meta'>Zgodność dotyczy obecności podpisu. "
        "Błędy, brak wyniku i niepełna analiza nie są liczone jako zgodność. "
        "HITL pozostaje widoczny niezależnie od zgodności modeli.</p>"
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
    parts.append(
        "<p class='meta'>"
        f"Przygotowanie: {result.preparation_s:.3f} s · "
        f"Ładowanie: {result.loading_s:.3f} s · "
        f"Działanie: {result.inference_s:.3f} s · Łącznie: {result.duration_s:.3f} s</p>"
    )
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


def write_html(path: Path, batch: BatchResult | Sequence[BatchResult]) -> None:
    path.write_text(build_html(batch), encoding="utf-8")


def write_csv(path: Path, batch: BatchResult | Sequence[BatchResult]) -> None:
    # newline="" wyłącza translację końców linii — CSV ma już CRLF,
    # a write_text zamieniłby je na CRCRLF (puste wiersze w Excelu).
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        handle.write(build_csv(batch))


def build_csv(batch: BatchResult | Sequence[BatchResult]) -> str:
    """CSV z podsumowaniem per plik (separator ``;`` — zgodny z polskim Excelem)."""
    runs = _runs(batch)
    documents = _documents(runs)
    document_ids = {path: i for i, path in enumerate(documents, 1)}
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
            "model", "przebieg", "dokument_id", "zgodnosc_modeli", "blad",
            "model_przygotowanie_s", "model_ladowanie_s", "model_dzialanie_s",
            "model_test_polaczenia_s", "model_lacznie_s", "suma_przebiegow_s",
            "blad_przebiegu", "ustawienia_analizy",
        ]
    )
    for index, run in enumerate(runs, 1):
        for r in run.results:
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
                    _safe_csv_cell(run.model_name), index, document_ids[r.path],
                    _agreement(documents[r.path]), _safe_csv_cell(r.error or ""),
                    run.preparation_s, run.loading_s, run.inference_s, run.preflight_s,
                    run.duration_s, sum(b.duration_s for b in runs),
                    _safe_csv_cell(run.abort_error or ""), _safe_csv_cell(run.analysis_settings),
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
