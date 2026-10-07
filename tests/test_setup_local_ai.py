from __future__ import annotations

import hashlib
import json
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from signum.ai.base import AIConnectionError
from signum.config import AppConfig
from signum.setup_local_ai import (
    LocalAIPreparer,
    SetupCancelledError,
    _safe_extract,
    parse_components,
    validate_storage,
)


def test_explicit_model_selection_includes_ollama_and_rejects_unknown() -> None:
    assert parse_components("app,ollama\\small") == {"ollama", "ollama\\small"}
    assert parse_components("app") == set()
    with pytest.raises(ValueError):
        parse_components("not-a-model")


def test_storage_checks_free_space_before_downloading(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "signum.setup_local_ai.shutil.disk_usage", lambda root: SimpleNamespace(free=5 * 1024**3)
    )
    with pytest.raises(ValueError, match="35 GB"):
        validate_storage(str(tmp_path), {"jev"})


def test_archive_cannot_escape_selected_storage(tmp_path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../escape.txt", "unsafe")
    with pytest.raises(ValueError):
        _safe_extract(archive, tmp_path / "runtime")
    assert not (tmp_path / "escape.txt").exists()


def test_download_checks_hash_and_reuses_verified_file(tmp_path) -> None:
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    data = b"verified weights"
    target = tmp_path / "weights"
    checksum = hashlib.sha256(data).hexdigest()
    response = Mock()
    response.headers = {"Content-Length": str(len(data))}
    response.iter_content.return_value = [data]
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    preparer.session.get = Mock(return_value=response)
    assert preparer.download("https://example.test/model", target, checksum) == target
    assert target.read_bytes() == data
    preparer.session.get.reset_mock()
    assert preparer.download("https://example.test/model", target, checksum) == target
    preparer.session.get.assert_not_called()
    response.iter_content.return_value = [b"wrong"]
    with pytest.raises(ValueError, match="suma kontrolna"):
        preparer.download("https://example.test/model", tmp_path / "other", checksum)
    assert not (tmp_path / "other").exists()


def test_cancel_stops_before_any_download(tmp_path) -> None:
    event = threading.Event()
    event.set()
    preparer = LocalAIPreparer(tmp_path, Mock(), event)
    preparer.session.get = Mock()
    with pytest.raises(SetupCancelledError):
        preparer.download("https://example.test/model", tmp_path / "weights")
    preparer.session.get.assert_not_called()


def test_existing_jev_is_reused_and_gpu_released_even_on_failure(tmp_path, monkeypatch) -> None:
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event(), check_only=True)
    preparer.download = Mock(side_effect=AssertionError("Unexpected download"))
    monkeypatch.setattr("signum.ai.local_vjev._runtime_paths", Mock(return_value=(tmp_path,) * 4))
    monkeypatch.setattr("signum.setup_local_ai.probe_runtime", Mock(return_value="libraries OK"))
    model = Mock()
    model.analyze_image.side_effect = RuntimeError("image failed")
    factory = Mock(return_value=model)
    monkeypatch.setattr("signum.ai.jev_client.JevVisionModel", factory)
    with pytest.raises(RuntimeError, match="image failed"):
        preparer.prepare_jev(AppConfig(vjev_runtime_dir=str(tmp_path)))
    assert factory.call_args.kwargs["model"] == "vjev-vision"
    assert factory.call_args.kwargs["api_key"] == ""
    model.release_resources.assert_called_once()


def test_failed_ollama_pull_never_saves_ready_configuration(tmp_path, monkeypatch) -> None:
    config = AppConfig()
    saved = Mock()
    monkeypatch.setattr(AppConfig, "save", saved)
    session = Mock()
    session.get.return_value.raise_for_status.return_value = None
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_lines.return_value = [b'{"error":"disk full"}']
    session.post.return_value = response
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))
    monkeypatch.setattr(
        "signum.ai.ollama_client.OllamaVisionModel.list_models", Mock(return_value=[])
    )
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    with pytest.raises(RuntimeError, match="disk full"):
        preparer.prepare_ollama({"ollama", "ollama\\small"}, config)
    saved.assert_not_called()


