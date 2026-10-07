"""Klient Claude API (Anthropic Messages API) dla modeli wizyjnych Claude."""

from __future__ import annotations

import base64
import time

import requests

from signum.ai.base import AIConnectionError, AIResponseError, VisionModel
from signum.network import is_loopback_endpoint, normalize_ai_endpoint

API_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicVisionModel(VisionModel):
    """Model Claude przez Messages API (obrazy jako bloki base64)."""

    def __init__(
        self, api_key: str, model: str = DEFAULT_MODEL, timeout_s: int = 300,
        base_url: str = API_URL,
    ) -> None:
        self._base_url = normalize_ai_endpoint(base_url, API_URL, "API Claude")
        self._session = requests.Session()
        self._session.trust_env = not is_loopback_endpoint(self._base_url)
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        self.request_seconds: float = 0.0

    @property
    def name(self) -> str:
        return f"Claude API: {self._model}"

    def _headers(self) -> dict[str, str]:
        headers = {
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def _generate(self, image_jpeg: bytes, prompt: str) -> str:
        payload = {
            "model": self._model,
            "max_tokens": 1000,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": base64.b64encode(image_jpeg).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        started = time.perf_counter()
        try:
            response = self._session.post(
                f"{self._base_url}/messages",
                json=payload,
                headers=self._headers(),
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError(f"Brak połączenia z Claude API: {exc}") from exc
        finally:
            self.request_seconds += time.perf_counter() - started
        if response.status_code != 200:
            raise AIResponseError(f"Claude API zwróciło HTTP {response.status_code}")
        try:
            blocks = response.json()["content"]
            texts = [block["text"] for block in blocks if block.get("type") == "text"]
            return "\n".join(texts)
        except (ValueError, KeyError, TypeError) as exc:
            raise AIResponseError(f"Niepoprawna odpowiedź Claude API: {exc}") from exc

    def check_connection(self) -> str:
        if not self._api_key and not is_loopback_endpoint(self._base_url):
            raise AIResponseError("Nie podano klucza API")
        try:
            response = self._session.get(
                f"{self._base_url}/models?limit=1",
                headers=self._headers(),
                timeout=15,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError(f"Brak połączenia z Claude API: {exc}") from exc
        if response.status_code == 401:
            raise AIResponseError("Klucz API odrzucony (HTTP 401)")
        if response.status_code != 200:
            raise AIResponseError(f"Claude API zwróciło HTTP {response.status_code}")
        return f"Połączono z Claude API — model {self._model}"
