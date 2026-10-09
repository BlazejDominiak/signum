"""Atomic collection checkpoints without extracted PDF text or credentials."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, fields
from pathlib import Path

from signum import config
from signum.core.classification import ClassificationBatch, ClassificationRow
from signum.core.decision import probability


def session_path() -> Path:
    return config.config_dir() / "collection.json"


def journal_path() -> Path:
    return config.config_dir() / "filing-history.jsonl"


def save_collection(
    files: list[Path], batch: ClassificationBatch, path: Path | None = None,
) -> None:
    data = asdict(batch)
    data["documents"] = []
    # Runtime details are unnecessary for restoring labels.
    data["model_details"] = {}
    payload = {"version": 1, "files": [str(p) for p in files], "batch": data}
    path = path or session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, default=str, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_collection(path: Path | None = None) -> tuple[list[Path], ClassificationBatch] | None:
    path = path or session_path()
    if not path.exists():
        return None
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Zapis kolekcji jest zbyt duży")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["version"] != 1:
            raise ValueError("Nieobsługiwana wersja kolekcji")
        files = [Path(value) for value in data["files"]]
        if any(not p.is_absolute() for p in files):
            raise ValueError("Kolekcja zawiera niepełną ścieżkę")
        values = data["batch"]
        rows = []
        allowed = {f.name for f in fields(ClassificationRow)}
        for raw in values["rows"]:
            row = ClassificationRow(**{k: v for k, v in raw.items() if k in allowed})
            row.path = Path(row.path)
            if row.source_fingerprint is not None:
                parts = list(row.source_fingerprint)
                if len(parts) != 4 or any(not isinstance(n, int) for n in parts):
                    raise ValueError("Niepoprawna tożsamość pliku")
                row.source_fingerprint = (parts[0], parts[1], parts[2], parts[3])
            if row.path not in files or not isinstance(row.category, str):
                raise ValueError("Niepoprawny wiersz kolekcji")
            if not isinstance(row.model, str) or not isinstance(row.repeat, int):
                raise ValueError("Niepoprawny model lub numer próby")
            if not isinstance(row.source_sha256, str) or not isinstance(row.error, str):
                raise ValueError("Niepoprawny wynik kolekcji")
            numbers = (row.elapsed_s, row.wait_s, row.loading_s)
            if any(not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0
                   for n in numbers):
                raise ValueError("Niepoprawne czasy kolekcji")
            if row.confidence is not None and (
                not isinstance(row.confidence, (int, float))
                or not math.isfinite(row.confidence) or not 0 <= row.confidence <= 1
            ):
                raise ValueError("Niepoprawna pewność klasyfikacji")
            for field_name in ("assigned_categories", "review_reasons", "model_review_reasons",
                               "review_labels"):
                value = getattr(row, field_name)
                if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                    raise ValueError("Niepoprawna lista etykiet lub powodów HITL")
            if len(set(row.assigned_categories)) != len(row.assigned_categories):
                raise ValueError("Powtórzone etykiety kolekcji")
            if not isinstance(row.label_scores, dict) or any(
                not isinstance(k, str) for k in row.label_scores
            ):
                raise ValueError("Niepoprawne oceny etykiet")
            row.label_scores = {k: probability(v) for k, v in row.label_scores.items()}
            if row.threshold is not None:
                row.threshold = probability(row.threshold)
            row.hitl_margin = probability(row.hitl_margin)
            if row.score_source not in {"", "decision", "declared"}:
                raise ValueError("Niepoprawne źródło ocen etykiet")
            if (type(row.hitl) is not bool or not isinstance(row.calibration_id, str)
                    or not isinstance(row.calibration_warning, str)):
                raise ValueError("Niepoprawne oznaczenie HITL")
            if row.assigned_categories:
                row.category = "; ".join(row.assigned_categories)
            rows.append(row)
        allowed_batch = {f.name for f in fields(ClassificationBatch)} - {"rows", "documents"}
        batch = ClassificationBatch(rows=rows, **{
            k: v for k, v in values.items() if k in allowed_batch
        })
        batch.categories = [(str(name), str(detail)) for name, detail in batch.categories]
        if not isinstance(batch.model_labels, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in batch.model_labels.items()
        ):
            raise ValueError("Niepoprawne nazwy modeli")
        if not isinstance(batch.instructions, str):
            raise ValueError("Niepoprawny prompt kolekcji")
        return files, batch
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Niepoprawny zapis kolekcji") from exc
