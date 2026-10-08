"""File operations must preserve originals on conflict, failure and cancellation."""

import hashlib
import threading
from pathlib import Path

import pytest

from signum.core.classification import ClassificationBatch, ClassificationRow, TextDocument
from signum.core.file_identity import fingerprint
from signum.core.filing import build_filing_plan, execute_filing, folder_name


def verified_row(path, model, repeat, category=""):
    return ClassificationRow(path, model, repeat, category,
                             source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             source_fingerprint=fingerprint(path))


def collection(tmp_path):
    files = []
    for directory in ('a', 'b'):
        folder = tmp_path / directory
        folder.mkdir()
        path = folder / 'dokument.pdf'
        path.write_bytes((directory * 100).encode())
        files.append(path)
    batch = ClassificationBatch(
        rows=[verified_row(path, 'model', 0, 'Umowy') for path in files],
        documents=[TextDocument(path) for path in files],
        categories=[('Umowy', ''), ('Finanse', '')], model_labels={'model': 'Model A'},
    )
    root = tmp_path / 'wynik'
    root.mkdir()
    return files, batch, root


@pytest.mark.parametrize('mode', ['copy', 'move'])
def test_filing_preserves_bytes_and_never_overwrites(tmp_path, mode):
    files, batch, root = collection(tmp_path)
    (root / 'Umowy').mkdir()
    existing = root / 'Umowy' / 'dokument.pdf'
    existing.write_bytes(b'existing')
    plan = build_filing_plan(files, batch, 'model', 0, root, mode)
    assert [entry.target.name for entry in plan.entries] == [
        'dokument (2).pdf', 'dokument (3).pdf',
    ]
    result = execute_filing(plan, threading.Event())
    assert len(result.completed) == 2 and not result.errors
    assert existing.read_bytes() == b'existing'
    assert plan.entries[0].target.read_bytes() == b'a' * 100
    assert plan.entries[1].target.read_bytes() == b'b' * 100
    assert all(path.exists() == (mode == 'copy') for path in files)


def test_file_created_after_preview_is_not_overwritten(tmp_path):
    files, batch, root = collection(tmp_path)
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    target = plan.entries[0].target
    target.parent.mkdir()
    target.write_bytes(b'someone else')
    result = execute_filing(plan, threading.Event())
    assert len(result.errors) == 1 and len(result.completed) == 1
    assert target.read_bytes() == b'someone else'
    assert files[0].exists()


def test_changed_source_is_not_moved(tmp_path):
    files, batch, root = collection(tmp_path)
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    files[0].write_bytes(b'updated')
    result = execute_filing(plan, threading.Event())
    assert result.errors and files[0].read_bytes() == b'updated'
    assert not plan.entries[0].target.exists()


def test_failed_copy_keeps_original_and_removes_incomplete_target(tmp_path, monkeypatch):
    import signum.core.filing as filing

    files, batch, root = collection(tmp_path)
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')

    def fail(*args):
        raise OSError('disk error')

    monkeypatch.setattr(filing.os, 'fsync', fail)
    result = execute_filing(plan, threading.Event())
    assert len(result.errors) == 2
    assert all(path.exists() for path in files)
    assert all(not entry.target.exists() for entry in plan.entries)


def test_cancel_mid_copy_removes_partial_copy(tmp_path, monkeypatch):
    import signum.core.filing as filing

    files, batch, root = collection(tmp_path)
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    cancel = threading.Event()
    monkeypatch.setattr(filing.shutil, 'copystat', lambda *args: cancel.set())
    result = execute_filing(plan, cancel)
    assert result.cancelled and not result.completed
    assert all(path.exists() for path in files)
    assert all(not entry.target.exists() for entry in plan.entries)


def test_cancel_between_files_keeps_completed_result(tmp_path):
    files, batch, root = collection(tmp_path)
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    cancel = threading.Event()
    result = execute_filing(plan, cancel, lambda *args: cancel.set())
    assert result.cancelled and len(result.completed) == 1
    assert not files[0].exists() and files[1].exists()


