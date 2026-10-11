"""Klient API zgodnych z OpenAI (OpenAI, OpenRouter, Azure OpenAI z proxy itd.)."""

from __future__ import annotations

import base64
import time

import requests

from signum.ai.base import AIConnectionError, AIResponseError, VisionModel
from signum.i18n import tr
from signum.network import is_loopback_endpoint, normalize_ai_endpoint

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIVisionModel(VisionModel):
    """Dowolne API implementujące ``POST /chat/completions`` w stylu OpenAI.

    ``response_format: json_object`` jest wysyłany opcjonalnie — część
    dostawców go nie wspiera, wtedy ponawiamy żądanie bez niego.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout_s: int = 300) -> None:
        self._base_url = normalize_ai_endpoint(base_url, DEFAULT_BASE_URL, "API OpenAI")
        self._session = requests.Session()
        self._session.trust_env = not is_loopback_endpoint(self._base_url)
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        self._supports_json_format = True
        self.request_seconds: float = 0.0

    @property
    def name(self) -> str:
        return f"OpenAI API: {self._model}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def _generate(self, image_jpeg: bytes, prompt: str) -> str:
        image_b64 = base64.b64encode(image_jpeg).decode("ascii")
        payload: dict = {
            "model": self._model,
            "temperature": 0,
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        if self._supports_json_format:
            payload["response_format"] = {"type": "json_object"}

        response = self._post("/chat/completions", payload)
        if response.status_code == 400 and self._supports_json_format:
            # Dostawca może nie wspierać response_format — jedna próba bez niego.
            self._supports_json_format = False
            payload.pop("response_format", None)
            response = self._post("/chat/completions", payload)

        if response.status_code != 200:
            raise AIResponseError(tr("ai.api_http", status=response.status_code))
        try:
            return str(response.json()["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIResponseError(tr("ai.invalid_api_response", error=exc)) from exc

    def _post(self, endpoint: str, payload: dict) -> requests.Response:
        started = time.perf_counter()
        try:
            return self._session.post(
                f"{self._base_url}{endpoint}",
                json=payload,
                headers=self._headers(),
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError(
                tr("ai.connection_failed", url=self._base_url, error=exc)
            ) from exc
        finally:
            self.request_seconds += time.perf_counter() - started

    def check_connection(self) -> str:
        if not self._api_key and not is_loopback_endpoint(self._base_url):
            raise AIResponseError(tr("ai.missing_api_key"))
        try:
            response = self._session.get(
                f"{self._base_url}/models",
                headers=self._headers(),
                timeout=15,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError(
                tr("ai.connection_failed", url=self._base_url, error=exc)
            ) from exc
        if response.status_code == 401:
            raise AIResponseError(tr("ai.api_key_rejected"))
        if response.status_code in {404, 405}:
            # Niektóre proxy nie wystawiają /models — to nie przesądza o błędzie.
            return tr("ai.models_unavailable", url=self._base_url, status=response.status_code)
        if response.status_code != 200:
            raise AIResponseError(tr("ai.api_check_failed", status=response.status_code))
        return tr("ai.api_connected", url=self._base_url)
