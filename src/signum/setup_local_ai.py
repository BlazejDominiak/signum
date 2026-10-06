"""Optional third-party AI preparation. Only explicitly selected components are fetched."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import requests
from PIL import Image

from signum.ai.base import AIConnectionError
from signum.config import AppConfig
from signum.network import is_loopback_endpoint

OLLAMA_VERSION = "0.35.1"
MODEL_REPO = "yah01/vjev-vision"
MODEL_REVISION = "2fa8b58e40e5bc351a7d6dd39b953469a8f3ded2"
VJEV_REVISION = "37e2ffb2695b9bf278374fdefec24611c3b710c1"
MODELS = {"ollama\\small": "gemma4:e2b", "ollama\\large": "gemma4:12b"}
VALID_COMPONENTS = {"app", "ollama", "jev", *MODELS}
Progress = Callable[[str, int], None]


class SetupCancelledError(Exception):
    """The user stopped optional preparation."""


def parse_components(value: str) -> set[str]:
    components = set(filter(None, value.split(",")))
    if not components <= VALID_COMPONENTS:
        raise ValueError("Nieznany składnik instalacji AI")
    if components & MODELS.keys():
        components.add("ollama")
    return components - {"app"}


def validate_storage(directory: str, components: set[str]) -> Path:
    root = Path(directory)
    if not root.is_absolute():
        raise ValueError("Katalog AI musi mieć pełną ścieżkę")
    root.mkdir(parents=True, exist_ok=True)
    # Downloads, unpacked packages and temporary wheels must fit on this drive.
    needed_gb = 35 if "jev" in components else 0
    if "ollama" in components:
        needed_gb += 28 if len(components & MODELS.keys()) > 1 else 20
    if shutil.disk_usage(root).free < needed_gb * 1024**3:
        raise ValueError(f"Na tym dysku potrzeba co najmniej {needed_gb} GB wolnego miejsca")
    return root


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            if not (destination / item.filename).resolve().is_relative_to(target):
                raise ValueError("Archiwum zawiera ścieżkę spoza katalogu instalacji")
        zipped.extractall(destination)


class LocalAIPreparer:
    def __init__(
        self, root: Path, progress: Progress, cancelled: threading.Event,
        existing_ollama: str = "", existing_ollama_url: str = "",
    ) -> None:
        self.root = root
        self.progress = progress
        self.cancelled = cancelled
        self.existing_ollama = existing_ollama
        self.existing_ollama_url = existing_ollama_url
        self.session = requests.Session()
        self.downloads = root / "downloads"
        self.downloads.mkdir(parents=True, exist_ok=True)
        self.log = root / "setup.log"
        self.log.touch(exist_ok=True)

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise SetupCancelledError(
                "Przygotowanie AI anulowane. Pobrane pliki pozostają na dysku."
            )

    def status(self, text: str, percent: int = -1) -> None:
        self.check_cancelled()
        with self.log.open("a", encoding="utf-8") as log:
            log.write(text + "\n")
        self.progress(text, percent)

    def download(self, url: str, target: Path, expected_hash: str = "") -> Path:
        self.check_cancelled()
        if target.is_file() and expected_hash:
            with target.open("rb") as cached:
                valid = hashlib.file_digest(cached, "sha256").hexdigest() == expected_hash
            if valid:
                return target
        partial = target.with_name(target.name + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with self.session.get(url, stream=True, timeout=(20, 60)) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            last_update = 0.0
            with partial.open("wb") as file:
                for chunk in response.iter_content(1024 * 1024):
                    self.check_cancelled()
                    file.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if time.monotonic() - last_update > 0.4:
                        self.status(
                            f"{target.name}: {downloaded / 1024**2:.0f} MB"
                            + (f" / {total / 1024**2:.0f} MB" if total else ""),
                            min(100, downloaded * 100 // total) if total else -1,
                        )
                        last_update = time.monotonic()
        if expected_hash and digest.hexdigest() != expected_hash:
            raise ValueError(f"Niepoprawna suma kontrolna pliku {target.name}")
        partial.replace(target)
        return target

    def run_process(self, arguments: list[str], timeout: int = 3600) -> None:
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "_PYI_APPLICATION_HOME_DIR",
                    "_PYI_PARENT_PROCESS_LEVEL"):
            env.pop(key, None)
        temporary = self.root / "temp"
        temporary.mkdir(exist_ok=True)
        env.update({
            "TEMP": str(temporary), "TMP": str(temporary), "PYTHONUTF8": "1",
            "PIP_CACHE_DIR": str(self.root / "cache" / "pip"),
            "HF_HOME": str(self.root / "cache" / "huggingface"),
        })
        # Keep the packaged GUI's DLL directory out of external Python/Ollama.
        if os.name == "nt":
            import ctypes  # noqa: PLC0415

            ctypes.windll.kernel32.SetDllDirectoryW(None)
        with self.log.open("ab") as log:
            process = subprocess.Popen(
                arguments, cwd=self.root, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if os.name == "nt":
                ctypes.windll.kernel32.SetDllDirectoryW(getattr(sys, "_MEIPASS", None))
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    self.check_cancelled()
                    if time.monotonic() > deadline:
                        raise TimeoutError("Przekroczono czas przygotowania składnika")
                    time.sleep(0.2)
            except BaseException:
                process.terminate()
                process.wait(timeout=20)
                raise
            if process.returncode:
                raise RuntimeError(f"Przygotowanie składnika nie powiodło się. Log: {self.log}")

    def prepare_ollama(self, components: set[str], config: AppConfig) -> None:
        from signum.ai.local_ollama import start_local_ollama  # noqa: PLC0415
        from signum.ai.ollama_client import OllamaVisionModel  # noqa: PLC0415

        local = requests.Session()
        local.trust_env = False
        url = self.existing_ollama_url or "http://127.0.0.1:11434"
        if not is_loopback_endpoint(url):
            raise ValueError("Przygotowanie Ollamy wymaga lokalnego adresu API")
        try:
            local.get(f"{url}/api/version", timeout=3).raise_for_status()
            self.status("Korzystam z już działającej Ollamy i jej katalogu modeli.")
            runtime = config.ollama_runtime_dir
        except requests.RequestException:
            runtime_path = self.root / "ollama"
            if self.existing_ollama:
                executable = Path(self.existing_ollama)
                if not executable.is_absolute() or not executable.is_file():
                    raise ValueError("Wykryta Ollama nie jest już dostępna") from None
                runtime_path.mkdir(parents=True, exist_ok=True)
                (runtime_path / "runtime.json").write_text(
                    json.dumps({"external_executable": str(executable)}), encoding="utf-8",
                )
                self.status("Uruchamiam wykrytą Ollamę.")
            elif not (runtime_path / "ollama.exe").is_file():
                self.status("Pobieram Ollamę z oficjalnego wydania GitHub.")
                response = self.session.get(
                    f"https://api.github.com/repos/ollama/ollama/releases/tags/v{OLLAMA_VERSION}",
                    timeout=30,
                )
                response.raise_for_status()
                asset = next(a for a in response.json()["assets"]
                             if a["name"] == "ollama-windows-amd64.zip")
                checksum = str(asset.get("digest") or "").removeprefix("sha256:")
                if len(checksum) != 64:
                    raise ValueError("Wydanie Ollamy nie udostępnia sumy SHA-256") from None
                archive = self.download(asset["browser_download_url"],
                                        self.downloads / asset["name"], checksum)
                self.status("Rozpakowuję Ollamę i biblioteki obsługi GPU.")
                _safe_extract(archive, runtime_path)
            start_local_ollama(url, str(runtime_path))
            runtime = str(runtime_path)
        installed = OllamaVisionModel.list_models(url)
        selected = [model for key, model in MODELS.items() if key in components]
        for model in selected:
            if model not in installed:
                self.status(f"Pobieram {model}. Pobieranie może potrwać kilkanaście minut.")
                with local.post(f"{url}/api/pull", json={"model": model, "stream": True},
                                stream=True, timeout=(20, 120)) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        self.check_cancelled()
                        if not line:
                            continue
                        item = json.loads(line)
                        if item.get("error"):
                            raise RuntimeError(item["error"])
                        total = int(item.get("total", 0))
                        completed = int(item.get("completed", 0))
                        self.status(f"{model}: {item.get('status', '')}",
                                    min(100, completed * 100 // total) if total else -1)
            self.status(f"Sprawdzam odpowiedź obrazu w {model}.")
            client = OllamaVisionModel(url, model)
            client.check_connection()
            analysis = client.analyze_image(Image.new("RGB", (320, 400), "white"), 1120)
            if analysis.signatures:
                raise RuntimeError(f"{model} wskazał podpis na pustym obrazie testowym")
            # The model is ready; avoid reserving GPU while preparing another component.
            local.post(f"{url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=30)
            config.ollama_model = model
        config.ollama_url = url
        config.ollama_runtime_dir = runtime
        config.provider = "ollama"
        config.save()

    def prepare_jev(self, config: AppConfig) -> None:
        from signum.ai.jev_client import JevVisionModel  # noqa: PLC0415
        from signum.ai.local_vjev import _runtime_paths  # noqa: PLC0415

        runtime = self.root / "jev"
        for candidate in (Path(config.vjev_runtime_dir), runtime):
            try:
                _runtime_paths(str(candidate))
                runtime = candidate
                self.status(f"Korzystam z przygotowanego Jev: {candidate}")
                break
            except AIConnectionError:
                continue
        else:
            runtime.mkdir(parents=True, exist_ok=True)
            python_root = runtime / "python"
            python = python_root / "python.exe"
            packages = runtime / "packages"
            packages.mkdir(exist_ok=True)
            if not python.is_file():
                self.status("Przygotowuję osobny Python dla Jev.")
                archive = self.download(
                    "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip",
                    self.downloads / "python-3.11.9-embed-amd64.zip",
                )
                _safe_extract(archive, python_root)
            (python_root / "python311._pth").write_text(
                f"python311.zip\n.\n{packages}\nimport site\n", encoding="utf-8",
            )
            if not (python_root / "Lib" / "site-packages" / "pip").is_dir():
                bootstrap = self.download("https://bootstrap.pypa.io/get-pip.py",
                                          self.downloads / "get-pip.py")
                self.status("Przygotowuję narzędzie instalacji bibliotek Jev.")
                self.run_process([str(python), str(bootstrap), "pip==25.1.1", "--no-cache-dir"])
            self.status("Instaluję PyTorch CUDA i biblioteki Jev. To może potrwać kilka minut.")
            self.run_process([
                str(python), "-m", "pip", "install", "--target", str(packages),
                "--upgrade", "--no-cache-dir", "--index-url", "https://download.pytorch.org/whl/cu128",
                "torch==2.11.0", "torchvision==0.26.0",
            ])
            source = self.download(
                f"https://github.com/BubbleCal/vjev-serve/archive/{VJEV_REVISION}.zip",
                self.downloads / f"vjev-{VJEV_REVISION}.zip",
            )
            self.run_process([
                str(python), "-m", "pip", "install", "--target", str(packages),
                "--no-cache-dir", "--no-deps", str(source),
            ])
            # Do not let pip replace the selected CUDA Torch with another build.
            self.run_process([
                str(python), "-m", "pip", "install", "--target", str(packages),
                "--no-cache-dir", "transformers==5.18.0", "huggingface_hub==1.33.0",
                "pillow>=10.4", "safetensors>=0.8.0",
            ])
            self.status("Pobieram wagi Jev (~9 GB) i sprawdzam ich sumy kontrolne.")
            metadata = self.session.get(
                f"https://huggingface.co/api/models/{MODEL_REPO}/revision/{MODEL_REVISION}",
                params={"blobs": "true"}, timeout=30,
            )
            metadata.raise_for_status()
            model_dir = runtime / "models" / "vjev-vision"
            for item in metadata.json()["siblings"]:
                name = item["rfilename"]
                if Path(name).suffix not in {".json", ".safetensors", ".pt", ".jinja", ".txt"}:
                    continue
                if Path(name).is_absolute() or ".." in Path(name).parts:
                    raise ValueError("Niepoprawna ścieżka pliku modelu")
                checksum = (item.get("lfs") or {}).get("sha256", "")
                self.download(f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}",
                              model_dir / name, checksum)
            (runtime / "runtime.json").write_text(json.dumps({
                "python": str(python), "packages": str(packages), "model_dir": str(model_dir),
                "model_repo": MODEL_REPO, "model_revision": MODEL_REVISION,
                "vjev_revision": VJEV_REVISION, "device": "cuda",
            }, indent=2), encoding="utf-8")
        self.status("Ładuję Jev i sprawdzam analizę obrazu. Pierwszy start trwa dłużej.")
        client = JevVisionModel(
            base_url="http://127.0.0.1:8800/v1", model="vjev-vision",
            api_key="", timeout_s=300, runtime_dir=str(runtime),
        )
        try:
            client.check_connection()
            analysis = client.analyze_image(Image.new("RGB", (320, 400), "white"), 1120)
            if analysis.signature_probability is None or analysis.signatures:
                raise RuntimeError("Jev nie przeszedł sprawdzenia na pustym obrazie")
        finally:
            client.release_resources()
        config.vjev_runtime_dir = str(runtime)
        config.vjev_base_url = "http://127.0.0.1:8800/v1"
        config.vjev_model = "vjev-vision"
        config.save()

    def prepare(self, components: set[str]) -> None:
        config = AppConfig.load()
        if "ollama" in components:
            self.prepare_ollama(components, config)
        if "jev" in components:
            self.prepare_jev(config)
            if "ollama" not in components:
                config.provider = "vjev"
                config.save()
        self.status("Gotowe. Signum jest skonfigurowane do pracy z wybranym lokalnym AI.", 100)


def run_setup_dialog(arguments: list[str]) -> int:
    # GUI stays lightweight: preparation happens in a separate worker thread.
    from PySide6.QtCore import QThread, QTimer, QUrl, Signal  # noqa: PLC0415
    from PySide6.QtGui import QDesktopServices  # noqa: PLC0415
    from PySide6.QtWidgets import (  # noqa: PLC0415
        QDialog,
        QLabel,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--setup-local-ai", action="store_true")
    parser.add_argument("--ai-components", required=True)
    parser.add_argument("--ai-directory", required=True)
    parser.add_argument("--existing-ollama", default="")
    parser.add_argument("--existing-ollama-url", default="")
    options = parser.parse_args(arguments)
    components = parse_components(options.ai_components)
    cancelled = threading.Event()

    class Worker(QThread):
        progress = Signal(str, int)
        outcome = Signal(bool, str)

        def run(self) -> None:
            try:
                root = validate_storage(options.ai_directory, components)
                LocalAIPreparer(
                    root, self.progress.emit, cancelled,
                    options.existing_ollama, options.existing_ollama_url,
                ).prepare(components)
            except Exception as exc:
                self.outcome.emit(False, str(exc))
            else:
                self.outcome.emit(True, "Gotowe — możesz zamknąć to okno i uruchomić Signum.")

    class Dialog(QDialog):
        def reject(self) -> None:
            if worker.isRunning():
                cancelled.set()
                status.setText("Zatrzymuję przygotowanie. Poczekaj na zakończenie bieżącego kroku.")
                button.setEnabled(False)
            else:
                super().reject()

    dialog = Dialog()
    dialog.setWindowTitle("Signum — przygotowanie lokalnego AI")
    dialog.resize(700, 470)
    layout = QVBoxLayout(dialog)
    intro = QLabel(
        "Pobieram wybrane w instalatorze programy, biblioteki i modele innych autorów.\n"
        f"Katalog: {options.ai_directory}\n"
        "Składniki: " + ", ".join(MODELS.get(c, c) for c in sorted(components)) + "\n"
        "Już działająca Ollama zachowuje swój katalog modeli.\n"
        "Duże pliki mogą pobierać się kilkanaście minut."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)
    sources = QLabel(
        'Źródła i licencje: <a href="https://github.com/ollama/ollama">Ollama</a> · '
        '<a href="https://ollama.com/library/gemma4">Gemma</a> · '
        '<a href="https://huggingface.co/yah01/vjev-vision">Jev</a> · '
        '<a href="https://www.python.org/downloads/">Python</a> · '
        '<a href="https://pytorch.org/">PyTorch</a> · '
        '<a href="https://github.com/huggingface/transformers">Transformers</a>'
    )
    sources.setOpenExternalLinks(True)
    layout.addWidget(sources)
    status = QLabel("Rozpoczynam przygotowanie…")
    status.setWordWrap(True)
    layout.addWidget(status)
    bar = QProgressBar()
    bar.setRange(0, 0)
    layout.addWidget(bar)
    messages = QPlainTextEdit()
    messages.setReadOnly(True)
    messages.setMaximumBlockCount(300)
    layout.addWidget(messages)
    log_button = QPushButton("Otwórz szczegółowy log")
    log_button.clicked.connect(lambda: QDesktopServices.openUrl(
        QUrl.fromLocalFile(str(Path(options.ai_directory) / "setup.log")),
    ))
    layout.addWidget(log_button)
    button = QPushButton("Anuluj przygotowanie")
    button.clicked.connect(dialog.reject)
    layout.addWidget(button)
    retry_button = QPushButton("Spróbuj ponownie")
    retry_button.hide()
    layout.addWidget(retry_button)
    worker = Worker(dialog)
    last_message = [""]
    success = [False]

    def progress(text: str, percent: int) -> None:
        status.setText(text)
        bar.setRange(0, 100 if percent >= 0 else 0)
        if percent >= 0:
            bar.setValue(percent)
        if text != last_message[0]:
            messages.appendPlainText(text)
            last_message[0] = text

    def outcome(ok: bool, message: str) -> None:
        success[0] = ok
        status.setText(message)
        messages.appendPlainText(message)
        bar.setRange(0, 100)
        bar.setValue(100 if ok else 0)
        button.setText("Zamknij")
        button.setEnabled(True)
        retry_button.setVisible(not ok)

    def retry() -> None:
        cancelled.clear()
        retry_button.hide()
        button.setText("Anuluj przygotowanie")
        status.setText("Ponawiam przygotowanie…")
        bar.setRange(0, 0)
        worker.start()

    worker.progress.connect(progress)
    worker.outcome.connect(outcome)
    retry_button.clicked.connect(retry)
    QTimer.singleShot(0, worker.start)
    dialog.exec()
    worker.wait()
    return 0 if success[0] else 1
