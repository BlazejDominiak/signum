"""Local component discovery, dependency checks and actionable recovery messages."""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from signum.config import AppConfig

THIRD_PARTY_NOTICE = (
    "Ollama, modele, biblioteki i Python są składnikami zewnętrznymi, które należy "
    "pobierać ze sprawdzonych źródeł; autor Signum nie bierze za nie odpowiedzialności."
)
COMPONENT_LABELS = {
    "ollama": "Ollama — obsługa modeli lokalnych",
    "ollama\\small": "Gemma 4 E2B — podpisy i kategoryzacja (ok. 4,6 GB; zalecane 8 GB VRAM)",
    "ollama\\large": "Gemma 4 12B — podpisy i kategoryzacja (ok. 8 GB; zalecane 16 GB VRAM)",
    "jev": "Jev — podpisy (Python + biblioteki + model; NVIDIA 16 GB; ok. 15 GB)",
    "jevk5": "JevK5 — kategoryzacja (Python + biblioteki + model; NVIDIA 16 GB; ok. 15 GB)",
}


def repair_instructions(error: str, provider: str = "") -> str:
    if "\n\nJak naprawić:" in error:
        return error
    lower = error.lower()
    if any(
        word in lower
        for word in ("zepsuty plik", "invalid pdf", "pdf header", "encrypted", "zaszyfrow")
    ):
        advice = "Otwórz dokument w czytniku PDF; użyj poprawnej, niezaszyfrowanej kopii pliku."
    elif any(word in lower for word in ("out of memory", "not enough memory", "pamięci gpu")):
        advice = (
            "Zamknij inne programy korzystające z GPU i spróbuj ponownie. "
            "Jeśli pamięci nadal brakuje, wybierz mniejszy model w Ustawieniach AI."
        )
    elif any(word in lower for word in ("cuda", "nvidia", "driver", "kernel image")):
        advice = (
            "Zainstaluj aktualny sterownik karty ze strony https://www.nvidia.com/Download/ "
            "i uruchom komputer ponownie. Jev i JevK5 wymagają NVIDIA z 16 GB VRAM; "
            "na innym sprzęcie wybierz model w Ollamie lub AI od dostawcy."
        )
    elif any(word in lower for word in ("winerror 126", "winerror 127", "vcruntime", "dll load")):
        advice = (
            "Zainstaluj Microsoft Visual C++ Redistributable x64 z "
            "https://aka.ms/vc14/vc_redist.x64.exe, uruchom komputer ponownie, "
            "a następnie sprawdź składnik ponownie."
        )
    elif any(
        word in lower
        for word in ("nie analizuje obraz", "does not support images", "vision is not supported")
    ):
        advice = (
            "W Ustawieniach AI wybierz model obsługujący obrazy. "
            "Modele wyłącznie tekstowe można testować w kategoryzacji."
        )
    elif "nie zwrócił poprawnej kategorii" in lower:
        advice = (
            "Sprawdź format API i prompt w Ustawieniach AI. Jeśli test nadal się nie udaje, "
            "wybierz model tekstowy, który obsługuje odpowiedzi JSON."
        )
    elif any(word in lower for word in ("timeout", "timed out", "przekroczono czas")):
        advice = (
            "Sprawdź połączenie i obciążenie komputera. Zwiększ limit czasu w Ustawieniach AI "
            "lub wybierz mniejszy model, następnie ponów Testuj połączenie."
        )
    elif any(word in lower for word in ("401", "403", "klucz")):
        advice = (
            "W Ustawieniach AI sprawdź klucz API, uprawnienia i adres usługi; "
            "użyj Testuj połączenie."
        )
    elif "429" in lower or "limit żądań" in lower:
        advice = "Odczekaj chwilę i sprawdź limit konta u dostawcy AI, następnie ponów test."
    elif any(word in lower for word in ("disk", "miejsce", "miejsca", "winerror 112")):
        advice = (
            "W Składnikach AI wybierz dysk z większą ilością wolnego miejsca i ponów instalację."
        )
    elif any(word in lower for word in ("permission", "access is denied", "odmowa", "winerror 5")):
        advice = "Wybierz własny, zapisywalny folder w Składnikach AI i ponów instalację."
    elif any(word in lower for word in ("ssl", "certificate", "proxy", "download", "pobier")):
        advice = (
            "Sprawdź połączenie z internetem, datę systemową i ustawienia proxy. "
            "Ponów instalację w Składnikach AI; nie wyłączaj weryfikacji certyfikatów."
        )
    elif provider in {"openai", "anthropic", "api", "venice"}:
        advice = (
            "W Ustawieniach AI sprawdź adres, format API, nazwę modelu i klucz; "
            "użyj Testuj połączenie. Sprawdź również dostępność usługi u dostawcy."
        )
    else:
        advice = (
            "Otwórz Składniki AI, zaznacz niedziałający składnik i wybierz Sprawdź. "
            "Jeśli test się nie powiedzie, wybierz Instaluj / napraw. "
            "Po zakończeniu użyj Testuj połączenie w Ustawieniach AI."
        )
    return error + "\n\nJak naprawić: " + advice


