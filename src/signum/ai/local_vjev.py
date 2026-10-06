"""Uruchamianie przygotowanego vjev poza procesem GUI, bez pobierania wag."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from signum.ai.base import AIConnectionError

_START_LOCK = threading.Lock()
_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}


def _wait_for_server_exit(origin: str, pid: object) -> None:
    process = _PROCESSES.get(origin)
    if process is not None and process.pid == pid:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise AIConnectionError("Jev nadal zwalnia pamięć GPU.") from exc
    elif os.name == "nt" and isinstance(pid, int) and pid > 0:
        # Serwer może przeżyć zamknięcie GUI. Czekamy także na proces z poprzedniej sesji.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE, bez prawa zabijania
        if handle:
            try:
                if kernel32.WaitForSingleObject(handle, 10_000) != 0:
                    raise AIConnectionError("Jev nadal zwalnia pamięć GPU.")
            finally:
                kernel32.CloseHandle(handle)


def _local_origin(base_url: str) -> str:
    url = urlsplit(base_url)
    if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1"}:
        raise AIConnectionError("Automatyczny start Jev obsługuje tylko lokalny adres HTTP.")
    if url.path.rstrip("/") != "/v1":
        raise AIConnectionError("Lokalny serwer Jev wymaga adresu zakończonego /v1.")
    return f"http://127.0.0.1:{url.port or 80}"


def _runtime_paths(runtime_dir: str) -> tuple[Path, Path, Path, Path]:
    root = Path(runtime_dir)
    try:
        manifest = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
        python = Path(manifest["python"])
        packages = Path(manifest["packages"])
        model = Path(manifest["model_dir"])
        if not all(path.is_absolute() for path in (root, python, packages, model)):
            raise ValueError("Ścieżki runtime muszą być bezwzględne")
        if not python.is_file() or not (packages / "vjev" / "server.py").is_file():
            raise ValueError("Brak interpretera lub pakietu vjev")
        index = json.loads((model / "model.safetensors.index.json").read_text(encoding="utf-8"))
        required = {
            "config.json", "processor_config.json", "tokenizer.json", "head.pt", "vjev.json",
        }
        required.update(index["weight_map"].values())
        if not all((model / filename).is_file() for filename in required):
            raise ValueError("Pobieranie wag nie zostało zakończone")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AIConnectionError(
            f"Lokalny Jev nie jest przygotowany w {root}. "
            "Sprawdź katalog runtime i komplet wag modelu (runtime.json)."
        ) from exc
    return root, python, packages, model


def start_local_vjev(base_url: str, runtime_dir: str, timeout_s: int) -> None:
    """Startuje tylko na localhost; czeka na rzeczywiste załadowanie modelu."""
    origin = _local_origin(base_url)
    root, python, _packages, _model = _runtime_paths(runtime_dir)
    session = requests.Session()
    session.trust_env = False
    deadline = time.monotonic() + timeout_s
    log_path = root / "server.log"
    with _START_LOCK:
        try:
            response = session.get(f"{origin}/v1/models", timeout=2, allow_redirects=False)
            if response.status_code == 200:
                return
            raise AIConnectionError(
                f"Port Jev jest zajęty przez inną usługę (HTTP {response.status_code})."
            )
        except requests.exceptions.ConnectionError:
            pass
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError(
                "Lokalny serwer Jev nie odpowiada; sprawdź zajętość portu."
            ) from exc
        process = _PROCESSES.get(origin)
        if process is None or process.poll() is not None:
            env = os.environ.copy()
            for key in (
                "PYTHONHOME", "PYTHONPATH",
                "_PYI_APPLICATION_HOME_DIR", "_PYI_PARENT_PROCESS_LEVEL",
            ):
                env.pop(key, None)
            env.update({
                "HF_HOME": str(root / "cache" / "huggingface"),
                "TORCH_HOME": str(root / "cache" / "torch"),
                "TORCHINDUCTOR_CACHE_DIR": str(root / "cache" / "torchinductor"),
                "TRITON_CACHE_DIR": str(root / "cache" / "triton"),
                "CUDA_CACHE_PATH": str(root / "cache" / "cuda"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "TEMP": str(root / "temp"), "TMP": str(root / "temp"),
                "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1",
            })
            (root / "temp").mkdir(parents=True, exist_ok=True)
            (root / "cache" / "cuda").mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                windows = Path(env.get("SystemRoot", "C:/Windows"))
                env["PATH"] = os.pathsep.join(map(str, (
                    python.parent, python.parent / "DLLs", windows / "System32", windows,
                )))
            bootstrap = Path(__file__).with_name("vjev_bootstrap.py")
            with log_path.open("ab") as log:
                try:
                    process = subprocess.Popen(
                        [str(python), str(bootstrap), str(root / "runtime.json"),
                         str(urlsplit(origin).port)],
                        cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except OSError as exc:
                    raise AIConnectionError(
                        f"Nie udało się uruchomić Jev. Log: {log_path}"
                    ) from exc
            _PROCESSES[origin] = process
    try:
        while time.monotonic() < deadline:
            try:
                response = session.get(f"{origin}/v1/models", timeout=2, allow_redirects=False)
                if response.status_code == 200:
                    return
            except requests.exceptions.RequestException:
                pass
            if process.poll() is not None:
                raise AIConnectionError(f"Lokalny Jev zakończył start z błędem. Log: {log_path}")
            time.sleep(0.5)
        raise AIConnectionError(
            f"Trwa ładowanie lokalnego Jev; przekroczono {timeout_s} s. "
            f"Spróbuj ponownie lub sprawdź log: {log_path}"
        )
    finally:
        session.close()


def stop_local_vjev(base_url: str, runtime_dir: str) -> str:
    """Zatrzymuje wyłącznie serwer uruchomiony przez Signum, zwalniając VRAM."""
    origin = _local_origin(base_url)
    state_path = Path(runtime_dir) / f"service-{urlsplit(origin).port}.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        token = state["control_token"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AIConnectionError("Brak lokalnego serwera Jev uruchomionego przez Signum.") from exc
    with requests.Session() as session:
        session.trust_env = False
        try:
            response = session.post(
                f"{origin}/signum/shutdown", headers={"X-Signum-Control": token},
                timeout=5, allow_redirects=False,
            )
            if response.status_code != 200:
                raise AIConnectionError("Ten serwer Jev nie może być zatrzymany przez Signum.")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    session.get(f"{origin}/health", timeout=1, allow_redirects=False)
                except requests.exceptions.ConnectionError:
                    _wait_for_server_exit(origin, state.get("pid"))
                    return "Lokalny Jev zatrzymany — pamięć GPU zwolniona."
                except requests.exceptions.RequestException:
                    pass
                time.sleep(0.2)
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError("Nie udało się zatrzymać lokalnego Jev.") from exc
    raise AIConnectionError("Zatrzymywanie Jev trwa zbyt długo. Sprawdź server.log.")
