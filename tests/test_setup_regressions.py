"""Audit regressions for setup. Services and files are isolated."""
import hashlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from signum.config import AppConfig
from signum.setup_local_ai import LocalAIPreparer


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr('signum.config.config_file', lambda: tmp_path / 'settings.json')
    monkeypatch.setattr('signum.config.config_dir', lambda: tmp_path)
    monkeypatch.setattr('signum.config.get_api_key', lambda _: '')


def test_model_pull_checks_free_space_with_an_existing_ollama(tmp_path, monkeypatch):
    session = MagicMock()
    response = session.post.return_value.__enter__.return_value
    response.iter_lines.return_value = [b'{"status":"success"}']
    monkeypatch.setattr('signum.setup_local_ai.requests.Session', lambda: session)
    vision = MagicMock()
    vision.list_models.return_value = []
    vision.return_value.analyze_image.return_value.signatures = ()
    monkeypatch.setattr('signum.ai.ollama_client.OllamaVisionModel', vision)
    text = MagicMock()
    text.return_value.classify.return_value = {'choice': 'c01'}
    monkeypatch.setattr('signum.ai.text_classifiers.GemmaTextClassifier', text)
    disk_usage = Mock(return_value=SimpleNamespace(free=0))
    monkeypatch.setattr('signum.setup_local_ai.shutil.disk_usage', disk_usage)
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.ollama_model_directory = str(tmp_path)
    with pytest.raises(ValueError, match='miejsca'):
        preparer.prepare_ollama({'ollama', 'ollama\\small'}, AppConfig())


def test_retry_download_resumes_existing_partial_bytes(tmp_path):
    # One failed response leaves a partial payload; a retry should request only its suffix.
    payload = b'abcdef'
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.ollama_model_directory = str(tmp_path)
    partial = tmp_path / 'model.safetensors.part'
    partial.write_bytes(payload[:3])
    response = MagicMock()
    response.headers = {'Content-Length': '6'}
    response.iter_content.return_value = [payload]
    response.__enter__.return_value = response
    preparer.session.get = Mock(return_value=response)
    preparer.download('https://example.invalid/model', tmp_path / 'model.safetensors',
                      hashlib.sha256(payload).hexdigest())
    call = preparer.session.get.call_args
    assert call.kwargs.get('headers', {}).get('Range') == 'bytes=3-', 'Retry restarted at byte zero'
