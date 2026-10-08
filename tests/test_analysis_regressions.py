"""Audit regressions for analysis. Services and files are isolated."""
import csv
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from signum.config import AppConfig
from signum.core.digital import scan_digital_signatures
from signum.core.models import DocumentResult, DocumentStatus
from signum.core.pipeline import BatchResult
from signum.report.export import build_csv, build_html
from signum.ui.worker import BatchWorker


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr('signum.config.config_file', lambda: tmp_path / 'settings.json')
    monkeypatch.setattr('signum.config.config_dir', lambda: tmp_path)
    monkeypatch.setattr('signum.config.get_api_key', lambda _: '')


def test_partial_signature_report_does_not_claim_whole_document_unsigned():
    result = DocumentResult(Path('twelve-pages.pdf'), status=DocumentStatus.OK,
                            page_count=12, pages_analyzed=10)
    batch = BatchResult(results=[result])
    row = next(csv.DictReader(io.StringIO(build_csv(batch)), delimiter=';'))
    assert row['podpisany'] != 'NIE', '10 of 12 pages inspected, CSV states NIE'
    assert "class='badge unsigned'>BRAK PODPISU" not in build_html(batch)


def test_empty_signature_value_is_not_an_actual_signature(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    field = DictionaryObject({NameObject('/FT'): NameObject('/Sig'),
                              NameObject('/T'): TextStringObject('Pending signature'),
                              NameObject('/V'): DictionaryObject()})
    ref = writer._add_object(field)
    writer._root_object[NameObject('/AcroForm')] = DictionaryObject(
        {NameObject('/Fields'): ArrayObject([ref])})
    path = tmp_path / 'unsigned.pdf'
    with path.open('wb') as stream:
        writer.write(stream)
    scan = scan_digital_signatures(path)
    assert not scan.signatures, 'An empty /V dictionary is counted as a digital signature'


def test_unexpected_later_error_preserves_completed_batch_results(tmp_path):
    first = DocumentResult(tmp_path / 'first.pdf', status=DocumentStatus.OK)
    analyzer = Mock()
    analyzer.model_name = 'test'
    analyzer.analyze.side_effect = [first, ValueError('invalid load_duration')]
    worker = BatchWorker([first.path, tmp_path / 'second.pdf'], analyzer)
    completed = []
    worker.batch_done.connect(completed.append)
    worker.run()
    assert first in completed[0].results, 'Fallback result discarded the completed first document'


def test_cli_does_not_describe_an_ollama_cloud_model_as_local(capsys):
    from signum.cli import _print_risk_notice
    _print_risk_notice(AppConfig(provider='ollama', ollama_model='gemma4:cloud'), 1)
    notice = capsys.readouterr().err
    assert 'zewnętrzna usługa AI' in notice, 'CLI says local for a cloud-backed Ollama model'
