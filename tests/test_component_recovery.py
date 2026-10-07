from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from signum.ai.model_profiles import ModelProfile, dump_profiles, load_profiles
from signum.config import AppConfig, default_ai_directory
from signum.local_components import jevk5_files, repair_instructions
from signum.setup_local_ai import LocalAIPreparer, parse_components


def test_fresh_install_does_not_require_h_drive(monkeypatch, tmp_path) -> None:
    original = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda p: False if str(p) == "H:\\" else original(p))
    monkeypatch.setattr("signum.config.platformdirs.user_documents_dir", lambda: str(tmp_path))
    config = AppConfig()
    assert default_ai_directory() == tmp_path / "SignumAI"
    assert config.classification_cache_dir == str(tmp_path / "SignumAI/cache/classification")
    assert config.classification_jev_python == ""
    assert config.classification_env_file == ""
    assert all("Users/B" not in str(value) for value in asdict(config).values())


def test_missing_drive_in_saved_configuration_is_migrated(isolated_config, monkeypatch) -> None:
    original = Path.exists
    monkeypatch.setattr(Path, "exists", lambda p: False if str(p) == "Z:\\" else original(p))
    isolated_config.parent.mkdir(parents=True)
    isolated_config.write_text(
        json.dumps(
            {
                "classification_cache_dir": "Z:/Temp/cache",
                "classification_jev_python": "Z:/Python/python.exe",
            }
        )
    )
    config = AppConfig.load()
    assert not config.classification_cache_dir.startswith("Z:")
    assert config.classification_jev_python == ""


def test_selected_small_model_does_not_add_uninstalled_large_model() -> None:
    config = AppConfig()
    LocalAIPreparer.register_ollama(config, "http://127.0.0.1:11434", "gemma4:e2b")
    assert [p.model for p in load_profiles(config)] == ["gemma4:e2b"]
    assert config.classification_ollama_model == "gemma4:e2b"
    LocalAIPreparer.register_ollama(config, "http://127.0.0.1:11434", "gemma4:e2b")
    assert len(load_profiles(config)) == 1


def test_adding_installed_model_preserves_user_api_profiles() -> None:
    config = AppConfig(
        classification_models=dump_profiles(
            [
                ModelProfile(
                    id="custom", provider="api", url="https://example.test/v1", model="chosen"
                ),
            ]
        )
    )
    LocalAIPreparer.register_ollama(config, "http://localhost:11434", "chosen:local")
    assert [p.model for p in load_profiles(config)] == ["chosen", "chosen:local"]


def test_fresh_jevk5_is_saved_only_after_real_model_check(tmp_path, isolated_config) -> None:
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.check_jevk5 = Mock(side_effect=[ValueError("missing"), None])
    python, packages = tmp_path / "jevk5/python/python.exe", tmp_path / "jevk5/packages"

    def provision(*args):
        packages.mkdir(parents=True)
        return python, packages

    preparer.python_runtime = Mock(side_effect=provision)
    preparer.download_model = Mock()
    config = AppConfig()
    preparer.prepare_jevk5(config)
    assert preparer.check_jevk5.call_count == 2
    stored = AppConfig.load()
    assert stored.classification_jev_python == str(python)
    assert load_profiles(stored)[0].provider == "jevk5"
    assert (tmp_path / "jevk5/runtime.json").is_file()


def test_broken_jevk5_does_not_publish_ready_manifest(tmp_path, isolated_config) -> None:
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.check_jevk5 = Mock(side_effect=ValueError("damaged weights"))
    preparer.python_runtime = Mock(return_value=(tmp_path / "python.exe", tmp_path / "packages"))
    preparer.download_model = Mock()
    with pytest.raises(ValueError, match="damaged"):
        preparer.prepare_jevk5(AppConfig())
    assert not isolated_config.exists()
    assert not (tmp_path / "jevk5/runtime.json").exists()


def test_healthy_external_jevk5_is_reused_without_download(tmp_path, isolated_config) -> None:
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.check_jevk5 = Mock()
    preparer.python_runtime = Mock(side_effect=AssertionError("must reuse"))
    config = AppConfig(
        classification_jev_python=str(tmp_path / "python.exe"),
        classification_jev_model_dir=str(tmp_path / "model"),
        classification_jev_packages=str(tmp_path / "packages"),
        classification_jev_runtime=str(tmp_path / "source"),
    )
    preparer.prepare_jevk5(config)
    assert load_profiles(AppConfig.load())[0].python == config.classification_jev_python