def test_stopped_existing_ollama_is_started_without_download(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "custom-install" / "ollama.exe"
    executable.parent.mkdir()
    executable.touch()
    session = Mock()
    session.get.side_effect = requests.ConnectionError("stopped")
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))
    start = Mock()
    monkeypatch.setattr("signum.ai.local_ollama.start_local_ollama", start)
    monkeypatch.setattr(
        "signum.ai.ollama_client.OllamaVisionModel.list_models", Mock(return_value=[])
    )
    monkeypatch.setattr(AppConfig, "save", Mock())
    root = tmp_path / "ai"
    preparer = LocalAIPreparer(root, Mock(), threading.Event(), str(executable))
    preparer.download = Mock(side_effect=AssertionError("Unexpected download"))
    config = AppConfig()
    preparer.prepare_ollama({"ollama"}, config)
    start.assert_called_once_with("http://127.0.0.1:11434", str(root / "ollama-launcher"))
    assert json.loads((root / "ollama-launcher/runtime.json").read_text(encoding="utf-8")) == {
        "external_executable": str(executable),
    }


def test_existing_ollama_launcher_keeps_its_model_folder(tmp_path, monkeypatch) -> None:
    from signum.ai.local_ollama import start_local_ollama

    executable = tmp_path / "different-folder" / "ollama.exe"
    executable.parent.mkdir()
    executable.touch()
    root = tmp_path / "ai" / "ollama"
    root.mkdir(parents=True)
    (root / "runtime.json").write_text(
        json.dumps(
            {
                "external_executable": str(executable),
            }
        ),
        encoding="utf-8",
    )
    session = Mock()
    session.get.side_effect = [requests.ConnectionError(), SimpleNamespace(status_code=200)]
    monkeypatch.setattr("signum.ai.local_ollama.requests.Session", Mock(return_value=session))
    monkeypatch.setattr("signum.ai.local_ollama._PROCESSES", {})
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "existing-models"))
    launch = Mock()
    monkeypatch.setattr("signum.ai.local_ollama.subprocess.Popen", launch)
    start_local_ollama("http://127.0.0.1:11434", str(root))
    assert launch.call_args.args[0] == [str(executable), "serve"]
    assert launch.call_args.kwargs["env"]["OLLAMA_MODELS"] == str(tmp_path / "existing-models")


def test_installer_has_utf8_bom_for_risk_text_and_component_choices() -> None:
    assert Path("installer/legal/RISK-NOTICE-pl.txt").read_bytes().startswith(b"\xef\xbb\xbf")
    source = Path("installer/signum.iss").read_text(encoding="utf-8-sig")
    assert "[Components]" in source
    assert "ollama\\small" in source and "ollama\\large" in source
    assert "--setup-local-ai" in source
    assert "DetectGPU" in source and "GpuMemoryMB >= 15000" in source
    assert "GpuVendor <> 4318" in source


def test_fresh_jev_prepares_isolated_cuda_runtime_and_frozen_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "signum.ai.local_vjev._runtime_paths",
        Mock(side_effect=[AIConnectionError("not installed"), (tmp_path,) * 4]),
    )
    monkeypatch.setattr("signum.setup_local_ai.probe_runtime", Mock(return_value="libraries OK"))
    monkeypatch.setattr("signum.setup_local_ai.require_nvidia_gpu", Mock())
    monkeypatch.setattr(AppConfig, "save", Mock())
    model = Mock()
    model.analyze_image.return_value = SimpleNamespace(signature_probability=0.01, signatures=())
    monkeypatch.setattr("signum.ai.jev_client.JevVisionModel", Mock(return_value=model))
    metadata = Mock()
    metadata.json.return_value = {
        "siblings": [
            {"rfilename": "config.json"},
            {"rfilename": "model.safetensors", "lfs": {"sha256": "a" * 64}},
        ]
    }
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.session.get = Mock(return_value=metadata)

    def download(url, target, expected_hash=""):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        return target

    def extract(archive, target):
        target.mkdir(parents=True, exist_ok=True)
        (target / "python.exe").touch()

    preparer.download = Mock(side_effect=download)
    preparer.run_process = Mock()
    monkeypatch.setattr("signum.setup_local_ai._safe_extract", extract)
    config = AppConfig(vjev_runtime_dir=str(tmp_path / "missing"))
    preparer.prepare_jev(config)
    commands = [call.args[0] for call in preparer.run_process.call_args_list]
    assert any(
        "torch==2.11.0" in cmd and "https://download.pytorch.org/whl/cu128" in cmd
        for cmd in commands
    )
    assert any("--no-deps" in cmd for cmd in commands)
    assert all(cmd[0] == str(tmp_path / "jev/python/python.exe") for cmd in commands)
    assert (tmp_path / "jev/runtime.json").is_file()
    model.release_resources.assert_called_once()