def test_unclassified_errors_unknown_labels_and_missing_files_are_skipped(tmp_path):
    files, batch, root = collection(tmp_path)
    batch.rows[0].error = 'failure'
    batch.rows[1].category = 'Unknown'
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    assert not plan.ready
    assert all(entry.skip for entry in plan.entries)
    batch.rows[0].error = ''
    files[0].unlink()
    plan = build_filing_plan(files, batch, 'model', 0, root, 'copy')
    assert not plan.ready
    plan = build_filing_plan(files, batch, 'other', 0, root, 'copy')
    assert not plan.ready


def test_selected_run_determines_folders_and_duplicates_are_ambiguous(tmp_path):
    files, batch, root = collection(tmp_path)
    batch.rows += [verified_row(path, 'other', 1, 'Finanse') for path in files]
    plan = build_filing_plan(files, batch, 'other', 1, root, 'copy')
    assert all(entry.target.parent.name == 'Finanse' for entry in plan.entries)
    batch.rows.append(verified_row(files[0], 'other', 1, 'Umowy'))
    plan = build_filing_plan(files, batch, 'other', 1, root, 'copy')
    assert plan.entries[0].skip and plan.ready == 1


@pytest.mark.parametrize(('label', 'expected'), [
    ('Umowy i porozumienia', 'Umowy i porozumienia'), ('../Finanse', '.._Finanse'),
    ('CON', '_CON'), ('lpt1.txt', '_lpt1.txt'), (' . ', 'Kategoria'),
    ('Faktury: 2026/10', 'Faktury_ 2026_10'), ('Zażółć', 'Zażółć'),
])
def test_windows_folder_names(label, expected):
    assert folder_name(label) == expected


def test_colliding_sanitized_labels_get_separate_folders(tmp_path):
    files, batch, root = collection(tmp_path)
    batch.categories = [('A/B', ''), ('A:B', '')]
    batch.rows[0].category = 'A/B'
    batch.rows[1].category = 'A:B'
    plan = build_filing_plan(files, batch, 'model', 0, root, 'copy')
    assert [e.target.parent.name for e in plan.entries] == ['A_B', 'A_B (2)']


def test_already_filed_document_is_not_duplicated_or_deleted(tmp_path):
    files, batch, root = collection(tmp_path)
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    result = execute_filing(plan, threading.Event())
    moved = {entry.source: entry.target for entry in result.completed}
    for row in batch.rows:
        row.path = moved[row.path]
        row.source_fingerprint = fingerprint(row.path)
    plan = build_filing_plan(list(moved.values()), batch, 'model', 0, root, 'move')
    assert not plan.ready and all(entry.source.exists() for entry in plan.entries)


