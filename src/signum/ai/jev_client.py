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
from signum.ai.jev_signature import QUALITY_QUESTIONS, parse_signature_views, signature_views
from signum.ai.local_vjev import start_local_vjev, stop_local_vjev
from signum.core.models import SignatureKind
from signum.core.rendering import to_model_jpeg
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
    ) -> None:
        self.loading_seconds = 0.0
        self.request_seconds: float = 0.0
        self._base_url = normalize_ai_endpoint(base_url, DEFAULT_URL, "API Jev")
        self._model = model
        self._timeout_s = timeout_s
        self._api_key = api_key
        self._runtime_dir = runtime_dir
        self._additional_analysis = additional_analysis
        self._session = requests.Session()
        self._session.trust_env = not is_loopback_endpoint(self._base_url)
        if api_key:
            self._session.headers["Authorization"] = f"Bearer {api_key}"

    @property
    def name(self) -> str:
        suffix = " (dodatkowa analiza)" if self._additional_analysis else ""
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
            raise AIConnectionError(
                f"Serwer vjev nie odpowiada pod {self._base_url}. "
                "Lokalny model musi być uruchomiony przed analizą."
            ) from exc
        finally:
            self.request_seconds += time.perf_counter() - started
        if response.status_code != 200:
            hint = {
                401: "Klucz API odrzucony",
                403: "Brak uprawnień do modelu",
                429: "Limit zapytań lub dostępnej przepustowości",
                422: "Sprawdź model wizyjny i zgodność serwera z API Jev",
            }.get(response.status_code, "Usługa Jev odrzuciła zapytanie")
            raise AIResponseError(f"{hint} (HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError as exc:
            raise AIResponseError("API Jev nie zwróciło poprawnego JSON") from exc
        if not isinstance(data, dict):
            raise AIResponseError("API Jev nie zwróciło obiektu JSON")
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
        raise NotImplementedError("Jev używa analyze_page i odpowiedzi typowanych")

    def analyze_page(self, image_jpeg: bytes, prompt: str | None = None) -> PageAnalysis:
        """Protokół pojedynczego JPEG-u, zachowany dla testu usługi i starego benchmarku."""
        data = self._decide(image_jpeg, prompt or JEV_PROMPT_INSTRUCTIONS)
        return _parse_decisions(data)

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
        basic = parse_signature_views(responses)
        if self._additional_analysis:
            return enrich_analysis(image, basic, self._decide, check_cancelled)
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
            raise AIResponseError("API Jev zwróciło niepoprawną listę modeli")
        selected = next((item for item in models if item.get("id") == self._model), None)
        if selected is None:
            raise AIResponseError(f"Model {self._model!r} nie jest dostępny pod tym adresem API")
        if selected.get("vision") is False or selected.get("stub") is True:
            raise AIResponseError("Wybrany model nie analizuje obrazów lub działa jako stub")
        # Mały, syntetyczny obraz weryfikuje rzeczywisty kontrakt wizyjny i uprawnienia.
        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(buffer, format="JPEG")
        self.analyze_page(buffer.getvalue())
        return f"Połączono z {self.name} — test obrazu zakończony"

    def stop_local(self) -> str:
        return stop_local_vjev(self._base_url, self._runtime_dir)

    def release_resources(self) -> None:
        if self._runtime_dir and is_loopback_endpoint(self._base_url):
            try:
                self.stop_local()
            except AIError:
                logging.getLogger(__name__).debug("Jev nie wymaga zatrzymania przez Signum.")


def _parse_decisions(data: dict[str, Any]) -> PageAnalysis:
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise AIResponseError("Brak obiektu answers w odpowiedzi Jev")
    signatures = []
    for kind in (SignatureKind.HANDWRITTEN, SignatureKind.INITIALS, SignatureKind.STAMP):
        answer = answers.get(kind.value)
        if not isinstance(answer, dict) or answer.get("type") != "noul":
            raise AIResponseError(f"Brak poprawnej decyzji {kind.value} w odpowiedzi Jev")
        score = answer.get("noul")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise AIResponseError(f"Niepoprawna ocena {kind.value} w odpowiedzi Jev")
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise AIResponseError(f"Niepoprawna ocena {kind.value} w odpowiedzi Jev")
        if score >= DETECTION_THRESHOLD:
            signatures.append(VisualSignature(kind, round(score * 100), None))
    document = answers.get("document_type")
    if not isinstance(document, dict) or document.get("type") != "choice":
        raise AIResponseError("Brak poprawnego rodzaju dokumentu w odpowiedzi Jev")
    choice = document.get("choice")
    if not isinstance(choice, str) or choice not in DOCUMENT_TYPES:
        raise AIResponseError("Nieznany rodzaj dokumentu w odpowiedzi Jev")
    return PageAnalysis(DOCUMENT_TYPES[choice][1], tuple(signatures))
