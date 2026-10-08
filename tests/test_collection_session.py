"""Collection recovery and verified operations introduced after the audit."""
import hashlib
import json
import os
import threading
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt

from signum.core.classification import ClassificationBatch, TextDocument
from signum.core.collection_session import load_collection, save_collection, session_path
from signum.core.filing import build_filing_plan, execute_filing
from signum.ui.classification_panel import ClassificationPanel
from tests.test_filing import collection


def test_session_round_trip_omits_text_and_restores_corrections(tmp_path):
    files, batch, _ = collection(tmp_path)
    batch.documents = [TextDocument(files[0], text='sensitive document text')]
    batch.rows[0].category_source = 'user'
    batch.rows[0].model_category = 'Finanse'
    batch.rows[1].excluded = True
    save_collection(files, batch)
    assert 'sensitive document text' not in session_path().read_text(encoding='utf-8')
    restored_files, restored = load_collection()
    assert restored_files == files
    assert restored.rows == batch.rows
    assert not restored.documents


def test_checkpoint_failure_preserves_previous_session(tmp_path, monkeypatch):
    from pathlib import Path
    files, batch, _ = collection(tmp_path)
    save_collection(files, batch)
    previous = session_path().read_bytes()
    monkeypatch.setattr(Path, 'replace', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError):
        save_collection([], ClassificationBatch())
    assert session_path().read_bytes() == previous


def test_correction_and_exclusion_survive_window_restart(qtbot, tmp_path, monkeypatch):
    files, batch, root = collection(tmp_path)
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    panel.files, panel.rows, panel.batch = files, list(batch.rows), batch
    panel._render_collection()
    monkeypatch.setattr('signum.ui.classification_panel.QInputDialog.getItem',
                        lambda *args: ('Finanse', True))
    panel._correct_category(0)
    panel.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    panel._persist_collection()
    other = ClassificationPanel()
    qtbot.addWidget(other)
    assert other.rows[0].category == 'Finanse'
    assert other.rows[0].category_source == 'user'
    assert other.rows[0].model_category == 'Umowy'
    assert other.rows[1].excluded
    plan = build_filing_plan(other.files, other.batch, 'model', 0, root, 'copy')
    assert plan.ready == 1
    assert plan.entries[0].target.parent.name == 'Finanse'


def test_delayed_save_is_bound_to_its_original_config(qtbot, tmp_path, monkeypatch):
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    original = panel._session_path
    monkeypatch.setattr('signum.config.config_dir', lambda: tmp_path / 'other-config')
    panel._persist_collection()
    assert original.exists()
    assert not (tmp_path / 'other-config/collection.json').exists()


def test_added_file_does_not_destroy_previous_results(qtbot, tmp_path):
    files, batch, _ = collection(tmp_path)
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    panel.files, panel.rows, panel.batch = files[:1], batch.rows[:1], batch
    new_file = files[1]
    panel.add_files([new_file])
    assert panel.rows == batch.rows[:1]
    assert panel.batch is batch
    assert panel.table.item(1, 6).text() == 'Oczekuje'


def test_content_hash_rejects_change_even_if_size_and_timestamp_match(tmp_path):
    files, batch, root = collection(tmp_path)
    original = files[0].stat()
    files[0].write_bytes(b'z' * original.st_size)
    os.utime(files[0], ns=(original.st_atime_ns, original.st_mtime_ns))
    plan = build_filing_plan(files[:1], batch, 'model', 0, root, 'move')
    result = execute_filing(plan, threading.Event())
    assert result.errors and not result.completed
    assert files[0].exists()
    assert not plan.entries[0].target.exists()


def test_journal_failure_prevents_move(tmp_path):
    files, batch, root = collection(tmp_path)
    journal = tmp_path / 'blocked'
    journal.write_text('not a directory')
    result = execute_filing(build_filing_plan(files, batch, 'model', 0, root, 'move'),
                            threading.Event(), journal=journal / 'history.jsonl')
    assert not result.completed and len(result.errors) == 2
    assert all(path.exists() for path in files)


def test_journal_records_original_path_and_verified_content(tmp_path):
    files, batch, root = collection(tmp_path)
    journal = tmp_path / 'history.jsonl'
    result = execute_filing(build_filing_plan(files[:1], batch, 'model', 0, root, 'move'),
                            threading.Event(), journal=journal)
    entries = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
    assert [entry['state'] for entry in entries] == ['planned', 'completed']
    assert entries[0]['id'] == entries[1]['id']
    assert entries[1]['source'] == str(files[0])
    copied_hash = hashlib.sha256(result.completed[0].target.read_bytes()).hexdigest()
    assert entries[1]['sha256'] == copied_hash


def test_corrupt_session_cannot_crash_table_or_erase_original(qtbot, tmp_path):
    files, batch, _ = collection(tmp_path)
    save_collection(files, batch)
    data = json.loads(session_path().read_text(encoding='utf-8'))
    data['batch']['rows'][0]['confidence'] = 'broken'
    session_path().write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        load_collection()
    panel = ClassificationPanel()
    qtbot.addWidget(panel)
    assert not panel.files
    assert list(session_path().parent.glob('collection.unreadable-*.json'))
