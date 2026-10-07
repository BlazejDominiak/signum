"""Release checks must reject local corpus files even if force-added to Git."""

import importlib
import subprocess
from pathlib import Path


def test_force_added_pdf_and_local_text_are_rejected(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    guard = importlib.import_module("check_local_documents")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text("*.PDF\nscratch/\n.env\n")
    (tmp_path / "scratch").mkdir()
    for name in ("document.PDF", "scratch/extracted.txt", ".env", ".env.example", "app.py"):
        (tmp_path / name).write_text("synthetic fixture")
    subprocess.run(["git", "add", "-f", "."], cwd=tmp_path, check=True, capture_output=True)
    assert set(guard.check_repository(tmp_path)) == {
        "document.PDF", "scratch/extracted.txt", ".env"
    }


def test_nested_bundle_data_is_rejected(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    guard = importlib.import_module("check_local_documents")
    internal = tmp_path / "_internal"
    internal.mkdir()
    for name in ("scan.pDf", ".env.local", "library.dll"):
        (internal / name).write_text("synthetic fixture")
    assert set(guard.check_bundle(tmp_path)) == {"_internal/scan.pDf", "_internal/.env.local"}
