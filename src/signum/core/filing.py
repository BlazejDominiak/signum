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
from signum.i18n import tr

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
        raise ValueError(tr("core.filing.the_category_folder_points_outside_the_destination"))
    if getattr(folder, "is_junction", lambda: False)():
        raise ValueError(tr("core.filing.the_category_folder_is_a_link"))
    if folder.exists() and not folder.is_dir():
        raise ValueError(tr("core.filing.a_file_already_uses_the_category_folder"))


def build_filing_plan(
    files: list[Path],
    batch: ClassificationBatch,
    model: str,
    repeat: int,
    root: Path,
    mode: FilingMode,
) -> FilingPlan:
    if mode not in ("copy", "move"):
        raise ValueError(tr("core.unknown_operation"))
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(tr("core.filing.select_an_existing_destination_folder"))
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
        categories = candidates[0].selected_categories if len(candidates) == 1 else []
        category = "; ".join(categories)
        target = None
        fingerprint = None
        skip = ""
        if len(candidates) != 1 or not category or candidates[0].error:
            skip = tr("core.filing.no_unambiguous_result")
        elif candidates[0].hitl:
            skip = tr("core.filing.hitl_review_labels_before_organizing")
        elif mode == "move" and len(categories) > 1:
            skip = tr("core.filing.multiple_labels_copy_to_all_categories_or")
        elif candidates[0].excluded:
            skip = tr("core.filing.excluded_from_organizing")
        elif not candidates[0].source_sha256 or not candidates[0].source_fingerprint:
            skip = tr("core.filing.missing_file_identity_run_the_analysis_again")
        elif any(label not in folders for label in categories):
            skip = tr("core.unknown_label")
        elif source.suffix.lower() != ".pdf" or source.is_symlink() or not source.is_file():
            skip = tr("core.filing.file_unavailable_or_a_link")
        else:
            try:
                if _fingerprint(source) != candidates[0].source_fingerprint:
                    raise ValueError(tr("core.filing.pdf_has_changed_since_classification_run_the"))
                for label in categories:
                    skip = ""
                    fingerprint = None
                    folder = root / folders[label]
                    _check_folder(root, folder)
                    target = folder / source.name
                    if _key(source.resolve()) == _key(target.resolve()):
                        skip = tr("core.filing.already_in_the_destination_folder")
                    else:
                        if folder not in folder_contents:
                            folder_contents[folder] = (
                                {p.name.casefold() for p in folder.iterdir()}
                                if folder.exists()
                                else set()
                            )
                        occupied = folder_contents[folder]
                        number = 2
                        while target.name.casefold() in occupied or _key(target) in reserved:
                            target = folder / f"{source.stem} ({number}){source.suffix}"
                            number += 1
                        reserved.add(_key(target))
                        fingerprint = _fingerprint(source)
                    entries.append(
                        FilingEntry(
                            source,
                            target,
                            label,
                            skip,
                            fingerprint,
                            candidates[0].source_sha256,
                        )
                    )
                continue
            except (OSError, ValueError) as exc:
                skip = str(exc)
        entries.append(
            FilingEntry(
                source,
                target,
                category,
                skip,
                fingerprint,
                candidates[0].source_sha256 if len(candidates) == 1 else "",
            )
        )
    return FilingPlan(root, mode, tuple(entries))


class _CancelledError(Exception):
    pass


def _copy_verified(entry: FilingEntry, root: Path, cancel: threading.Event, move: bool) -> None:
    source, target = entry.source, entry.target
    assert target is not None
    if root.resolve(strict=True) != root:
        raise ValueError(tr("core.filing.the_destination_folder_has_moved"))
    _check_folder(root, target.parent)
    if source.is_symlink() or _fingerprint(source) != entry.fingerprint:
        raise ValueError(tr("core.filing.the_source_file_has_changed_since_the"))
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
        if (
            copied != digest.digest()
            or digest.hexdigest() != entry.source_sha256
            or _fingerprint(source) != entry.fingerprint
        ):
            raise ValueError(tr("core.filing.copy_verification_failed_the_source_is_unchanged"))
        shutil.copystat(source, target)
        if cancel.is_set():
            raise _CancelledError()
        if move:
            with source.open("rb") as check:
                current = hashlib.file_digest(check, "sha256").digest()
            if current != copied or _fingerprint(source) != entry.fingerprint:
                raise ValueError(tr("core.filing.the_source_file_changed_while_moving"))
            if cancel.is_set():
                raise _CancelledError()
            source.unlink()
    except Exception:
        if created:
            target.chmod(stat.S_IREAD | stat.S_IWRITE)
            target.unlink(missing_ok=True)
        raise


def execute_filing(
    plan: FilingPlan,
    cancel: threading.Event,
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
                result.errors.append(
                    (entry, tr("core.filing.operation_completed_journal_error", exc=exc))
                )
            progress(index, entry, tr("core.moved") if plan.mode == "move" else tr("core.copied"))
    return result


def _journal(path: Path | None, operation: str, mode: str, entry: FilingEntry, state: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "id": operation,
        "time": time.time(),
        "mode": mode,
        "state": state,
        "source": str(entry.source),
        "target": str(entry.target),
        "sha256": entry.source_sha256,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
