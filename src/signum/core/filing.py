"""Plan and execute PDF filing without overwriting existing documents."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from signum.core.classification import ClassificationBatch, ClassificationRow
from signum.core.file_identity import Fingerprint
from signum.core.file_identity import fingerprint as _fingerprint

FilingMode = Literal["copy", "move"]
def _key(path: Path) -> str:
    return str(path.absolute()).casefold()


def folder_name(label: str) -> str:
    """Keep readable labels, removing Windows-invalid characters and device names."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", unicodedata.normalize("NFC", label))
    name = name.strip().rstrip(". ")[:120].rstrip(". ") or "Kategoria"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", name):
        name = "_" + name
    return name


@dataclass(frozen=True)
class FilingEntry:
    source: Path
    target: Path | None = None
    category: str = ""
    skip: str = ""
    fingerprint: Fingerprint | None = None
    source_sha256: str = ""


@dataclass(frozen=True)
class FilingPlan:
    root: Path
    mode: FilingMode
    entries: tuple[FilingEntry, ...]

    @property
    def ready(self) -> int:
        return sum(not entry.skip for entry in self.entries)


@dataclass
class FilingResult:
    completed: list[FilingEntry] = field(default_factory=list)
    errors: list[tuple[FilingEntry, str]] = field(default_factory=list)
    cancelled: bool = False


def _check_folder(root: Path, folder: Path) -> None:
    if folder.parent != root or folder.is_symlink() or folder.resolve().parent != root:
        raise ValueError("Folder kategorii prowadzi poza folder docelowy lub jest dowiązaniem.")
    if getattr(folder, "is_junction", lambda: False)():
        raise ValueError("Folder kategorii jest dowiązaniem.")
    if folder.exists() and not folder.is_dir():
        raise ValueError("Nazwa folderu kategorii jest zajęta przez plik.")


def build_filing_plan(
    files: list[Path], batch: ClassificationBatch, model: str, repeat: int,
    root: Path, mode: FilingMode,
) -> FilingPlan:
    if mode not in ("copy", "move"):
        raise ValueError("Nieznana operacja na plikach.")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Wybierz istniejący folder docelowy.")
    labels = [name for name, _ in batch.categories if name]
    folders: dict[str, str] = {}
    used_folders: set[str] = set()
    for label in labels:
        base = folder_name(label)
        name, number = base, 2
        while name.casefold() in used_folders:
            name = f"{base} ({number})"
            number += 1
        folders[label] = name
        used_folders.add(name.casefold())
    rows: dict[str, list[ClassificationRow]] = {}
    for row in batch.rows:
        if row.model == model and row.repeat == repeat:
            rows.setdefault(_key(row.path), []).append(row)
    entries = []
    reserved: set[str] = set()
    seen: set[str] = set()
    folder_contents: dict[Path, set[str]] = {}
    for path in files:
        source = path.absolute()
        if _key(source) in seen:
            continue
        seen.add(_key(source))
        candidates = rows.get(_key(source), [])
        category = candidates[0].category if len(candidates) == 1 else ""
        target = None
        fingerprint = None
        skip = ""
        if len(candidates) != 1 or not category or candidates[0].error:
            skip = "Brak jednoznacznego wyniku"
        elif candidates[0].excluded:
            skip = "Wyłączony z porządkowania"
        elif not candidates[0].source_sha256 or not candidates[0].source_fingerprint:
            skip = "Brak tożsamości pliku — powtórz analizę"
        elif category not in folders:
            skip = "Nieznana etykieta"
        elif source.suffix.lower() != ".pdf" or source.is_symlink() or not source.is_file():
            skip = "Plik niedostępny lub dowiązanie"
        else:
            try:
                if _fingerprint(source) != candidates[0].source_fingerprint:
                    raise ValueError("PDF zmienił się od klasyfikacji — powtórz analizę")
                folder = root / folders[category]
                _check_folder(root, folder)
                target = folder / source.name
                if _key(source.resolve()) == _key(target.resolve()):
                    skip = "Już w folderze docelowym"
                else:
                    if folder not in folder_contents:
                        folder_contents[folder] = (
                            {p.name.casefold() for p in folder.iterdir()}
                            if folder.exists() else set()
                        )
                    occupied = folder_contents[folder]
                    number = 2
                    while target.name.casefold() in occupied or _key(target) in reserved:
                        target = folder / f"{source.stem} ({number}){source.suffix}"
                        number += 1
                    reserved.add(_key(target))
                    fingerprint = _fingerprint(source)
            except (OSError, ValueError) as exc:
                skip = str(exc)
        entries.append(FilingEntry(
            source, target, category, skip, fingerprint,
            candidates[0].source_sha256 if len(candidates) == 1 else "",
        ))
    return FilingPlan(root, mode, tuple(entries))