def find_ollama(config: AppConfig) -> str:
    candidates = [shutil.which("ollama") or ""]
    if config.ollama_runtime_dir:
        root = Path(config.ollama_runtime_dir)
        candidates.insert(0, str(root / "ollama.exe"))
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
            candidates.insert(
                0,
                json.loads((root / "runtime.json").read_text(encoding="utf-8"))[
                    "external_executable"
                ],
            )
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(str(Path(local) / "Programs/Ollama/ollama.exe"))
    return next((p for p in candidates if p and Path(p).is_file()), "")


def jevk5_files(config: AppConfig) -> None:
    required = [Path(config.classification_jev_python)]
    model = Path(config.classification_jev_model_dir)
    required += [
        model / name
        for name in ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors")
    ]
    required += [Path(config.classification_jev_runtime) / "jevk5" / "__init__.py"]
    if (
        not config.classification_jev_packages
        or not Path(config.classification_jev_packages).is_dir()
    ):
        raise ValueError("Brak katalogu bibliotek JevK5.")
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise ValueError("Brak składników JevK5: " + ", ".join(missing))


def probe_runtime(
    kind: str,
    python: str,
    packages: str,
    model: str,
    runtime: str,
    cache: Path,
    cancelled: threading.Event | None = None,
) -> str:
    """Import real libraries and run a CUDA operation in the actual model interpreter."""
    if not python or not Path(python).is_file():
        raise ValueError("Nie znaleziono Pythona składnika. Użyj Instaluj / napraw.")
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "_PYI_APPLICATION_HOME_DIR",
        "_PYI_PARENT_PROCESS_LEVEL",
    ):
        env.pop(key, None)
    env.update(
        TEMP=str(cache),
        TMP=str(cache),
        HF_HOME=str(cache),
        TORCH_HOME=str(cache),
        PYTHONUTF8="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    args = [
        python,
        str(Path(__file__).parent / "ai/runtime_probe.py"),
        "--kind",
        kind,
        "--packages",
        packages,
        "--runtime",
        runtime,
        "--model",
        model,
    ]
    if os.name == "nt":
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        process = subprocess.Popen(
            args,
            cwd=cache,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        if os.name == "nt":
            ctypes.windll.kernel32.SetDllDirectoryW(getattr(sys, "_MEIPASS", None))
    deadline = time.monotonic() + 120
    try:
        while True:
            try:
                output, errors = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancelled and cancelled.is_set():
                    raise RuntimeError("Sprawdzanie anulowane.") from None
                if time.monotonic() > deadline:
                    raise TimeoutError("Biblioteki nie odpowiedziały w ciągu 120 sekund.") from None
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    try:
        result = json.loads(output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ValueError("Nie można uruchomić bibliotek: " + errors[-2000:]) from None
    if process.returncode or not result.get("ok"):
        raise ValueError(str(result.get("message", errors[-2000:])))
    return str(result["message"])


def require_nvidia_gpu() -> None:
    executable = shutil.which("nvidia-smi")
    if not executable:
        candidate = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32/nvidia-smi.exe"
        executable = str(candidate) if candidate.is_file() else None
    if not executable:
        raise ValueError("Nie wykryto sterownika NVIDIA. Jev i JevK5 wymagają NVIDIA z 16 GB VRAM.")
    result = subprocess.run(
        [executable, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        memory = int(result.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        raise ValueError("Nie można sprawdzić karty NVIDIA; zaktualizuj sterownik.") from None
    if result.returncode or memory < 15000:
        raise ValueError("Ten pakiet wymaga NVIDIA z co najmniej 16 GB pamięci GPU.")
