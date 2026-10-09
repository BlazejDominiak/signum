"""Optional third-party AI preparation. Only explicitly selected components are fetched."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
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
        self.completed_components: set[str] = set()
        self.verified_models: set[str] = set()
        self.component_results: dict[str, str] = {}
        self.ollama_model_directory = ""
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
        metadata = partial.with_suffix(partial.suffix + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = {}
        with contextlib.suppress(OSError, ValueError):
            stored = json.loads(metadata.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                previous = stored
        validator = previous.get("validator", "") if previous.get("url") == url else ""
        offset = partial.stat().st_size if partial.exists() and (expected_hash or validator) else 0
        headers = {"Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
            if validator:
                headers["If-Range"] = validator
        digest = hashlib.sha256()
        with self.session.get(url, headers=headers, stream=True, timeout=(20, 60)) as response:
            # A complete partial can remain after interruption just before renaming.
            if response.status_code == 416 and expected_hash and offset:
                with partial.open("rb") as cached:
                    complete = hashlib.file_digest(cached, "sha256").hexdigest() == expected_hash
                if complete:
                    partial.replace(target)
                    metadata.unlink(missing_ok=True)
                    return target
                partial.unlink(missing_ok=True)
                metadata.unlink(missing_ok=True)
                raise ValueError("Nieaktualna część pliku — ponów pobieranie")
            response.raise_for_status()
            if response.status_code == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",
                                     response.headers.get("Content-Range", ""))
                if not match or int(match[1]) != offset or int(match[2]) < offset:
                    raise ValueError("Serwer zwrócił niepoprawny zakres pobierania")
                total = int(match[3])
                if int(match[2]) + 1 != total:
                    raise ValueError("Niepełny zakres odpowiedzi serwera")
            else:
                offset = 0  # Server ignored Range or If-Range no longer matches.
                total = int(response.headers.get("Content-Length", 0))
            current_validator = (
                response.headers.get("ETag") or response.headers.get("Last-Modified")
            )
            if (response.status_code == 206 and validator and current_validator
                    and current_validator != validator and not expected_hash):
                raise ValueError("Źródło pliku zmieniło się; ponów pobieranie od początku")
            if current_validator and current_validator.startswith("W/"):
                current_validator = response.headers.get("Last-Modified", "")
            metadata.write_text(json.dumps({"url": url, "validator": current_validator or ""}),
                                encoding="utf-8")
            if offset:
                with partial.open("rb") as cached:
                    while chunk := cached.read(1024 * 1024):
                        self.check_cancelled()
                        digest.update(chunk)
            downloaded = offset
            last_update = 0.0
            with partial.open("ab" if offset else "wb") as file:
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
                file.flush()
                os.fsync(file.fileno())
        if total and downloaded != total:
            raise ValueError(f"Niepełne pobranie pliku {target.name}; ponów pobieranie")
        if expected_hash and digest.hexdigest() != expected_hash:
            partial.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            raise ValueError(f"Niepoprawna suma kontrolna pliku {target.name}")
        partial.replace(target)
        metadata.unlink(missing_ok=True)
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
        from signum.ai.local_ollama import (  # noqa: PLC0415
            managed_model_directory,
            start_local_ollama,
        )
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
        missing = [m for m in selected if m not in self.verified_models
                   and (m not in installed or self.repair)]
        if missing and not self.check_only:
            model_root = managed_model_directory(url)
            if model_root is None:
                if not self.ollama_model_directory:
                    raise ValueError(
                        "Ollama nie udostępnia ścieżki swojego magazynu. Wskaż folder modeli "
                        "w Składniki AI → Szczegóły instalacji lub przez --ollama-model-directory."
                    )
                model_root = Path(self.ollama_model_directory)
            if not model_root.is_absolute():
                raise ValueError("Folder modeli Ollamy musi mieć pełną ścieżkę")
            self.status(f"Folder modeli Ollamy: {model_root}")
            check_root = model_root
            while not check_root.exists() and check_root.parent != check_root:
                check_root = check_root.parent
            needed = sum(8 if m == "gemma4:e2b" else 20 for m in missing) * 1024**3
            if shutil.disk_usage(check_root).free < needed:
                raise ValueError(f"Za mało miejsca w {model_root}: potrzeba {needed // 1024**3} GB")
        for model in selected:
            if model in self.verified_models:
                continue
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
                text_client.check_connection()
            finally:
                text_client.close()
            self.verified_models.add(model)
            if not self.check_only:
                self.register_ollama(config, url, model)
                if model in MODELS.values():
                    config.ollama_model = model
                config.ollama_url = url
                config.ollama_runtime_dir = runtime
                config.save()
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
        self.status("Ładuję JevK5 i sprawdzam odpowiedź modelu.")
        client = JevK5TextClassifier(config, self.cancelled)
        try:
            client.check_connection()
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
        if self.ollama_model_directory and not self.check_only:
            config.ollama_models_directory = self.ollama_model_directory
        if not self.check_only:
            config.ai_directory = str(self.root)
            config.classification_cache_dir = str(self.root / "cache/classification")
        if not self.existing_ollama:
            self.existing_ollama = find_ollama(config)
        failures = []
        for kind in ("ollama", "jev", "jevk5"):
            if kind not in components or kind in self.completed_components:
                continue
            try:
                if kind == "ollama":
                    self.prepare_ollama(components, config)
                elif kind == "jev":
                    self.prepare_jev(config)
                else:
                    self.prepare_jevk5(config)
                self.status(f"{kind}: test zakończony poprawnie.")
                self.completed_components.add(kind)
                self.component_results[kind] = "ready"
            except SetupCancelledError:
                raise
            except Exception as exc:
                self.check_cancelled()
                message = repair_instructions(str(exc), kind)
                self.component_results[kind] = message
                failures.append(f"{kind}: {message}")
                self.status(failures[-1])
        if failures:
            raise RuntimeError("\n\n".join(failures))
        if not self.check_only:
            if "jev" in components and "ollama" not in components:
                config.provider = "vjev"
            config.save()
        self.status("Wybrane składniki przeszły test działania.", 100)


def perform_setup(
    preparer: LocalAIPreparer, components: set[str], result_file: Path | None = None,
) -> tuple[bool, str]:
    try:
        preparer.prepare(components)
    except Exception as exc:
        ok, message = False, repair_instructions(str(exc))
    else:
        ok, message = True, "Wybrane składniki działają."
    target = result_file or preparer.root / "setup-result.json"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "success": ok, "message": message, "components": preparer.component_results,
            "models": sorted(preparer.verified_models),
            "directory": str(preparer.root), "time": time.time(),
        }, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
    except OSError as exc:
        return False, f"Nie zapisano wyniku przygotowania: {exc}"
    return ok, message


def run_setup_dialog(arguments: list[str]) -> int:
    # GUI stays lightweight: preparation happens in a separate worker thread.
    from PySide6.QtCore import QThread, QTimer, QUrl, Signal  # noqa: PLC0415
    from PySide6.QtGui import QDesktopServices  # noqa: PLC0415
    from PySide6.QtWidgets import (  # noqa: PLC0415
        QDialog,
        QHBoxLayout,
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
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--result-file", default="")
    parser.add_argument("--language", choices=("pl", "en"), default="pl")
    parser.add_argument("--ollama-model-directory", default="")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--ollama-model", default="")
    options = parser.parse_args(arguments)
    components = parse_components(options.ai_components)
    cancelled = threading.Event()
    def tr(pl: str, en: str) -> str:
        return en if options.language == "en" else pl

    result_file = Path(options.result_file) if options.result_file else None

    def create_preparer(progress: Progress) -> LocalAIPreparer:
        root = validate_storage(options.ai_directory, set())
        preparer = LocalAIPreparer(
            root, progress, cancelled, options.existing_ollama, options.existing_ollama_url,
            repair=options.repair, custom_model=options.ollama_model, check_only=options.check_only,
        )
        preparer.ollama_model_directory = (
            options.ollama_model_directory or AppConfig.load().ollama_models_directory
        )
        return preparer

    def creation_failed(exc: Exception) -> str:
        message = repair_instructions(str(exc))
        if result_file:
            try:
                result_file.parent.mkdir(parents=True, exist_ok=True)
                result_file.write_text(json.dumps({
                    "success": False, "message": message, "components": {},
                    "directory": options.ai_directory, "time": time.time(),
                }, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        return message

    if options.headless:
        try:
            preparer = create_preparer(lambda text, percent: None)
            ok, _ = perform_setup(preparer, components, result_file)
            return 0 if ok else 1
        except Exception as exc:
            creation_failed(exc)
            return 1

    class Worker(QThread):
        progress = Signal(str, int)
        outcome = Signal(bool, str)

        preparer: LocalAIPreparer | None = None

        def run(self) -> None:
            try:
                if self.preparer is None:
                    self.preparer = create_preparer(self.progress.emit)
                ok, message = perform_setup(self.preparer, components, result_file)
                self.outcome.emit(ok, message)
            except Exception as exc:
                self.outcome.emit(False, creation_failed(exc))

    class Dialog(QDialog):
        def reject(self) -> None:
            if worker.isRunning():
                cancelled.set()
                status.setText("Zatrzymuję przygotowanie. Poczekaj na zakończenie bieżącego kroku.")
                button.setEnabled(False)
            else:
                super().reject()

    from signum.ui.theme import SIGNUM_STYLE  # noqa: PLC0415

    dialog = Dialog()
    dialog.setStyleSheet(SIGNUM_STYLE)
    dialog.setWindowTitle(tr("Signum — przygotowanie lokalnego AI", "Signum — local AI setup"))
    dialog.resize(720, 300)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(10)
    heading = QLabel(tr("Przygotowanie AI", "AI setup"))
    heading.setProperty("role", "title")
    layout.addWidget(heading)
    intro = QLabel(f"Folder: {options.ai_directory}")
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
    sources.hide()
    notice = QLabel(THIRD_PARTY_NOTICE)
    notice.setWordWrap(True)
    layout.addWidget(notice)
    notice.hide()
    status = QLabel(tr("Rozpoczynam przygotowanie…", "Preparing…"))
    status.setWordWrap(True)
    layout.addWidget(status)
    bar = QProgressBar()
    bar.setRange(0, 0)
    layout.addWidget(bar)
    messages = QPlainTextEdit()
    messages.setReadOnly(True)
    messages.setMaximumBlockCount(300)
    layout.addWidget(messages)
    messages.hide()
    details = QPushButton(tr("Szczegóły", "Details"))
    details.setCheckable(True)
    def show_details(visible: bool) -> None:
        for widget in (messages, sources, notice):
            widget.setVisible(visible)
    details.toggled.connect(show_details)
    layout.addStretch(1)
    actions = QHBoxLayout()
    actions.addWidget(details)
    details.setProperty("role", "quiet")
    log_button = QPushButton(tr("Otwórz szczegółowy log", "Open log"))
    log_button.clicked.connect(
        lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(options.ai_directory) / "setup.log")),
        )
    )
    actions.addWidget(log_button)
    log_button.setProperty("role", "quiet")
    actions.addStretch()
    button = QPushButton(tr("Anuluj przygotowanie", "Cancel setup"))
    button.clicked.connect(dialog.reject)
    actions.addWidget(button)
    retry_button = QPushButton(tr("Spróbuj ponownie", "Retry failed components"))
    retry_button.hide()
    actions.insertWidget(3, retry_button)
    retry_button.setProperty("role", "primary")
    layout.addLayout(actions)
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
            tr("Wybrane składniki działają.", "Selected components are ready.") if ok
            else tr("Nie udało się zakończyć. Zobacz szczegóły.", "Setup incomplete. See details.")
        )
        messages.appendPlainText(message)
        if not ok:
            details.setChecked(True)
        bar.setRange(0, 100)
        bar.setValue(100 if ok else 0)
        button.setText(tr("Zamknij", "Close"))
        button.setEnabled(True)
        retry_button.setVisible(not ok)
        retry_button.setEnabled(False)

    def retry() -> None:
        cancelled.clear()
        retry_button.hide()
        button.setText(tr("Anuluj przygotowanie", "Cancel setup"))
        status.setText(tr("Ponawiam przygotowanie…", "Retrying…"))
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
