"""Cykl życia lokalnego serwera; prawdziwy HTTP/proces, mały sztuczny backend."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from socket import socket
from unittest.mock import Mock

import pytest
import requests

from signum.ai.base import AIConnectionError
from signum.ai.jev_client import JevVisionModel
from signum.ai.local_vjev import _PROCESSES, start_local_vjev, stop_local_vjev


def _free_port() -> int:
    with socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def fake_runtime(tmp_path: Path) -> Path:
    packages = tmp_path / "packages"
    vjev = packages / "vjev"
    vjev.mkdir(parents=True)
    (vjev / "__init__.py").write_text("", encoding="utf-8")
    (vjev / "server.py").write_text('''
import json
from http.server import BaseHTTPRequestHandler
class ModelEngine:
    model_id = "vjev-vision"
    def __init__(self, *args, **kwargs): pass
def make_handler(engine, page):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def _json(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            self._json({"models": [{"id": engine.model_id, "vision": True}]})
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self._json({"answers": {
                "handwritten": {"type": "noul", "noul": 0.1},
                "initials": {"type": "noul", "noul": 0.1},
                "stamp": {"type": "noul", "noul": 0.1},
                "document_type": {"type": "choice", "choice": "other"}}})
    return Handler
''', encoding="utf-8")
    model = tmp_path / "models" / "vjev-vision"
    model.mkdir(parents=True)
    for name in (
        "config.json", "processor_config.json", "tokenizer.json", "head.pt", "vjev.json",
        "weights.safetensors",
    ):
        (model / name).write_text("{}", encoding="utf-8")
    (model / "model.safetensors.index.json").write_text(
        '{"weight_map":{"weight":"weights.safetensors"}}', encoding="utf-8",
    )
    (tmp_path / "runtime.json").write_text(json.dumps({
        "python": sys.executable, "packages": str(packages), "model_dir": str(model),
    }), encoding="utf-8")
    return tmp_path


def test_start_test_obrazu_i_zatrzymanie_wlasnego_serwera(fake_runtime: Path) -> None:
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    url = f"{origin}/v1"
    model = JevVisionModel(url, "vjev-vision", timeout_s=20, runtime_dir=str(fake_runtime))
    try:
        assert "test obrazu" in model.check_connection()
        state = json.loads((fake_runtime / f"service-{port}.json").read_text())
        assert state["pid"] == _PROCESSES[origin].pid
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                f"{origin}/signum/shutdown", headers={"X-Signum-Control": "wrong"}, timeout=2,
            )
            assert response.status_code == 403
        start_local_vjev(url, str(fake_runtime), 20)
        assert _PROCESSES[origin].pid == state["pid"]  # bez drugiego loadera
        assert "zatrzymany" in model.stop_local()
        _PROCESSES[origin].wait(timeout=5)
        assert not (fake_runtime / f"service-{port}.json").exists()
    finally:
        process = _PROCESSES.pop(origin, None)
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


@pytest.mark.parametrize("url", [
    "https://api.example.test/v1", "http://127.0.0.1:8800/wrong", "http://[::1]:8800/v1",
])
def test_nie_uruchamia_procesu_dla_zdalnego_lub_niezgodnego_api(url: str) -> None:
    with pytest.raises(AIConnectionError):
        start_local_vjev(url, "missing", 10)
    with pytest.raises(AIConnectionError):
        stop_local_vjev(url, "missing")


def test_brak_runtime_i_niepelne_wagi_maja_czytelny_blad(
    fake_runtime: Path, tmp_path: Path,
) -> None:
    url = "http://127.0.0.1:8800/v1"
    with pytest.raises(AIConnectionError, match="Instaluj / napraw"):
        start_local_vjev(url, str(tmp_path / "missing"), 10)
    (fake_runtime / "models/vjev-vision/weights.safetensors").unlink()
    with pytest.raises(AIConnectionError, match="Instaluj / napraw"):
        start_local_vjev(url, str(fake_runtime), 10)


def test_zdalny_preflight_nigdy_nie_startuje_lokalnego_modelu(monkeypatch) -> None:
    start = Mock()
    monkeypatch.setattr("signum.ai.jev_client.start_local_vjev", start)
    model = JevVisionModel(
        "https://api.example.test/v1", "vjev-vision", runtime_dir="H:/Tools/SignumJev",
    )
    model._session.request = Mock(side_effect=requests.exceptions.ConnectionError())
    with pytest.raises(AIConnectionError):
        model.check_connection()
    start.assert_not_called()


def test_blad_http_nie_wywoluje_startu_localhost(monkeypatch) -> None:
    start = Mock()
    monkeypatch.setattr("signum.ai.jev_client.start_local_vjev", start)
    model = JevVisionModel(
        "http://127.0.0.1:8800/v1", "vjev-vision", runtime_dir="H:/Tools/SignumJev",
    )
    model._session.request = Mock(return_value=Mock(status_code=401))
    from signum.ai.base import AIResponseError

    with pytest.raises(AIResponseError):
        model.check_connection()
    start.assert_not_called()
