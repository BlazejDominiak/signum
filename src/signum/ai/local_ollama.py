"""Start the standalone Ollama selected during installation, without global changes."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from signum.ai.base import AIConnectionError

_LOCK = threading.Lock()
_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}
_MODEL_DIRECTORIES: dict[str, Path] = {}


def managed_model_directory(base_url: str) -> Path | None:
    url = urlsplit(base_url)
    origin = f"http://127.0.0.1:{url.port or 11434}"
    process = _PROCESSES.get(origin)
    if process is not None and process.poll() is None:
        return _MODEL_DIRECTORIES.get(origin)
    return None


def start_local_ollama(base_url: str, runtime_dir: str) -> None:
    url = urlsplit(base_url)
    if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1"}:
        raise AIConnectionError("Automatyczny start Ollamy wymaga lokalnego adresu HTTP.")
    root = Path(runtime_dir)
    executable = root / "ollama.exe"
    external = False
    if (root / "runtime.json").is_file():
        try:
            manifest = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
            executable = Path(manifest["external_executable"])
            external = True
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AIConnectionError("Niepoprawna konfiguracja wykrytej Ollamy.") from exc
    if not root.is_absolute() or not executable.is_absolute() or not executable.is_file():
        raise AIConnectionError("Nie znaleziono przygotowanej Ollamy. Uruchom konfigurator AI.")
    origin = f"http://127.0.0.1:{url.port or 11434}"
    session = requests.Session()
    session.trust_env = False
    with _LOCK:
        try:
            response = session.get(f"{origin}/api/version", timeout=2)
            if response.status_code == 200:
                return
            raise AIConnectionError("Port Ollamy jest zajęty przez inną usługę.")
        except requests.ConnectionError:
            pass
        process = _PROCESSES.get(origin)
        if process is None or process.poll() is not None:
            env = os.environ.copy()
            for key in ("PYTHONHOME", "PYTHONPATH", "_PYI_APPLICATION_HOME_DIR",
                        "_PYI_PARENT_PROCESS_LEVEL"):
                env.pop(key, None)
            env.update({
                "OLLAMA_HOST": origin.removeprefix("http://"),
                "OLLAMA_NO_CLOUD": "1",
                "TEMP": str(root.parent / "temp"), "TMP": str(root.parent / "temp"),
            })
            if not external:
                env["OLLAMA_MODELS"] = str(root.parent / "models" / "ollama")
            (root.parent / "temp").mkdir(parents=True, exist_ok=True)
            with (root / "server.log").open("ab") as log:
                process = subprocess.Popen(
                    [str(executable), "serve"], cwd=root, env=env,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            _PROCESSES[origin] = process
            if not external:
                _MODEL_DIRECTORIES[origin] = root.parent / "models" / "ollama"
            else:
                _MODEL_DIRECTORIES.pop(origin, None)
        for _ in range(120):
            try:
                if session.get(f"{origin}/api/version", timeout=2).status_code == 200:
                    return
            except requests.RequestException:
                pass
            if process.poll() is not None:
                raise AIConnectionError(f"Ollama nie wystartowała. Log: {root / 'server.log'}")
            time.sleep(0.25)
    raise AIConnectionError("Przekroczono czas startu lokalnej Ollamy.")
