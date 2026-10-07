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
from dataclasses import replace
from pathlib import Path

import requests
from PIL import Image

from signum.config import AppConfig
from signum.local_components import (
    THIRD_PARTY_NOTICE,
    find_ollama,
    jevk5_files,
    probe_runtime,
    repair_instructions,
    require_nvidia_gpu,
)
from signum.network import is_loopback_endpoint

OLLAMA_VERSION = "0.35.1"
MODEL_REPO = "yah01/vjev-vision"
MODEL_REVISION = "2fa8b58e40e5bc351a7d6dd39b953469a8f3ded2"
VJEV_REVISION = "37e2ffb2695b9bf278374fdefec24611c3b710c1"
MODELS = {"ollama\\small": "gemma4:e2b", "ollama\\large": "gemma4:12b"}
JEVK5_REPO = "alibiserikbay/JevK5"
JEVK5_REVISION = "c4f7fdb3aeab5582336406e78d3bef11bf98833d"
JEVK5_SOURCE = "f26426d16f59e8bbe1470e5b162cc89329e29b29"
VALID_COMPONENTS = {"app", "ollama", "jev", "jevk5", *MODELS}
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
    needed_gb = 35 * len(components & {"jev", "jevk5"})
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
        self,
        root: Path,
        progress: Progress,
        cancelled: threading.Event,
        existing_ollama: str = "",
        existing_ollama_url: str = "",
        *,
        repair: bool = False,
        custom_model: str = "",
        check_only: bool = False,
    ) -> None:
        self.repair = repair
        self.custom_model = custom_model.strip()
        self.check_only = check_only
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
        for key in (
            "PYTHONHOME",
            "PYTHONPATH",
            "_PYI_APPLICATION_HOME_DIR",
            "_PYI_PARENT_PROCESS_LEVEL",
        ):
            env.pop(key, None)
        for key in list(env):
            if key.startswith("PIP_"):
                env.pop(key)
        temporary = self.root / "temp"
        temporary.mkdir(exist_ok=True)
        env.update(
            {
                "TEMP": str(temporary),
                "TMP": str(temporary),
                "PYTHONUTF8": "1",
                "PIP_CACHE_DIR": str(self.root / "cache" / "pip"),
                "HF_HOME": str(self.root / "cache" / "huggingface"),
            }
        )
        env["PIP_CONFIG_FILE"] = os.devnull
        env["PIP_INDEX_URL"] = "https://pypi.org/simple"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env.pop("PIP_EXTRA_INDEX_URL", None)
        # Keep the packaged GUI's DLL directory out of external Python/Ollama.
        if os.name == "nt":
            import ctypes  # noqa: PLC0415

            ctypes.windll.kernel32.SetDllDirectoryW(None)
        with self.log.open("ab") as log:
            try:
                process = subprocess.Popen(
                    arguments,
                    cwd=self.root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            finally:
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
                with self.log.open("rb") as stream:
                    stream.seek(max(0, self.log.stat().st_size - 2500))
                    detail = stream.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Instalacja bibliotek nie powiodła się. Log: {self.log}\n{detail}"
                )

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
            runtime_path = (
                Path(config.ollama_runtime_dir)
                if config.ollama_runtime_dir
                else self.root / "ollama"
            )
            if self.existing_ollama and not self.check_only:
                executable = Path(self.existing_ollama)
                if (
                    executable.is_file()
                    and executable.resolve() != (runtime_path / "ollama.exe").resolve()
                ):
                    runtime_path = self.root / "ollama-launcher"
                    runtime_path.mkdir(parents=True, exist_ok=True)
                    (runtime_path / "runtime.json").write_text(
                        json.dumps({"external_executable": str(executable)}),
                        encoding="utf-8",
                    )
            try:
                start_local_ollama(url, str(runtime_path))
            except Exception:
                if self.check_only:
                    raise
                self.check_cancelled()
                runtime_path = self.root / "ollama"
                self.install_ollama(runtime_path)
                start_local_ollama(url, str(runtime_path))
            runtime = str(runtime_path)
        installed = OllamaVisionModel.list_models(url)
        selected = [model for key, model in MODELS.items() if key in components]
        if self.custom_model and self.custom_model not in selected:
            selected.append(self.custom_model)
        for model in selected:
            if model not in installed and self.check_only:
                raise ValueError(f"Brak modelu {model}. Użyj Instaluj / napraw.")
            if (model not in installed or self.repair) and not self.check_only:
                self.status(f"Pobieram {model}. Pobieranie może potrwać kilkanaście minut.")
                with local.post(
                    f"{url}/api/pull",
                    json={"model": model, "stream": True},
                    stream=True,
                    timeout=(20, 120),
                ) as response:
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
                        self.status(
                            f"{model}: {item.get('status', '')}",
                            min(100, completed * 100 // total) if total else -1,
                        )
            self.status(f"Sprawdzam model {model}.")
            if model in MODELS.values():
                client = OllamaVisionModel(url, model)
                try:
                    client.check_connection()
                    analysis = client.analyze_image(Image.new("RGB", (320, 400), "white"), 1120)
                    if analysis.signatures:
                        raise RuntimeError(f"{model} wskazał podpis na pustym obrazie testowym")
                finally:
                    client.release_resources()
            from signum.ai.text_classifiers import GemmaTextClassifier  # noqa: PLC0415
            from signum.core.classification import make_question  # noqa: PLC0415

            text_client = GemmaTextClassifier(
                replace(
                    config,
                    classification_ollama_url=url,
                    classification_ollama_model=model,
                    ollama_runtime_dir=runtime,
                ),
                api_key="",
            )
            try:
                answer = text_client.classify(
                    "Agreement for delivery of goods.",
                    make_question(
                        [("Agreement", "A contract."), ("Other", "Other documents.")],
                        "Choose the document type.",
                    ),
                )
                if answer.get("choice") not in {"c01", "c02"}:
                    raise ValueError("Model nie zwrócił poprawnej kategorii.")
            finally:
                text_client.close()
            if not self.check_only:
                self.register_ollama(config, url, model)
                if model in MODELS.values():
                    config.ollama_model = model
        if not self.check_only:
            config.ollama_url = url
            config.ollama_runtime_dir = runtime
            config.ai_directory = str(self.root)
            config.classification_cache_dir = str(self.root / "cache/classification")
            config.provider = "ollama"
            config.save()

    def install_ollama(self, runtime_path: Path) -> None:
        validate_storage(str(self.root), {"ollama"})
        self.status("Pobieram Ollamę z oficjalnego wydania GitHub.")
        response = self.session.get(
            f"https://api.github.com/repos/ollama/ollama/releases/tags/v{OLLAMA_VERSION}",
            timeout=30,
        )
        response.raise_for_status()
        asset = next(
            a for a in response.json()["assets"] if a["name"] == "ollama-windows-amd64.zip"
        )
        checksum = str(asset.get("digest") or "").removeprefix("sha256:")
        if len(checksum) != 64:
            raise ValueError("Wydanie Ollamy nie udostępnia sumy SHA-256")
        archive = self.download(
            asset["browser_download_url"], self.downloads / asset["name"], checksum
        )
        self.status("Rozpakowuję Ollamę i biblioteki obsługi GPU.")
        _safe_extract(archive, runtime_path)
        # This is our managed launcher metadata, never external program files.
        manifest = runtime_path / "runtime.json"
        if manifest.is_file():
            manifest.rename(runtime_path / f"runtime-backup-{time.time_ns()}.json")

    @staticmethod
    def register_ollama(config: AppConfig, url: str, model: str) -> None:
        from signum.ai.model_profiles import (  # noqa: PLC0415
            ModelProfile,
            dump_profiles,
            load_profiles,
        )

        profiles = load_profiles(config) if config.classification_models else []
        if not any(p.provider == "ollama" and p.model == model and p.url == url for p in profiles):
            profiles.append(
                ModelProfile(
                    id="ollama-" + hashlib.sha256((url + model).encode()).hexdigest()[:12],
                    url=url,
                    model=model,
                )
            )
        config.classification_models = dump_profiles(profiles)
        config.classification_ollama_url = url
        config.classification_ollama_model = model

    def python_runtime(self, runtime: Path, kind: str) -> tuple[Path, Path]:
        require_nvidia_gpu()
        validate_storage(str(self.root), {kind})
        runtime.mkdir(parents=True, exist_ok=True)
        python_root = runtime / "python"
        python = python_root / "python.exe"
        packages = runtime / "packages"
        packages.mkdir(exist_ok=True)
        self.status(f"Przygotowuję Python i biblioteki: {kind}.")
        archive = self.download(
            "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip",
            self.downloads / "python-3.11.9-embed-amd64.zip",
        )
        _safe_extract(archive, python_root)
        (python_root / "python311._pth").write_text(
            f"python311.zip\n.\nLib/site-packages\n{packages}\nimport site\n",
            encoding="utf-8",
        )
        bootstrap = self.download(
            "https://bootstrap.pypa.io/get-pip.py", self.downloads / "get-pip.py"
        )
        self.run_process(
            [
                str(python),
                str(bootstrap),
                "pip==25.1.1",
                "setuptools==80.9.0",
                "wheel==0.45.1",
                "hatchling==1.31.0",
                "--no-cache-dir",
            ]
        )
        self.run_process(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--target",
                str(packages),
                "--upgrade",
                "--no-cache-dir",
                "--index-url",
                "https://download.pytorch.org/whl/cu128",
                "torch==2.11.0",
                "torchvision==0.26.0",
            ]
        )
        # Pin the integration; dependencies must not replace the selected CUDA Torch.
        source_repo = "BubbleCal/vjev-serve" if kind == "jev" else "allebee/jevk5"
        revision = VJEV_REVISION if kind == "jev" else JEVK5_SOURCE
        source = self.download(
            f"https://github.com/{source_repo}/archive/{revision}.zip",
            self.downloads / f"{kind}-{revision}.zip",
        )
        self.run_process(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--target",
                str(packages),
                "--upgrade",
                "--no-cache-dir",
                "--no-deps",
                "--no-build-isolation",
                str(source),
            ]
        )
        self.run_process(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--target",
                str(packages),
                "--upgrade",
                "--no-cache-dir",
                "--index-url",
                "https://pypi.org/simple",
                "transformers==5.18.0",
                "huggingface_hub==1.33.0",
                "pillow==12.2.0",
                "safetensors==0.8.0",
            ]
        )
        return python, packages

    def download_model(self, repo: str, revision: str, model_dir: Path) -> None:
        self.status(f"Sprawdzam i pobieram pliki modelu {repo}.")
        metadata = self.session.get(
            f"https://huggingface.co/api/models/{repo}/revision/{revision}",
            params={"blobs": "true"},
            timeout=30,
        )
        metadata.raise_for_status()
        for item in metadata.json()["siblings"]:
            name = item["rfilename"]
            if Path(name).suffix not in {".json", ".safetensors", ".pt", ".jinja", ".txt"}:
                continue
            if Path(name).is_absolute() or ".." in Path(name).parts or ":" in name:
                raise ValueError("Niepoprawna ścieżka pliku modelu")
            checksum = (item.get("lfs") or {}).get("sha256", "")
            if Path(name).suffix in {".safetensors", ".pt"} and len(checksum) != 64:
                raise ValueError(f"Brak sumy SHA-256 dla wag {name}; pobieranie wstrzymane.")
            self.download(
                f"https://huggingface.co/{repo}/resolve/{revision}/{name}",
                model_dir / name,
                checksum,
            )

    def check_jev(self, runtime: Path) -> None:
        from signum.ai.jev_client import JevVisionModel  # noqa: PLC0415
        from signum.ai.local_vjev import _runtime_paths  # noqa: PLC0415

        _, python, packages, model = _runtime_paths(str(runtime))
        self.status(
            probe_runtime(
                "jev",
                str(python),
                str(packages),
                str(model),
                "",
                self.root / "temp",
                self.cancelled,
            )
        )
        self.status("Ładuję Jev i sprawdzam analizę obrazu.")
        client = JevVisionModel(
            base_url="http://127.0.0.1:8800/v1",
            model="vjev-vision",
            api_key="",
            timeout_s=300,
            runtime_dir=str(runtime),
        )
        try:
            client.check_connection()
            analysis = client.analyze_image(Image.new("RGB", (320, 400), "white"), 1120)
            if analysis.signature_probability is None or analysis.signatures:
                raise RuntimeError("Jev nie przeszedł sprawdzenia na pustym obrazie")
        finally:
            client.release_resources()

    def prepare_jev(self, config: AppConfig) -> None:
        runtime = Path(config.vjev_runtime_dir) if config.vjev_runtime_dir else self.root / "jev"
        try:
            self.check_jev(runtime)
        except SetupCancelledError:
            raise
        except Exception as exc:
            if self.check_only or any(
                term in str(exc).lower()
                for term in (
                    "out of memory",
                    "cuda niedostępna",
                    "16 gb",
                    "driver",
                    "kernel image",
                )
            ):
                raise
            self.status(f"Jev wymaga przygotowania: {exc}")
            runtime = self.root / "jev"
            python, packages = self.python_runtime(runtime, "jev")
            model_dir = runtime / "models/vjev-vision"
            self.download_model(MODEL_REPO, MODEL_REVISION, model_dir)
            (runtime / "runtime.json").write_text(
                json.dumps(
                    {
                        "python": str(python),
                        "packages": str(packages),
                        "model_dir": str(model_dir),
                        "model_repo": MODEL_REPO,
                        "model_revision": MODEL_REVISION,
                        "vjev_revision": VJEV_REVISION,
                        "device": "cuda",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            self.check_jev(runtime)
        if not self.check_only:
            config.vjev_runtime_dir = str(runtime)
            config.vjev_base_url = "http://127.0.0.1:8800/v1"
            config.vjev_model = "vjev-vision"
            config.save()

    def check_jevk5(self, config: AppConfig) -> None:
        from signum.ai.text_classifiers import JevK5TextClassifier  # noqa: PLC0415
        from signum.core.classification import make_question  # noqa: PLC0415

        jevk5_files(config)
        self.status(
            probe_runtime(
                "jevk5",
                config.classification_jev_python,
                config.classification_jev_packages,
                config.classification_jev_model_dir,
                config.classification_jev_runtime,
                self.root / "temp",
                self.cancelled,
            )
        )
        self.status("Ładuję JevK5 i sprawdzam kategoryzację.")
        client = JevK5TextClassifier(config, self.cancelled)
        try:
            answer = client.classify(
                "Agreement for delivery of goods.",
                make_question(
                    [("Agreement", "A contract."), ("Other", "Other documents.")],
                    "Choose the document type.",
                ),
            )
            if answer.get("choice") not in {"c01", "c02"}:
                raise ValueError("JevK5 nie zwrócił poprawnej kategorii.")
        finally:
            client.close()

    def prepare_jevk5(self, config: AppConfig) -> None:
        candidate = replace(config)
        manifest = self.root / "jevk5/runtime.json"
        if not candidate.classification_jev_python and manifest.is_file():
            try:
                saved = json.loads(manifest.read_text(encoding="utf-8"))
                for field, key in (
                    ("python", "python"),
                    ("packages", "packages"),
                    ("model_dir", "model_dir"),
                    ("runtime", "runtime"),
                ):
                    setattr(candidate, "classification_jev_" + field, saved[key])
            except (OSError, ValueError, KeyError, TypeError):
                pass
        try:
            self.check_jevk5(candidate)
        except SetupCancelledError:
            raise
        except Exception as exc:
            if self.check_only or any(
                term in str(exc).lower()
                for term in (
                    "out of memory",
                    "cuda niedostępna",
                    "16 gb",
                    "driver",
                    "kernel image",
                )
            ):
                raise
            self.status(f"JevK5 wymaga przygotowania: {exc}")
            runtime = self.root / "jevk5"
            python, packages = self.python_runtime(runtime, "jevk5")
            model_dir = runtime / "models/JevK5"
            self.download_model(JEVK5_REPO, JEVK5_REVISION, model_dir)
            candidate = replace(
                config,
                classification_jev_python=str(python),
                classification_jev_packages=str(packages),
                classification_jev_model_dir=str(model_dir),
                classification_jev_runtime=str(packages),
                classification_cache_dir=str(self.root / "cache/classification"),
            )
            self.check_jevk5(candidate)
            manifest.write_text(
                json.dumps(
                    {
                        "python": str(python),
                        "packages": str(packages),
                        "runtime": str(packages),
                        "model_dir": str(model_dir),
                        "model_revision": JEVK5_REVISION,
                        "source_revision": JEVK5_SOURCE,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        if not self.check_only:
            from signum.ai.model_profiles import (  # noqa: PLC0415
                ModelProfile,
                dump_profiles,
                load_profiles,
            )

            old_paths = (config.classification_jev_python, config.classification_jev_model_dir)
            for name in ("python", "packages", "runtime", "model_dir"):
                setattr(
                    config,
                    "classification_jev_" + name,
                    getattr(candidate, "classification_jev_" + name),
                )
            profiles = load_profiles(config) if config.classification_models else []
            matches = [
                p
                for p in profiles
                if p.provider == "jevk5"
                and ((p.python, p.model_dir) == old_paths or p.id == "installed-jevk5")
            ]
            if not matches:
                profile = ModelProfile(id="installed-jevk5", provider="jevk5", name="JevK5")
                profiles.append(profile)
                matches = [profile]
            for profile in matches:
                profile.python = candidate.classification_jev_python
                profile.packages = candidate.classification_jev_packages
                profile.runtime = candidate.classification_jev_runtime
                profile.model_dir = candidate.classification_jev_model_dir
            config.classification_models = dump_profiles(profiles)
            config.save()

    def prepare(self, components: set[str]) -> None:
        config = AppConfig.load()
        if not self.check_only:
            config.ai_directory = str(self.root)
            config.classification_cache_dir = str(self.root / "cache/classification")
        if not self.existing_ollama:
            self.existing_ollama = find_ollama(config)
        failures = []
        for kind in ("ollama", "jev", "jevk5"):
            if kind not in components:
                continue
            try:
                if kind == "ollama":
                    self.prepare_ollama(components, config)
                elif kind == "jev":
                    self.prepare_jev(config)
                else:
                    self.prepare_jevk5(config)
                self.status(f"{kind}: test zakończony poprawnie.")
            except SetupCancelledError:
                raise
            except Exception as exc:
                self.check_cancelled()
                message = repair_instructions(str(exc), kind)
                failures.append(f"{kind}: {message}")
                self.status(failures[-1])
        if failures:
            raise RuntimeError("\n\n".join(failures))
        if not self.check_only:
            if "jev" in components and "ollama" not in components:
                config.provider = "vjev"
            config.save()
        self.status("Wybrane składniki przeszły test działania.", 100)


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
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--ollama-model", default="")
    options = parser.parse_args(arguments)
    components = parse_components(options.ai_components)
    cancelled = threading.Event()

    class Worker(QThread):
        progress = Signal(str, int)
        outcome = Signal(bool, str)

        def run(self) -> None:
            try:
                root = validate_storage(options.ai_directory, set())
                LocalAIPreparer(
                    root,
                    self.progress.emit,
                    cancelled,
                    options.existing_ollama,
                    options.existing_ollama_url,
                    repair=options.repair,
                    custom_model=options.ollama_model,
                    check_only=options.check_only,
                ).prepare(components)
            except Exception as exc:
                self.outcome.emit(False, repair_instructions(str(exc)))
            else:
                self.outcome.emit(True, "Testy zakończone. Wybrane składniki działają.")

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
        (
            "Sprawdzam wybrane składniki.\n"
            if options.check_only
            else "Przygotowuję wybrane programy, biblioteki i modele.\n"
        )
        + f"Katalog: {options.ai_directory}\n"
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
        '<a href="https://huggingface.co/alibiserikbay/JevK5">JevK5</a> · '
        '<a href="https://www.python.org/downloads/">Python</a> · '
        '<a href="https://pytorch.org/">PyTorch</a> · '
        '<a href="https://github.com/huggingface/transformers">Transformers</a>'
    )
    sources.setOpenExternalLinks(True)
    layout.addWidget(sources)
    notice = QLabel(THIRD_PARTY_NOTICE)
    notice.setWordWrap(True)
    layout.addWidget(notice)
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
    log_button.clicked.connect(
        lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(options.ai_directory) / "setup.log")),
        )
    )
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
        status.setText(text.splitlines()[0][:180])
        bar.setRange(0, 100 if percent >= 0 else 0)
        if percent >= 0:
            bar.setValue(percent)
        if text != last_message[0]:
            messages.appendPlainText(text)
            last_message[0] = text

    def outcome(ok: bool, message: str) -> None:
        success[0] = ok
        status.setText(
            "Wybrane składniki działają." if ok else "Nie udało się zakończyć. Instrukcje poniżej."
        )
        messages.appendPlainText(message)
        bar.setRange(0, 100)
        bar.setValue(100 if ok else 0)
        button.setText("Zamknij")
        button.setEnabled(True)
        retry_button.setVisible(not ok)
        retry_button.setEnabled(False)

    def retry() -> None:
        cancelled.clear()
        retry_button.hide()
        button.setText("Anuluj przygotowanie")
        status.setText("Ponawiam przygotowanie…")
        bar.setRange(0, 0)
        worker.start()

    worker.progress.connect(progress)
    worker.outcome.connect(outcome)
    worker.finished.connect(lambda: retry_button.setEnabled(True))
    retry_button.clicked.connect(retry)
    QTimer.singleShot(0, worker.start)
    dialog.exec()
    worker.wait()
    return 0 if success[0] else 1