def test_check_only_never_installs_or_saves(tmp_path, isolated_config) -> None:
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event(), check_only=True)
    preparer.check_jevk5 = Mock(side_effect=ValueError("missing torch"))
    preparer.python_runtime = Mock(side_effect=AssertionError("must not install"))
    with pytest.raises(ValueError, match="missing torch"):
        preparer.prepare_jevk5(AppConfig())
    assert not isolated_config.exists()


def test_missing_libraries_detected_before_worker_is_started(tmp_path) -> None:
    config = AppConfig(classification_jev_python=str(tmp_path / "python.exe"))
    with pytest.raises(ValueError, match="bibliotek"):
        jevk5_files(config)


def test_unsupported_gpu_stops_before_any_download(tmp_path, monkeypatch) -> None:
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    preparer.download = Mock(side_effect=AssertionError("must not download"))
    monkeypatch.setattr(
        "signum.setup_local_ai.require_nvidia_gpu", Mock(side_effect=ValueError("NVIDIA required"))
    )
    with pytest.raises(ValueError, match="NVIDIA"):
        preparer.python_runtime(tmp_path / "jevk5", "jevk5")


@pytest.mark.parametrize(
    ("error", "provider", "instruction"),
    [
        ("CUDA out of memory", "jevk5", "mniejszy model"),
        ("CUDA unavailable", "jev", "sterownik"),
        ("DLL load failed: WinError 126", "jevk5", "vc_redist.x64.exe"),
        ("HTTP 401", "api", "klucz API"),
        ("No module named torch", "jevk5", "Instaluj / napraw"),
        ("disk full", "ollama", "wolnego miejsca"),
        ("HTTP 429", "api", "limit konta"),
        ("Model nie analizuje obrazów", "ollama", "obsługujący obrazy"),
        ("Przekroczono czas oczekiwania", "jevk5", "limit czasu"),
    ],
)
def test_errors_have_specific_recovery_steps(error, provider, instruction) -> None:
    message = repair_instructions(error, provider)
    assert message.startswith(error)
    assert instruction in message


def test_missing_components_dialog_opens_without_external_python(qtbot, isolated_config) -> None:
    from signum.ui.components_dialog import ComponentsDialog

    dialog = ComponentsDialog(AppConfig())
    qtbot.addWidget(dialog)
    assert "jevk5" in dialog.choices
    assert "niewykryta" in dialog.states["jevk5"].text()
    dialog._run(True)
    assert "Zaznacz" in dialog.result_label.text()


def test_jevk5_is_an_explicit_installer_component() -> None:
    assert parse_components("app,jevk5") == {"jevk5"}
    source = Path("installer/signum.iss").read_text(encoding="utf-8-sig")
    assert 'Name: "jevk5"' in source
    assert 'MinVersion=10.0.19045' in source
    assert "autor Signum nie bierze za nie odpowiedzialności" in source


def test_one_failed_component_does_not_skip_other_selected_checks(tmp_path, monkeypatch) -> None:
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event(), check_only=True)
    monkeypatch.setattr(AppConfig, "load", Mock(return_value=AppConfig()))
    preparer.prepare_jev = Mock(side_effect=ValueError("missing library"))
    preparer.prepare_jevk5 = Mock()
    with pytest.raises(RuntimeError, match="missing library"):
        preparer.prepare({"jev", "jevk5"})
    preparer.prepare_jevk5.assert_called_once()


def test_managed_python_explicitly_loads_site_packages(tmp_path, monkeypatch) -> None:
    preparer = LocalAIPreparer(tmp_path, Mock(), threading.Event())
    monkeypatch.setattr("signum.setup_local_ai.require_nvidia_gpu", Mock())
    monkeypatch.setattr(
        "signum.setup_local_ai.shutil.disk_usage", lambda _: SimpleNamespace(free=100 * 1024**3)
    )
    preparer.download = Mock(side_effect=lambda url, target, *args: target)
    preparer.run_process = Mock()
    monkeypatch.setattr(
        "signum.setup_local_ai._safe_extract", lambda archive, target: target.mkdir(parents=True)
    )
    python, packages = preparer.python_runtime(tmp_path / "jevk5", "jevk5")
    pth = (python.parent / "python311._pth").read_text()
    assert "Lib/site-packages" in pth
    assert str(packages) in pth
    assert any("--no-deps" in call.args[0] for call in preparer.run_process.call_args_list)
