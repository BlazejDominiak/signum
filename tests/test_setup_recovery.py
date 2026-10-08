"""Installation retries, headless mode and partial download integrity."""
import hashlib
import json
import threading
from unittest.mock import MagicMock, Mock

import pytest

from signum.setup_local_ai import LocalAIPreparer, perform_setup, run_setup_dialog


def response(data, status=200, **headers):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    result.headers = {'Content-Length': str(len(data)), **headers}
    result.iter_content.return_value = [data]
    return result


def test_range_resume_requests_only_missing_bytes(tmp_path):
    payload = b'abcdef'
    target = tmp_path / 'model'
    target.with_suffix('.part').write_bytes(payload[:3])
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.session.get = Mock(return_value=response(payload[3:], 206,
                                                     **{'Content-Range': 'bytes 3-5/6'}))
    preparer.download('https://example.invalid/model', target, hashlib.sha256(payload).hexdigest())
    assert preparer.session.get.call_args.kwargs['headers']['Range'] == 'bytes=3-'
    assert target.read_bytes() == payload


def test_ignored_range_replaces_partial_instead_of_appending(tmp_path):
    payload = b'abcdef'
    target = tmp_path / 'model'
    target.with_suffix('.part').write_bytes(b'bad prefix')
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.session.get = Mock(return_value=response(payload))
    preparer.download('https://example.invalid/model', target, hashlib.sha256(payload).hexdigest())
    assert target.read_bytes() == payload


def test_invalid_range_does_not_publish_file(tmp_path):
    target = tmp_path / 'model'
    target.with_suffix('.part').write_bytes(b'abc')
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.session.get = Mock(return_value=response(b'def', 206,
                                                     **{'Content-Range': 'bytes 0-2/3'}))
    with pytest.raises(ValueError, match='zakres'):
        preparer.download('https://example.invalid/model', target, 'a' * 64)
    assert not target.exists()
    assert target.with_suffix('.part').read_bytes() == b'abc'


def test_corrupt_resumed_download_is_discarded(tmp_path):
    target = tmp_path / 'model'
    target.with_suffix('.part').write_bytes(b'bad')
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.session.get = Mock(return_value=response(b'def', 206,
                                                     **{'Content-Range': 'bytes 3-5/6'}))
    with pytest.raises(ValueError, match='suma kontrolna'):
        preparer.download('https://example.invalid/model', target,
                         hashlib.sha256(b'abcdef').hexdigest())
    assert not target.exists() and not target.with_suffix('.part').exists()


def test_retry_runs_only_failed_components(tmp_path, monkeypatch):
    monkeypatch.setattr('signum.setup_local_ai.find_ollama', lambda config: '')
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.prepare_ollama = Mock()
    preparer.prepare_jevk5 = Mock(side_effect=[RuntimeError('test failure'), None])
    components = {'ollama', 'jevk5'}
    assert not perform_setup(preparer, components)[0]
    result = json.loads((tmp_path / 'setup-result.json').read_text(encoding='utf-8'))
    assert result['components']['ollama'] == 'ready'
    assert result['components']['jevk5'] != 'ready'
    assert perform_setup(preparer, components)[0]
    assert preparer.prepare_ollama.call_count == 1
    assert preparer.prepare_jevk5.call_count == 2


@pytest.mark.parametrize('failed', [False, True])
def test_headless_returns_without_creating_a_dialog(tmp_path, monkeypatch, failed):
    dialog = Mock(side_effect=AssertionError('GUI created'))
    monkeypatch.setattr('PySide6.QtWidgets.QDialog', dialog)
    monkeypatch.setattr(LocalAIPreparer, 'prepare',
                        Mock(side_effect=RuntimeError('offline') if failed else None))
    result_path = tmp_path / 'result.json'
    exit_code = run_setup_dialog(['--setup-local-ai', '--headless', '--ai-components', 'app',
                                 '--ai-directory', str(tmp_path),
                                 '--result-file', str(result_path)])
    assert exit_code == (1 if failed else 0)
    assert json.loads(result_path.read_text(encoding='utf-8'))['success'] is not failed


def test_headless_creation_failure_writes_report_outside_broken_storage(tmp_path):
    blocked = tmp_path / 'file-not-folder'
    blocked.write_text('existing file')
    result = tmp_path / 'state/result.json'
    code = run_setup_dialog(['--setup-local-ai', '--headless', '--ai-components', 'ollama',
                             '--ai-directory', str(blocked), '--result-file', str(result)])
    assert code == 1
    assert not json.loads(result.read_text(encoding='utf-8'))['success']


def test_existing_server_without_known_storage_cannot_start_model_download(tmp_path, monkeypatch):
    from signum.config import AppConfig
    session = MagicMock()
    monkeypatch.setattr('signum.setup_local_ai.requests.Session', lambda: session)
    monkeypatch.setattr('signum.ai.ollama_client.OllamaVisionModel.list_models', lambda url: [])
    monkeypatch.setattr('signum.ai.local_ollama.managed_model_directory', lambda url: None)
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    with pytest.raises(ValueError, match='Wskaż folder'):
        preparer.prepare_ollama({'ollama', 'ollama\\small'}, AppConfig())
    session.post.assert_not_called()