def test_folder_symlink_cannot_redirect_output(tmp_path):
    files, batch, root = collection(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (root / 'Umowy').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Creating symlinks requires privileges on this Windows installation')
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    assert not plan.ready
    assert not list(outside.iterdir())


@pytest.mark.parametrize('mode', ['copy', 'move'])
def test_dialog_worker_and_updated_document_paths(qtbot, isolated_config, tmp_path, mode):
    from PySide6.QtCore import Qt

    from signum.ui.filing_dialog import FilingDialog
    from signum.ui.main_window import MainWindow

    files, batch, root = collection(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    panel = window.classification
    panel.add_files(files)
    window._add_documents(files)
    panel.table.setRowCount(0)
    for row in batch.rows:
        panel._row_done(row)
    panel._batch_done(batch)
    panel._finished()
    assert panel.copy_button.isEnabled() and panel.move_button.isEnabled()
    dialog = FilingDialog(list(panel.files), batch, mode, panel)
    qtbot.addWidget(dialog)
    dialog.filed.connect(lambda result: panel._apply_filing_result(result, mode))
    dialog.busy_changed.connect(panel._filing_state_changed)
    dialog.destination.setText(str(root))
    dialog.refresh_plan()
    assert dialog.plan.ready == 2
    dialog._execute()
    assert panel.is_busy() and not panel.copy_button.isEnabled()
    qtbot.waitUntil(lambda: dialog.worker is None, timeout=10000)
    assert not panel.is_busy() and dialog.outcome is not None
    assert len(dialog.outcome.completed) == 2
    assert all(path.exists() for path in panel.files)
    assert window._files == panel.files
    assert batch.documents[0].path == panel.files[0]
    assert Path(panel.table.item(0, 0).data(Qt.ItemDataRole.UserRole)) == panel.files[0]
    if mode == 'move':
        assert all(path.parent == root / 'Umowy' for path in panel.files)
    else:
        assert panel.files == files
    panel.clear()
    assert not panel.copy_button.isEnabled() and not panel.move_button.isEnabled()


def test_comparison_requires_explicit_run_selection(qtbot, tmp_path):
    from signum.ui.filing_dialog import FilingDialog

    files, batch, root = collection(tmp_path)
    batch.rows.append(verified_row(files[0], 'second', 0, 'Finanse'))
    dialog = FilingDialog(files, batch, 'copy')
    qtbot.addWidget(dialog)
    dialog.destination.setText(str(root))
    dialog.refresh_plan()
    assert dialog.plan is None and not dialog.execute_button.isEnabled()
    dialog.run_choice.setCurrentIndex(2)
    assert dialog.plan.ready == 1
    assert dialog.plan.entries[0].target.parent.name == 'Finanse'


def test_windows_junction_cannot_redirect_preview_or_execution(tmp_path):
    import sys

    if sys.platform != 'win32':
        pytest.skip('Windows junction test')
    import _winapi

    files, batch, root = collection(tmp_path)
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    outside = tmp_path / 'outside'
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(root / 'Umowy'))
    try:
        result = execute_filing(plan, threading.Event())
        assert len(result.errors) == 2 and not result.completed
        assert all(path.exists() for path in files)
        assert not list(outside.iterdir())
        preview = build_filing_plan(files, batch, 'model', 0, root, 'move')
        assert not preview.ready
    finally:
        (root / 'Umowy').rmdir()


def test_failed_source_removal_rolls_back_copy(tmp_path, monkeypatch):
    files, batch, root = collection(tmp_path)
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    unlink = Path.unlink

    def locked(path, *args, **kwargs):
        if path in files:
            raise PermissionError('Source locked')
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', locked)
    result = execute_filing(plan, threading.Event())
    assert len(result.errors) == 2
    assert all(path.exists() for path in files)
    assert all(not entry.target.exists() for entry in plan.entries)


def test_corrupted_copy_never_deletes_source(tmp_path, monkeypatch):
    import signum.core.filing as filing

    files, batch, root = collection(tmp_path)
    plan = build_filing_plan(files, batch, 'model', 0, root, 'move')
    real_digest = filing.hashlib.file_digest

    def corrupt(handle, algorithm):
        return filing.hashlib.sha256(b'corruption')

    monkeypatch.setattr(filing.hashlib, 'file_digest', corrupt)
    result = execute_filing(plan, threading.Event())
    monkeypatch.setattr(filing.hashlib, 'file_digest', real_digest)
    assert len(result.errors) == 2
    assert all(path.exists() for path in files)
    assert all(not entry.target.exists() for entry in plan.entries)


def test_closing_active_dialog_cancels_without_destroying_worker(qtbot, tmp_path, monkeypatch):
    import signum.core.filing as filing
    from signum.ui.filing_dialog import FilingDialog

    files, batch, root = collection(tmp_path)
    entered = threading.Event()
    resume = threading.Event()
    original = filing._copy_verified

    def slow(*args):
        entered.set()
        resume.wait(5)
        return original(*args)

    monkeypatch.setattr(filing, '_copy_verified', slow)
    dialog = FilingDialog(files, batch, 'move')
    qtbot.addWidget(dialog)
    dialog.destination.setText(str(root))
    dialog.refresh_plan()
    dialog.show()
    dialog._execute()
    qtbot.waitUntil(entered.is_set)
    dialog.close()
    assert dialog.isVisible() and dialog.worker is not None
    resume.set()
    qtbot.waitUntil(lambda: dialog.worker is None, timeout=10000)
    assert dialog.outcome.cancelled
    assert all(path.exists() for path in files)
    dialog.close()
    assert not dialog.isVisible()
