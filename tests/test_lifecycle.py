"""Testy zabezpieczeń i komunikatów instalatora Windows."""

from pathlib import Path

from signum.app import _self_test


def test_installer_requires_document_and_ai_risk_awareness() -> None:
    installer = Path("installer/signum.iss").read_text(encoding="utf-8")

    assert "RiskCheckPurpose" in installer
    assert "RiskCheckDocuments" in installer
    assert "RiskCheckLocal" in installer
    assert "RiskCheckRemote" in installer
    assert "ACKNOWLEDGERISKS" in installer
    assert "RisksConfirmed" in installer


def test_installer_contains_polish_and_english_risk_notices() -> None:
    polish_notice = Path("installer/legal/RISK-NOTICE-pl.txt").read_text(encoding="utf-8")
    english_notice = Path("installer/legal/RISK-NOTICE-en.txt").read_text(encoding="utf-8")

    assert "INFORMACJA O RYZYKU" in polish_notice
    assert "ręcznej weryfikacji" in polish_notice
    assert "RISK NOTICE" in english_notice
    assert "human verification" in english_notice
    assert "zobowiązuję się" not in polish_notice.lower()


def test_installer_explains_and_checks_runtime_prerequisites() -> None:
    installer = Path("installer/signum.iss").read_text(encoding="utf-8")
    build_script = Path("scripts/build_installer.ps1").read_text(encoding="utf-8")

    assert "RequirementsNote" in installer
    assert "DetectAI" in installer
    assert "HardwareSummary" in installer
    assert "RequirementsPage" not in installer
    assert "ItemEnabled[1]" in installer
    assert "--self-test" in build_script
    assert "Start-Process" in build_script
    assert "Get-FileHash" in build_script
    assert _self_test() == 0


def test_packaged_executable_gets_neutral_version_metadata() -> None:
    spec = Path("packaging/signum.spec").read_text(encoding="utf-8")

    assert "version=str(version_file)" in spec
    assert "Signum contributors" in spec
    assert "app_version" in spec


def test_installer_mutex_matches_application_mutex() -> None:
    installer = Path("installer/signum.iss").read_text(encoding="utf-8")
    application = Path("src/signum/app.py").read_text(encoding="utf-8")
    mutex = "Local\\Signum-6D6C3F52-9C1B-4E6A-9A57-2B1FBD6A7E31"

    assert f"AppMutex={mutex}" in installer
    assert mutex.replace("\\", "\\\\") in application


def test_personal_identity_metadata_has_one_explicit_allowlisted_exception() -> None:
    text_suffixes = {".md", ".py", ".toml", ".txt", ".iss", ".ps1", ".yml", ".yaml"}
    excluded_dirs = {".git", ".venv", ".claude", ".agents", "build", "dist", "output", "scratch"}
    identity_tokens = ("Bla" + "zej", "Bła" + "żej", "real" + "buka")
    matches: list[tuple[str, str]] = []

    for path in Path(".").rglob("*"):
        # User-authored presentation artifact is not application identity metadata.
        if path.as_posix().removeprefix("./") == "JevScript_gotowy.txt":
            continue
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        if any(part in excluded_dirs for part in path.parts):
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if any(token.casefold() in line.casefold() for token in identity_tokens):
                matches.append((path.as_posix().removeprefix("./"), line.strip()))

    publisher = '#define MyAppPublisher "' + identity_tokens[0] + '"'
    assert matches == [("installer/signum.iss", publisher)]
