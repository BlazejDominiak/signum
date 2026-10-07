"""Punkt wejścia aplikacji GUI."""

from __future__ import annotations

import ctypes
import logging
import sys
from importlib import resources

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from signum import APP_NAME, __version__
from signum.ui.main_window import MainWindow

_INSTANCE_MUTEX_NAME = "Local\\Signum-6D6C3F52-9C1B-4E6A-9A57-2B1FBD6A7E31"
_instance_mutex_handles: list[object] = []


def _load_icon() -> QIcon:
    try:
        icon_path = resources.files("signum.ui.resources") / "signum.ico"
        return QIcon(str(icon_path))
    except (FileNotFoundError, ModuleNotFoundError):
        return QIcon()


def main() -> int:
    """Uruchamia GUI Signum."""
    if "--self-test" in sys.argv or "--self-test-jev" in sys.argv:
        return _self_test(local_jev="--self-test-jev" in sys.argv)
    if "--self-test-classification" in sys.argv:
        return _self_test_classification()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(_load_icon())
    if "--setup-local-ai" in sys.argv:
        from signum.setup_local_ai import run_setup_dialog  # noqa: PLC0415

        return run_setup_dialog(sys.argv[1:])
    if not _acquire_instance_mutex():
        QMessageBox.information(
            None,
            APP_NAME,
            "Signum jest już uruchomione w tej sesji użytkownika.",
        )
        return 0
    window = MainWindow()
    window.show()
    return app.exec()


def _self_test(*, local_jev: bool = False) -> int:
    """Minimalny test spakowanego runtime'u używany podczas budowania instalatora."""
    import keyring  # noqa: PLC0415
    import pypdf  # noqa: PLC0415
    import pypdfium2  # noqa: PLC0415
    import requests  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    dependencies = (keyring, pypdf, pypdfium2, requests, Image)
    icon_path = resources.files("signum.ui.resources") / "signum.ico"
    jev_bootstrap = resources.files("signum.ai") / "vjev_bootstrap.py"
    probe = resources.files("signum.ai") / "runtime_probe.py"
    text_bootstrap = resources.files("signum.ai") / "jevk5_text_worker.py"
    try:
        keyring.get_password("Signum self-test", "missing-test-entry")
    except Exception:
        return 1
    if (
        not all(dependencies)
        or not icon_path.is_file()
        or not jev_bootstrap.is_file()
        or not text_bootstrap.is_file()
        or not probe.is_file()
    ):
        return 1
    if local_jev:
        import json  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        from signum.ai import AIError, create_vision_model  # noqa: PLC0415
        from signum.config import AppConfig  # noqa: PLC0415

        config = AppConfig.load()
        config.provider = "vjev"
        config.vjev_base_url = "http://localhost:8800/v1"  # always local diagnostics
        model = create_vision_model(config, api_key="")
        try:
            message = model.check_connection()
            analysis = model.analyze_image(Image.new("RGB", (640, 800), "white"), 1120)
            result = {
                "ok": analysis.signature_probability is not None,
                "message": message,
                "version": __version__,
                "signature_probability": analysis.signature_probability,
            }
        except (AIError, ValueError) as exc:
            result = {"ok": False, "message": str(exc), "version": __version__}
        finally:
            model.release_resources()
        try:
            (Path(config.vjev_runtime_dir) / "packaged-self-test.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return 1
        return 0 if result["ok"] else 1
    return 0


def _self_test_classification() -> int:
    """Opt-in packaged check of the external text runtime and its packaged bridge."""
    import json  # noqa: PLC0415
    import threading  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from signum.ai.text_classifiers import JevK5TextClassifier  # noqa: PLC0415
    from signum.config import AppConfig  # noqa: PLC0415
    from signum.core.classification import make_question  # noqa: PLC0415

    config = AppConfig.load()
    bridge = JevK5TextClassifier(config, threading.Event())
    question = make_question(
        [("Umowa", "An agreement or contract"), ("Raport", "A report")], "Choose the document type."
    )
    try:
        text = bridge.prepare("This is a contract for delivery of goods.", question)
        decision = bridge.classify(text, question)
        result = {
            "ok": decision.get("choice") == "c01",
            "version": __version__,
            "decision": decision,
        }
    except Exception as exc:
        result = {"ok": False, "version": __version__, "error": str(exc)}
    finally:
        bridge.close()
    destination = Path(config.classification_cache_dir) / "packaged-self-test.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


def _acquire_instance_mutex() -> bool:
    """Tworzy mutex używany także przez instalator do wykrycia działającej aplikacji."""
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    create_mutex.restype = ctypes.c_void_p
    handle = create_mutex(None, False, _INSTANCE_MUTEX_NAME)
    if not handle:
        logging.getLogger(__name__).warning("Nie udało się utworzyć mutexu aplikacji")
        return True
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _instance_mutex_handles.append(handle)
    return True


if __name__ == "__main__":
    sys.exit(main())
