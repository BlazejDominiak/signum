"""Bezpieczne uruchamianie trybu CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from signum.cli import build_parser, main
from tests.test_pipeline import FakeVisionModel


def test_cli_wymaga_jawnego_potwierdzenia(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    document = tmp_path / "skan.png"
    document.write_bytes(b"not-read-before-risk-acknowledgement")

    assert main([str(document)]) == 2
    captured = capsys.readouterr()
    assert "OSTRZEŻENIE PRZED ANALIZĄ" in captured.err
    assert "--acknowledge-risks" in captured.err


@pytest.mark.parametrize("value", ["0", "-1", "501"])
def test_cli_odrzuca_niebezpieczny_limit_stron(value: str) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["dokument.pdf", "--max-pages", value])


@pytest.mark.parametrize("broken", [False, True])
def test_cli_kod_wyjscia_odzwierciedla_bledy_plikow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken: bool,
) -> None:
    from PIL import Image

    good = tmp_path / "good.png"
    Image.new("RGB", (50, 50), "white").save(good)
    files = [str(good)]
    if broken:
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a pdf")
        files.append(str(bad))
    monkeypatch.setattr("signum.cli.create_vision_model", lambda config: FakeVisionModel())
    report = tmp_path / "report.html"
    assert main([*files, "--acknowledge-risks", "--html", str(report)]) == int(broken)
    assert report.exists()
