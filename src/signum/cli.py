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
from signum.config import PROVIDERS, AppConfig, signature_settings
from signum.core.discovery import collect_documents
from signum.core.models import DocumentResult, DocumentStatus
from signum.core.pipeline import BatchResult, CancelToken, DocumentAnalyzer, run_batch
from signum.i18n import set_language, tr
from signum.network import processing_is_local
from signum.report import write_csv, write_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signum-cli",
        description=tr("core.cli.detects_signatures_handwritten_initials_stamps_digital_in"),
    )
    parser.add_argument("paths", nargs="+", type=Path, help=tr("cli.paths"))
    parser.add_argument(
        "--no-recursive", action="store_true", help=tr("core.cli.do_not_scan_subfolders")
    )
    parser.add_argument("--html", type=Path, metavar=tr("cli.file"), help=tr("cli.html"))
    parser.add_argument("--csv", type=Path, metavar=tr("cli.file"), help=tr("cli.csv"))
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--model", help=tr("cli.model"))
    parser.add_argument(
        "--additional-analysis",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=tr("core.cli.descriptions_categories_and_crops_for_ollama_or"),
    )
    parser.add_argument("--max-pages", type=_positive_int, metavar="N", help=tr("cli.pages"))
    parser.add_argument(
        "--acknowledge-risks",
        action="store_true",
        help=tr("core.cli.acknowledge_permissions_processing_method_and_the_need"),
    )
    parser.add_argument("--version", action="version", version=f"signum {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    config = AppConfig.load()
    set_language(config.language)
    args = build_parser().parse_args(argv)
    if args.provider:
        config.provider = args.provider
    if args.model:
        setattr(config, f"{config.provider}_model", args.model)
    if args.max_pages is not None:
        config.max_pages_per_doc = args.max_pages
    if args.additional_analysis is not None:
        if config.provider not in {"ollama", "vjev"}:
            print(
                tr("core.cli.the_additional_analysis_option_supports_ollama_and"), file=sys.stderr
            )
            return 2
        setattr(config, f"{config.provider}_additional_analysis", args.additional_analysis)

    files = collect_documents(args.paths, recursive=not args.no_recursive)
    if not files:
        print(tr("core.cli.no_supported_documents_found_pdf_jpg_png"))
        return 2

    if not args.acknowledge_risks:
        _print_risk_notice(config, len(files))
        print(
            tr("core.cli.to_start_the_analysis_repeat_the_command"),
            file=sys.stderr,
        )
        return 2

    try:
        model = create_vision_model(config)
        connection = model.check_connection()
    except (AIError, ValueError) as exc:
        print(tr("core.cli.ai_service_unavailable", exc=exc), file=sys.stderr)
        if config.provider == "ollama":
            print(
                tr("cli.local_requirements"),
                file=sys.stderr,
            )
        return 2
    print(tr("core.cli.model", value0=model.name))
    print(tr("core.cli.connection", connection=connection))
    print(tr("core.cli.files_to_analyze", value0=len(files)))

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
    batch.analysis_settings = signature_settings(config)
    _print_summary(batch)

    if args.html:
        write_html(args.html, batch)
        print(tr("core.cli.html_report", value0=args.html))
    if args.csv:
        write_csv(args.csv, batch)
        print(tr("core.cli.csv_report", value0=args.csv))
    return 1 if batch.abort_error or batch.error_count else 0


def _summarize(result: DocumentResult) -> str:
    if result.status == DocumentStatus.ERROR:
        return tr("core.cli.error", value0=result.error)
    if not result.is_signed:
        return f"„{result.title}” — {result.signature_label}"
    return tr(
        "core.cli.signed_max_confidence",
        value0=result.title,
        value1=result.kinds_summary,
        value2=result.max_confidence,
    ) + (f" · {result.review_summary}" if result.hitl else "")


def _print_summary(batch: BatchResult) -> None:
    print(f"\n{'=' * 60}")
    print(
        tr(
            "core.cli.processed_files_in_s_signed_errors",
            value0=len(batch.results),
            value1=batch.duration_s,
            value2=batch.signed_count,
            value3=batch.error_count,
        )
    )
    if batch.abort_error:
        print(tr("core.cli.batch_aborted", value0=batch.abort_error))


def _print_risk_notice(config: AppConfig, file_count: int) -> None:
    local = processing_is_local(config.provider, config.api_base_url, config.ollama_model)
    transport = (
        tr("cli.local_ai") if local else tr("core.cli.external_ai_service_page_images_will_leave")
    )
    print(tr("core.cli.pre_analysis_notice"), file=sys.stderr)
    print(tr("core.cli.number_of_documents", file_count=file_count), file=sys.stderr)
    print(tr("core.cli.processing_method", transport=transport), file=sys.stderr)
    print(tr("core.cli.you_must_have_the_right_to_process"), file=sys.stderr)
    print(tr("core.cli.ai_results_may_be_incorrect_and_require"), file=sys.stderr)
    print(
        tr("core.cli.reports_contain_names_and_data_from_documents"),
        file=sys.stderr,
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 500:
        raise argparse.ArgumentTypeError(tr("core.cli.value_must_be_in_the_1_500"))
    return parsed


if __name__ == "__main__":
    sys.exit(main())
