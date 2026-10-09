"""Regressions for retaining signature runs and comparing their measured results."""
from __future__ import annotations

import csv
import io
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtWidgets import QDialog, QMessageBox

from signum.ai.base import AIConnectionError, PageAnalysis, VisionModel
from signum.config import AppConfig
from signum.core.models import DocumentResult, DocumentStatus, SignatureFinding, SignatureKind
from signum.core.pipeline import BatchResult
from signum.report import build_csv, build_html
from signum.ui.main_window import MainWindow
from signum.ui.worker import SignatureComparisonWorker


def _runs() -> list[BatchResult]:
    first = DocumentResult(
        Path('private/one/same.pdf'), status=DocumentStatus.OK, page_count=1, pages_analyzed=1,
        preparation_s=1, loading_s=2, inference_s=3, duration_s=6,
        findings=[SignatureFinding(SignatureKind.HANDWRITTEN, 1, 90)],
    )
    second = replace(first, findings=[], inference_s=7, duration_s=10,
                     page_review_reasons={1: ['Blisko progu']})
    return [
        BatchResult(results=[first], model_name='Gemma', started_at=100, finished_at=111,
                    preparation_s=1, loading_s=5, inference_s=3, preflight_s=1),
        BatchResult(results=[second], model_name='Jev', started_at=200, finished_at=215,
                    preparation_s=1, loading_s=6, inference_s=7, preflight_s=1),
    ]


def test_report_compares_models_and_preserves_document_and_model_timings() -> None:
    runs = _runs()
    rows = list(csv.DictReader(io.StringIO(build_csv(runs)), delimiter=';'))
    assert [r['model'] for r in rows] == ['Gemma', 'Jev']
    assert [r['podpisany'] for r in rows] == ['TAK', 'NIE']
    assert [r['dzialanie_s'] for r in rows] == ['3', '7']
    assert [r['model_ladowanie_s'] for r in rows] == ['5', '6']
    assert [r['model_lacznie_s'] for r in rows] == ['11', '15']
    assert all(r['suma_przebiegow_s'] == '26' for r in rows)
    assert all(r['zgodnosc_modeli'] == 'RÓŻNICA' for r in rows)
    assert rows[1]['hitl'] == 'HITL'
    report = build_html(runs)
    assert 'Czasy i wyniki modeli' in report
    assert 'Porównanie wyników dokument po dokumencie' in report
    assert 'Gemma' in report and 'Jev' in report
    assert '11.000' in report and '15.000' in report and '26.000' in report
    assert "class='different'" in report and 'Blisko progu' in report
    assert 'private/' not in report


@pytest.mark.parametrize('state', ['missing', 'error', 'cancelled', 'partial'])
def test_missing_or_incomplete_results_are_never_agreement(state: str) -> None:
    runs = _runs()
    if state == 'missing':
        runs[1].results.clear()
    elif state == 'partial':
        runs[1].results[0].page_count = 2
    else:
        runs[1].results[0].status = DocumentStatus(state)
    rows = list(csv.DictReader(io.StringIO(build_csv(runs)), delimiter=';'))
    assert all(r['zgodnosc_modeli'] == 'NIEPEŁNE DANE' for r in rows)
    assert 'NIEPEŁNE DANE' in build_html(runs)


def test_same_names_in_different_directories_are_not_matched() -> None:
    runs = _runs()
    runs[1].results[0].path = Path('private/two/same.pdf')
    runs[1].model_name = '=FORMULA <script>'
    rows = list(csv.DictReader(io.StringIO(build_csv(runs)), delimiter=';'))
    assert [r['dokument_id'] for r in rows] == ['1', '2']
    assert all(r['zgodnosc_modeli'] == 'NIEPEŁNE DANE' for r in rows)
    assert rows[1]['model'].startswith("'")
    assert '<script>' not in build_html(runs)


class _Model(VisionModel):
    def __init__(self, provider: str, events: list[str], fail: bool = False):
        self.provider = provider
        self.events = events
        self.fail = fail

    @property
    def name(self) -> str:
        return self.provider

    def check_connection(self) -> str:
        self.events.append('check ' + self.provider)
        if self.fail:
            raise AIConnectionError('offline')
        return 'OK'

    def _generate(self, image_jpeg: bytes, prompt: str) -> str:
        raise AssertionError('unused')

    def analyze_page(self, image_jpeg: bytes, prompt: str | None = None) -> PageAnalysis:
        self.events.append('analyze ' + self.provider)
        return PageAnalysis('', ())

    def release_resources(self) -> None:
        self.events.append('release ' + self.provider)


def test_comparison_button_runs_two_models_and_exports_both(qtbot, monkeypatch, tmp_path):
    import signum.ui.main_window as ui
    import signum.ui.worker as worker_module

    events = []
    monkeypatch.setattr(
        worker_module, 'create_vision_model', lambda cfg: _Model(cfg.provider, events),
    )
    monkeypatch.setattr(ui.BatchRiskDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    source = tmp_path / 'scan.png'
    Image.new('RGB', (4, 4), 'white').save(source)
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_documents([source])
    window.act_compare.trigger()
    qtbot.waitUntil(lambda: window._worker is None, timeout=5000)
    assert events == ['check ollama', 'analyze ollama', 'release ollama',
                      'check vjev', 'analyze vjev', 'release vjev']
    assert len(window._signature_runs) == 2
    assert window.signature_runs.count() == 2
    window.signature_runs.setCurrentIndex(0)
    assert window._last_batch.model_name == 'ollama'
    assert window.table.item(0, 2).text() == 'BRAK PODPISU'
    target = tmp_path / 'comparison.csv'
    monkeypatch.setattr(ui.QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ui.QFileDialog, 'getSaveFileName', lambda *args: (str(target), 'CSV'))
    window._on_export()
    rows = list(csv.DictReader(io.StringIO(target.read_text(encoding='utf-8-sig')), delimiter=';'))
    assert [r['model'] for r in rows] == ['ollama', 'vjev']
    assert all(r['zgodnosc_modeli'] == 'ZGODNE' for r in rows)
    window._on_clear()
    assert not window._signature_runs and window.signature_runs.count() == 0


@pytest.mark.parametrize('stop', ['error', 'cancel'])
def test_failure_or_cancel_keeps_partial_comparison(qapp, monkeypatch, tmp_path, stop):
    import signum.ui.worker as worker_module

    events = []
    monkeypatch.setattr(worker_module, 'create_vision_model', lambda cfg: _Model(
        cfg.provider, events, fail=stop == 'error' and cfg.provider == 'ollama',
    ))
    source = tmp_path / 'scan.png'
    Image.new('RGB', (4, 4), 'white').save(source)
    worker = SignatureComparisonWorker(
        [source], [AppConfig(provider=p) for p in ('ollama', 'vjev')],
    )
    batches = []

    def collect(batch):
        batches.append(batch)
        if stop == 'cancel':
            worker.cancel()

    worker.batch_done.connect(collect)
    worker.run()
    assert len(batches) == 2
    if stop == 'error':
        assert batches[0].abort_error == 'offline'
        assert batches[0].results[0].status == DocumentStatus.ERROR
        assert batches[1].results[0].status == DocumentStatus.OK
        assert events.index('release ollama') < events.index('check vjev')
    else:
        assert batches[1].results[0].status == DocumentStatus.CANCELLED
        assert 'check vjev' not in events
    assert 'NIEPEŁNE DANE' in build_html(batches)
