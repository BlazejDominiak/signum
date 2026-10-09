"""Qt worker for text classification with user-selected model profiles."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from signum.ai.model_profiles import ModelProfile, load_profiles
from signum.ai.text_classifiers import (
    JevK5TextClassifier,
    conservative_text_limit,
    create_text_classifier,
)
from signum.config import AppConfig
from signum.core.classification import (
    ClassificationBatch,
    TextClassifier,
    make_question,
    run_classification,
)
from signum.core.classification_calibration import policy_for


class ClassificationWorker(QThread):
    progress = Signal(str)
    row_done = Signal(object)
    batch_done = Signal(object)
    timing = Signal(object)

    def __init__(
        self,
        config: AppConfig,
        files: list[Path],
        categories: list[tuple[str, str]],
        instructions: str,
        models: list[str],
        repeats: int,
    ) -> None:
        super().__init__()
        self.config, self.files, self.categories = config, files, categories
        self.instructions, self.models, self.repeats = instructions, models, repeats
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        profiles = {p.id: p for p in load_profiles(self.config)}
        bridges: list[JevK5TextClassifier] = []

        def factory(name: str) -> TextClassifier:
            for bridge in bridges:
                bridge.close()
            return create_text_classifier(
                profiles[name], self.config, self.cancel_event, self.progress.emit
            )

        try:
            selected: list[ModelProfile] = [profiles[name] for name in self.models]
            for profile in selected:
                if profile.provider == "jevk5":
                    bridge = create_text_classifier(profile, self.config, self.cancel_event)
                    assert isinstance(bridge, JevK5TextClassifier)
                    if not bridge.available():
                        raise ValueError(f"{profile.label}: sprawdź ścieżki lokalnego modelu.")
                    bridges.append(bridge)

            def prepare(text: str, question: dict[str, Any]) -> str:
                limited = conservative_text_limit(text, question)
                for bridge in bridges:
                    limited = bridge.prepare(limited, question)
                return limited

            batch = run_classification(
                self.files,
                self.categories,
                self.instructions,
                self.models,
                self.repeats,
                self.cancel_event,
                factory,
                prepare,
                self.progress.emit,
                self.row_done.emit,
                {p.id: p.label for p in selected},
                lambda value: self.timing.emit(copy.deepcopy(value)),
                policies={p.id: policy_for(p, make_question(self.categories, self.instructions))
                          for p in selected},
            )
        except Exception as exc:
            batch = ClassificationBatch(error=str(exc))
        finally:
            for bridge in bridges:
                bridge.close()
        batch.model_details = {
            name: {
                "provider": profiles[name].provider, "model": profiles[name].model,
                "api_format": profiles[name].api_format, "url": profiles[name].url,
            } for name in self.models if name in profiles
        }
        self.batch_done.emit(batch)
