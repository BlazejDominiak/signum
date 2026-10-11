"""Wizyjne decyzje on-prem vjev-serve."""

from __future__ import annotations

import base64
import io
import logging
import math
import time
from collections.abc import Callable
from typing import Any

import requests
from PIL import Image

from signum.ai.base import (
    AIConnectionError,
    AIError,
    AIResponseError,
    PageAnalysis,
    VisionModel,
    VisualSignature,
)
from signum.ai.jev_additional import enrich_analysis
from signum.ai.jev_prompts import DOCUMENT_TYPES, JEV_PROMPT_INSTRUCTIONS, decision_questions
from signum.ai.jev_signature import (
    QUALITY_QUESTIONS,
    THRESHOLD,
    parse_signature_views,
    signature_views,
)
from signum.ai.local_vjev import start_local_vjev, stop_local_vjev
from signum.core.decision import near_threshold, probability, review_reason
from signum.core.models import SignatureKind
from signum.core.rendering import to_model_jpeg
from signum.i18n import tr
from signum.network import is_loopback_endpoint, normalize_ai_endpoint

DEFAULT_URL = "http://localhost:8800/v1"
DETECTION_THRESHOLD = 0.5


class JevVisionModel(VisionModel):
    """Obecność danego rodzaju oznaczenia na stronie, bez ramek i zliczania."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_s: int = 300,
        runtime_dir: str = "",
        additional_analysis: bool = False,
        hitl_margin: float = 0.10,
        threshold: float = THRESHOLD,
        stamp_threshold: float = 0.5,
        category_threshold: float = 0.6,
        candidate_threshold: float = 0.5,
        verify_threshold: float = 0.65,
        single_threshold: float = 0.5,
    ) -> None:
        self.loading_seconds = 0.0
        self.request_seconds: float = 0.0
        self._base_url = normalize_ai_endpoint(base_url, DEFAULT_URL, "API Jev")
        self._model = model
        self._timeout_s = timeout_s
        self._api_key = api_key
        self._runtime_dir = runtime_dir
        self._additional_analysis = additional_analysis
        self._hitl_margin = probability(hitl_margin)
        self._threshold = probability(threshold)
        self._stamp_threshold = probability(stamp_threshold)
        self._additional_thresholds = {
            "category_threshold": probability(category_threshold),
            "candidate_threshold": probability(candidate_threshold),
            "verify_threshold": probability(verify_threshold),
            "single_threshold": probability(single_threshold),
        }
        self._session = requests.Session()
        self._session.trust_env = not is_loopback_endpoint(self._base_url)
        if api_key:
            self._session.headers["Authorization"] = f"Bearer {api_key}"

    @property
    def name(self) -> str:
        suffix = tr("ai.additional_suffix") if self._additional_analysis else ""
        return f"vjev-vision: {self._model}{suffix}"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            response = self._session.request(
                method,
                f"{self._base_url}/{path}",
                timeout=self._timeout_s,
                allow_redirects=False,
                **kwargs,
            )
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError(tr("ai.vjev_connection_failed", url=self._base_url)) from exc
        finally:
            self.request_seconds += time.perf_counter() - started
        if response.status_code != 200:
            hint = {
                401: tr("ai.jev_key_rejected"),
                403: tr("ai.jev_forbidden"),
                429: tr("ai.jev_capacity"),
                422: tr("ai.jev_compatibility"),
            }.get(response.status_code, tr("ai.jev_request_rejected"))
            raise AIResponseError(f"{hint} (HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError as exc:
            raise AIResponseError(tr("ai.jev_invalid_json")) from exc
        if not isinstance(data, dict):
            raise AIResponseError(tr("ai.jev_missing_object"))
        return data

    def _decide(
        self,
        image_jpeg: bytes,
        prompt: str,
        questions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded = base64.b64encode(image_jpeg).decode("ascii")
        payload: dict[str, Any] = {
            "model": self._model,
            "questions": questions or decision_questions(),
        }
        text = {"type": "text", "text": prompt}
        payload["state"] = [
            text,
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": encoded,
                },
            },
        ]
        return self._request("POST", "systemone", json=payload)

    def _generate(self, image_jpeg: bytes, prompt: str) -> str:
        # Ten dostawca nie generuje tekstu — analyze_page parsuje decyzje bezpośrednio.
        raise NotImplementedError(tr("ai.jev_typed_responses"))

    def analyze_page(self, image_jpeg: bytes, prompt: str | None = None) -> PageAnalysis:
        """Protokół pojedynczego JPEG-u, zachowany dla testu usługi i starego benchmarku."""
        data = self._decide(image_jpeg, prompt or JEV_PROMPT_INSTRUCTIONS)
        return _parse_decisions(data, self._hitl_margin)

    def analyze_image(
        self,
        image: Image.Image,
        max_side: int,
        prompt: str | None = None,
        check_cancelled: Callable[[], None] | None = None,
    ) -> PageAnalysis:
        responses = []
        for view in signature_views(image):
            if check_cancelled:
                check_cancelled()
            responses.append(
                self._decide(
                    to_model_jpeg(view, 1120),
                    prompt or JEV_PROMPT_INSTRUCTIONS,
                    QUALITY_QUESTIONS,
                )
            )
        basic = parse_signature_views(
            responses,
            self._hitl_margin,
            self._threshold,
            self._stamp_threshold,
        )
        if self._additional_analysis:
            return enrich_analysis(
                image,
                basic,
                self._decide,
                check_cancelled,
                **self._additional_thresholds,
            )
        return basic

    def check_connection(self) -> str:
        try:
            data = self._request("GET", "models")
        except AIConnectionError:
            if not self._runtime_dir or not is_loopback_endpoint(self._base_url):
                raise
            started = time.perf_counter()
            try:
                start_local_vjev(self._base_url, self._runtime_dir, self._timeout_s)
            finally:
                self.loading_seconds += time.perf_counter() - started
            data = self._request("GET", "models")
        models = data.get("models")
        if not isinstance(models, list) or not all(isinstance(item, dict) for item in models):
            raise AIResponseError(tr("ai.jev_invalid_models"))
        selected = next((item for item in models if item.get("id") == self._model), None)
        if selected is None:
            raise AIResponseError(tr("ai.jev_model_missing", model=self._model))
        if selected.get("vision") is False or selected.get("stub") is True:
            raise AIResponseError(tr("ai.jev_no_vision"))
        # Mały, syntetyczny obraz weryfikuje rzeczywisty kontrakt wizyjny i uprawnienia.
        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(buffer, format="JPEG")
        self.analyze_page(buffer.getvalue())
        return tr("ai.jev_connected", model=self.name)

    def stop_local(self) -> str:
        return stop_local_vjev(self._base_url, self._runtime_dir)

    def release_resources(self) -> None:
        if self._runtime_dir and is_loopback_endpoint(self._base_url):
            try:
                self.stop_local()
            except AIError:
                logging.getLogger(__name__).debug("Jev nie wymaga zatrzymania przez Signum.")


def _parse_decisions(data: dict[str, Any], hitl_margin: float = 0.10) -> PageAnalysis:
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise AIResponseError(tr("ai.jev_missing_answers"))
    signatures = []
    reasons = []
    for kind in (SignatureKind.HANDWRITTEN, SignatureKind.INITIALS, SignatureKind.STAMP):
        answer = answers.get(kind.value)
        if not isinstance(answer, dict) or answer.get("type") != "noul":
            raise AIResponseError(tr("ai.jev_invalid_decision", kind=kind.value))
        score = answer.get("noul")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise AIResponseError(tr("ai.jev_invalid_score", kind=kind.value))
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise AIResponseError(tr("ai.jev_invalid_score", kind=kind.value))
        if kind != SignatureKind.STAMP and near_threshold(score, DETECTION_THRESHOLD, hitl_margin):
            reasons.append(review_reason(kind.label_pl, score, DETECTION_THRESHOLD, hitl_margin))
        if score >= DETECTION_THRESHOLD:
            signatures.append(VisualSignature(kind, round(score * 100), None))
    document = answers.get("document_type")
    if not isinstance(document, dict) or document.get("type") != "choice":
        raise AIResponseError(tr("ai.jev_missing_document_type"))
    choice = document.get("choice")
    if not isinstance(choice, str) or choice not in DOCUMENT_TYPES:
        raise AIResponseError(tr("ai.jev_unknown_document_type"))
    label_key = DOCUMENT_TYPES[choice][1]
    description = tr(label_key) if label_key else ""
    return PageAnalysis(description, tuple(signatures), review_reasons=tuple(reasons))
