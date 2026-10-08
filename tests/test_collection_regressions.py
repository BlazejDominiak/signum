"""Audit regressions for collection. Services and files are isolated."""
import hashlib
import threading

import pytest

from signum.core.classification import ClassificationBatch, ClassificationRow, TextDocument
from signum.core.file_identity import fingerprint
from signum.core.filing import build_filing_plan, execute_filing
from signum.ui.classification_panel import ClassificationPanel


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr('signum.config.config_file', lambda: tmp_path / 'settings.json')
    monkeypatch.setattr('signum.config.config_dir', lambda: tmp_path)
    monkeypatch.setattr('signum.config.get_api_key', lambda _: '')


@pytest.mark.parametrize('action', ['cancel_picker', 'duplicate'])
def test_non_mutating_add_keeps_completed_results(qtbot, tmp_path, monkeypatch, action):
    path = tmp_path / 'document.pdf'
    path.write_bytes(b'old pdf')
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    panel.add_files([path])
    row = ClassificationRow(path, 'gemma', 0, category='Contract')
    panel._row_done(row)
    batch = ClassificationBatch(rows=[row], categories=[('Contract', ''), ('Invoice', '')])
    panel._batch_done(batch)
    panel._set_busy(False)
    if action == 'cancel_picker':
        monkeypatch.setattr('signum.ui.classification_panel.QFileDialog.getOpenFileNames',
                            lambda *args: ([], ''))
        panel._add_dialog()
    else:
        panel.add_files([path])
    assert panel.batch is batch, 'Existing classifications disappeared without adding any file'


def test_filing_rejects_a_document_changed_since_classification(tmp_path):
    path = tmp_path / 'document.pdf'
    path.write_bytes(b'contract version')
    row = ClassificationRow(path, 'm', 0, category='Contract',
                            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            source_fingerprint=fingerprint(path))
    batch = ClassificationBatch(rows=[row], categories=[('Contract', ''), ('Invoice', '')],
                                documents=[TextDocument(path, text='contract version')])
    # A different document replaces the classified one before the filing preview.
    path.write_bytes(b'invoice version after classification')
    target = tmp_path / 'output'
    target.mkdir()
    plan = build_filing_plan([path], batch, 'm', 0, target, 'move')
    outcome = execute_filing(plan, threading.Event())
    assert not outcome.completed, 'New content was moved using the old document label'
