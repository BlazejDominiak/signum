"""Klient API zgodnych z OpenAI (OpenAI, OpenRouter, Azure OpenAI z proxy itd.)."""

from __future__ import annotations

import base64

import requests

from signum.ai.base import AIConnectionError, AIResponseError, VisionModel
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
            raise AIResponseError(f"API zwróciło HTTP {response.status_code}")
        try:
            return str(response.json()["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIResponseError(f"Niepoprawna odpowiedź API: {exc}") from exc

    def _post(self, endpoint: str, payload: dict) -> requests.Response:
        try:
            return self._session.post(
                f"{self._base_url}{endpoint}",
                json=payload,
                headers=self._headers(),
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError(f"Brak połączenia z {self._base_url}: {exc}") from exc

    def check_connection(self) -> str:
        if not self._api_key and not is_loopback_endpoint(self._base_url):
            raise AIResponseError("Nie podano klucza API")
        try:
            response = self._session.get(
                f"{self._base_url}/models",
                headers=self._headers(),
                timeout=15,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError(f"Brak połączenia z {self._base_url}: {exc}") from exc
        if response.status_code == 401:
            raise AIResponseError("Klucz API odrzucony (HTTP 401)")
        if response.status_code != 200:
            # Niektóre proxy nie wystawiają /models — to nie przesądza o błędzie.
            return f"Endpoint {self._base_url} odpowiada (HTTP {response.status_code})"
        return f"Połączono z {self._base_url} — klucz API przyjęty"
