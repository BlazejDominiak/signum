"""Tryb wiersza poleceń: ``signum-cli`` — ta sama analiza co w GUI, bez okna.

Przydatny do automatyzacji (zadania wsadowe, skrypty) i do testów end-to-end.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from signum import __version__
from signum.ai import AIError, create_vision_model
from signum.ai.prompts import build_page_prompt
from signum.config import PROVIDERS, AppConfig
from signum.core.discovery import collect_documents
from signum.core.models import DocumentResult, DocumentStatus
from signum.core.pipeline import BatchResult, CancelToken, DocumentAnalyzer, run_batch
from signum.network import processing_is_local
from signum.report import write_csv, write_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signum-cli",
        description="Wykrywa podpisy (odręczne, parafki, pieczątki, cyfrowe) "
        "w dokumentach PDF i skanach.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="pliki i/lub foldery do analizy")
    parser.add_argument("--no-recursive", action="store_true", help="nie schodź do podfolderów")
    parser.add_argument("--html", type=Path, metavar="PLIK", help="zapisz raport HTML")
    parser.add_argument("--csv", type=Path, metavar="PLIK", help="zapisz raport CSV")
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--model", help="nazwa modelu (nadpisuje ustawienia)")
    parser.add_argument(
        "--max-pages", type=_positive_int, metavar="N", help="limit stron na dokument"
    )
    parser.add_argument(
        "--acknowledge-risks",
        action="store_true",
        help="potwierdź uprawnienia, sposób przetwarzania i obowiązek weryfikacji",
    )
    parser.add_argument("--version", action="version", version=f"signum {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = AppConfig.load()
    if args.provider:
        config.provider = args.provider
    if args.model:
        setattr(config, f"{config.provider}_model", args.model)
    if args.max_pages is not None:
        config.max_pages_per_doc = args.max_pages

    files = collect_documents(args.paths, recursive=not args.no_recursive)
    if not files:
        print("Nie znaleziono obsługiwanych dokumentów (PDF/JPG/PNG/TIFF/BMP/WEBP).")
        return 2

    if not args.acknowledge_risks:
        _print_risk_notice(config, len(files))
        print(
            "Aby uruchomić analizę, ponów polecenie z --acknowledge-risks.",
            file=sys.stderr,
        )
        return 2

    try:
        model = create_vision_model(config)
        connection = model.check_connection()
    except (AIError, ValueError) as exc:
        print(f"Usługa AI niedostępna: {exc}", file=sys.stderr)
        if config.provider == "ollama":
            print(
                "Wersja instalowana zawiera Pythona, ale lokalny tryb wymaga "
                "uruchomionej Ollamy i pobranego modelu.",
                file=sys.stderr,
            )
        return 2
    print(f"Model: {model.name}")
    print(f"Połączenie: {connection}")
    print(f"Plików do analizy: {len(files)}\n")

    analyzer = DocumentAnalyzer(
        model=model,
        max_pages=config.max_pages_per_doc,
        image_max_side=config.model_image_max_side,
        prompt=build_page_prompt(config.custom_prompt, config.provider, config.jev_custom_prompt),
    )

    def on_start(index: int, total: int, path: Path) -> None:
        print(f"[{index + 1}/{total}] {path.name} ...", flush=True)

    def on_done(_index: int, result: DocumentResult) -> None:
        print(f"    {_summarize(result)}", flush=True)

    try:
        batch = run_batch(files, analyzer, CancelToken(), on_start, on_done)
    finally:
        analyzer.release_resources()
    _print_summary(batch)

    if args.html:
        write_html(args.html, batch)
        print(f"Raport HTML: {args.html}")
    if args.csv:
        write_csv(args.csv, batch)
        print(f"Raport CSV: {args.csv}")
    return 1 if batch.abort_error else 0


def _summarize(result: DocumentResult) -> str:
    if result.status == DocumentStatus.ERROR:
        return f"BŁĄD: {result.error}"
    if not result.is_signed:
        return f"„{result.title}” — brak podpisów"
    return (
        f"„{result.title}” — PODPISANY: {result.kinds_summary} "
        f"(max pewność {result.max_confidence}%)"
    )


def _print_summary(batch: BatchResult) -> None:
    print(f"\n{'=' * 60}")
    print(
        f"Przetworzono {len(batch.results)} plików w {batch.duration_s:.0f} s — "
        f"z podpisami: {batch.signed_count}, błędy: {batch.error_count}"
    )
    if batch.abort_error:
        print(f"PARTIĘ PRZERWANO: {batch.abort_error}")


def _print_risk_notice(config: AppConfig, file_count: int) -> None:
    local = processing_is_local(config.provider, config.api_base_url)
    transport = (
        "lokalny model AI pod adresem loopback"
        if local
        else "zewnętrzna usługa AI; obrazy stron opuszczą komputer"
    )
    print("OSTRZEŻENIE PRZED ANALIZĄ", file=sys.stderr)
    print(f"- Liczba dokumentów: {file_count}.", file=sys.stderr)
    print(f"- Sposób przetwarzania: {transport}.", file=sys.stderr)
    print("- Musisz mieć prawo do przetwarzania dokumentów.", file=sys.stderr)
    print("- Wyniki AI mogą być błędne i wymagają ręcznej weryfikacji.", file=sys.stderr)
    print(
        "- Raporty zawierają nazwy i dane z dokumentów; HTML osadza również obrazy.",
        file=sys.stderr,
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 500:
        raise argparse.ArgumentTypeError("wartość musi mieścić się w zakresie 1–500")
    return parsed


if __name__ == "__main__":
    sys.exit(main())