class _CancelledError(Exception):
    pass


def _copy_verified(entry: FilingEntry, root: Path, cancel: threading.Event, move: bool) -> None:
    source, target = entry.source, entry.target
    assert target is not None
    if root.resolve(strict=True) != root:
        raise ValueError("Folder docelowy zmienił położenie.")
    _check_folder(root, target.parent)
    if source.is_symlink() or _fingerprint(source) != entry.fingerprint:
        raise ValueError("Plik źródłowy zmienił się od przygotowania podglądu.")
    target.parent.mkdir(exist_ok=True)
    _check_folder(root, target.parent)
    created = False
    try:
        digest = hashlib.sha256()
        with source.open("rb") as original, target.open("xb") as output:
            created = True
            while chunk := original.read(1024 * 1024):
                if cancel.is_set():
                    raise _CancelledError()
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        with target.open("rb") as check:
            copied = hashlib.file_digest(check, "sha256").digest()
        if (copied != digest.digest() or digest.hexdigest() != entry.source_sha256
                or _fingerprint(source) != entry.fingerprint):
            raise ValueError("Weryfikacja kopii nie powiodła się; źródło pozostaje bez zmian.")
        shutil.copystat(source, target)
        if cancel.is_set():
            raise _CancelledError()
        if move:
            with source.open("rb") as check:
                current = hashlib.file_digest(check, "sha256").digest()
            if current != copied or _fingerprint(source) != entry.fingerprint:
                raise ValueError("Plik źródłowy zmienił się podczas przenoszenia.")
            if cancel.is_set():
                raise _CancelledError()
            source.unlink()
    except Exception:
        if created:
            target.chmod(stat.S_IREAD | stat.S_IWRITE)
            target.unlink(missing_ok=True)
        raise


def execute_filing(
    plan: FilingPlan, cancel: threading.Event,
    progress: Callable[[int, FilingEntry, str], None] = lambda *_: None,
    journal: Path | None = None,
) -> FilingResult:
    result = FilingResult()
    for index, entry in enumerate(plan.entries):
        if cancel.is_set():
            result.cancelled = True
            break
        if entry.skip:
            continue
        operation = uuid.uuid4().hex
        try:
            _journal(journal, operation, plan.mode, entry, "planned")
            _copy_verified(entry, plan.root, cancel, plan.mode == "move")
        except _CancelledError:
            result.cancelled = True
            break
        except (OSError, ValueError) as exc:
            result.errors.append((entry, str(exc)))
            progress(index, entry, str(exc))
        else:
            result.completed.append(entry)
            try:
                _journal(journal, operation, plan.mode, entry, "completed")
            except OSError as exc:
                result.errors.append((entry, f"Operacja wykonana; błąd dziennika: {exc}"))
            progress(index, entry, "Przeniesiono" if plan.mode == "move" else "Skopiowano")
    return result


def _journal(path: Path | None, operation: str, mode: str, entry: FilingEntry, state: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"id": operation, "time": time.time(), "mode": mode, "state": state,
              "source": str(entry.source), "target": str(entry.target),
              "sha256": entry.source_sha256}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
