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
from signum.i18n import tr, translate_error


def third_party_notice() -> str:
    return tr("core.components.third_party_notice")


def component_labels() -> dict[str, str]:
    return {
        key: tr("core.components." + key.replace("\\", "."))
        for key in ("ollama", "ollama\\small", "ollama\\large", "jev", "jevk5")
    }


def repair_instructions(error: str, provider: str = "") -> str:
    if any(marker in error for marker in ("\n\nJak naprawić:", "\n\nHow to fix:")):
        return error
    lower = error.lower()
    if any(
        word in lower
        for word in ("zepsuty plik", "invalid pdf", "pdf header", "encrypted", "zaszyfrow")
    ):
        advice = tr("core.local_components.open_the_document_in_a_pdf_reader")
    elif any(word in lower for word in ("out of memory", "not enough memory", "pamięci gpu")):
        advice = tr("core.local_components.close_other_programs_using_the_gpu_and")
    elif any(word in lower for word in ("cuda", "nvidia", "driver", "kernel image")):
        advice = tr("core.local_components.install_the_latest_graphics_driver_from_https")
    elif any(word in lower for word in ("winerror 126", "winerror 127", "vcruntime", "dll load")):
        advice = tr("core.local_components.install_microsoft_visual_c_redistributable_x64_from")
    elif any(
        word in lower
        for word in ("nie analizuje obraz", "does not support images", "vision is not supported")
    ):
        advice = tr("core.local_components.select_a_model_that_supports_images_in")
    elif any(
        word in lower
        for word in (
            "nie zwrócił poprawnej kategorii",
            "did not return a valid category",
        )
    ):
        advice = tr("core.local_components.check_the_api_format_and_prompt_in")
    elif any(word in lower for word in ("timeout", "timed out", "przekroczono czas")):
        advice = tr("core.local_components.check_the_connection_and_computer_load_increase")
    elif any(word in lower for word in ("401", "403", "klucz")):
        advice = tr("core.local_components.check_the_api_key_permissions_and_service")
    elif "429" in lower or "limit żądań" in lower:
        advice = tr("core.local_components.wait_a_moment_and_check_your_ai")
    elif any(word in lower for word in ("disk", "miejsce", "miejsca", "winerror 112")):
        advice = tr("core.local_components.select_a_drive_with_more_free_space")
    elif any(word in lower for word in ("permission", "access is denied", "odmowa", "winerror 5")):
        advice = tr("core.local_components.select_a_writable_folder_of_your_own")
    elif any(word in lower for word in ("ssl", "certificate", "proxy", "download", "pobier")):
        advice = tr("core.local_components.check_the_internet_connection_system_date_and")
    elif provider in {"openai", "anthropic", "api", "venice"}:
        advice = tr("core.local_components.check_the_address_api_format_model_name")
    else:
        advice = tr("core.local_components.open_ai_components_select_the_failing_component")
    return error + tr("core.local_components.how_to_fix") + advice


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
        raise ValueError(tr("core.local_components.missing_jevk5_library_directory"))
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise ValueError(tr("core.local_components.missing_jevk5_components") + ", ".join(missing))


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
        raise ValueError(tr("core.local_components.component_python_was_not_found_use_install"))
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
                    raise RuntimeError(tr("core.check_cancelled")) from None
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        tr("core.local_components.libraries_did_not_respond_within_120_seconds")
                    ) from None
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    try:
        result = json.loads(output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ValueError(
            tr("core.local_components.could_not_start_libraries") + errors[-2000:]
        ) from None
    if process.returncode or not result.get("ok"):
        raise ValueError(translate_error(str(result.get("message", errors[-2000:]))))
    return str(result["message"])


def require_nvidia_gpu() -> None:
    executable = shutil.which("nvidia-smi")
    if not executable:
        candidate = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32/nvidia-smi.exe"
        executable = str(candidate) if candidate.is_file() else None
    if not executable:
        raise ValueError(tr("core.local_components.nvidia_driver_not_detected_jev_and_jevk5"))
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
        raise ValueError(
            tr("core.local_components.could_not_check_the_nvidia_gpu_update")
        ) from None
    if result.returncode or memory < 15000:
        raise ValueError(tr("core.local_components.this_package_requires_nvidia_with_at_least"))
