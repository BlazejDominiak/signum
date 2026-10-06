"""Klient Ollamy — lokalny model wizyjny przez HTTP API (domyślny dostawca)."""

from __future__ import annotations

import base64
import logging
from typing import Any

import requests

from signum.ai.base import AIConnectionError, AIResponseError, VisionModel
from signum.ai.parsing import extract_first_json_object
from signum.ai.prompts import RESPONSE_SCHEMA
from signum.network import is_loopback_endpoint, normalize_ai_endpoint

DEFAULT_URL = "http://localhost:11434"
DEFAULT_NUM_CTX = 8192
logger = logging.getLogger(__name__)


class OllamaVisionModel(VisionModel):
    """Model wizyjny serwowany przez Ollamę (np. ``gemma4:12b``).

    Pierwsze zapytanie idzie BEZ structured outputs: wymuszanie schematu
    gramatyką (``format``) obniża recall detekcji — model potrafi zamknąć
    listę podpisów przedwcześnie i zgubić np. podpis odręczny sąsiadujący
    z pieczątką (zaobserwowane na gemma4:12b, temp 0, powtarzalne).
    Dopiero gdy odpowiedź nie zawiera poprawnego obiektu JSON, ponawiamy
    raz ze ``format`` jako siatką bezpieczeństwa dla zgodności ze schematem.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: int = 300,
        num_ctx: int = DEFAULT_NUM_CTX,
        api_key: str = "",
        runtime_dir: str = "",
    ) -> None:
        self._base_url = normalize_ai_endpoint(base_url, DEFAULT_URL, "Ollamy")
        self._session = requests.Session()
        # Lokalny endpoint nie może odziedziczyć proxy z otoczenia procesu.
        self._session.trust_env = not is_loopback_endpoint(self._base_url)
        if api_key:
            self._session.headers["Authorization"] = f"Bearer {api_key}"
        self._model = model
        self._timeout_s = timeout_s
        self._num_ctx = num_ctx
        self._api_key = api_key
        self._runtime_dir = runtime_dir

    @property
    def name(self) -> str:
        return f"Ollama: {self._model}"

    def _generate(self, image_jpeg: bytes, prompt: str) -> str:
        for structured in (False, True):
            try:
                content = self._chat(image_jpeg, prompt, structured=structured)
                data = extract_first_json_object(content)
                if not isinstance(data.get("signatures"), list):
                    raise AIResponseError("Brak listy podpisów w odpowiedzi Ollamy")
                return content
            except AIResponseError as exc:
                if structured:
                    raise AIResponseError(
                        f"Ollama ({self._model}) nie zwróciła pełnego wyniku analizy "
                        f"także po ponowieniu: {exc}. "
                        "Nie można na tej podstawie ocenić obecności podpisu."
                    ) from exc
        raise AssertionError("Nieosiągalny koniec ponowienia Ollamy")

    def _chat(self, image_jpeg: bytes, prompt: str, structured: bool) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt + (
                        "\nKażde odrębne znalezisko wpisz tylko RAZ. "
                        "Nie powtarzaj tych samych współrzędnych ani wpisów. "
                        "Po ostatnim znalezisku zamknij listę i obiekt JSON."
                    ),
                    "images": [base64.b64encode(image_jpeg).decode("ascii")],
                }
            ],
            "stream": False,
            # Thinking may consume the context before any final JSON is produced.
            "think": False,
            "options": {
                "temperature": 0,
                "num_ctx": self._num_ctx,
                "num_predict": 4096 if structured else 2048,
                "repeat_penalty": 1.15,
                "repeat_last_n": 256,
            },
        }
        if structured:
            payload["format"] = RESPONSE_SCHEMA
        try:
            response = self._session.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=self._timeout_s,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise AIConnectionError(
                f"Brak połączenia z Ollamą pod {self._base_url}: {exc}"
            ) from exc
        if response.status_code != 200:
            raise AIResponseError(f"Ollama zwróciła HTTP {response.status_code}")
        try:
            data = response.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AIResponseError(f"Niepoprawna odpowiedź Ollamy: {exc}") from exc
        if data.get("done_reason") == "length":
            raise AIResponseError("Model osiągnął limit odpowiedzi przed zakończeniem analizy")
        if not isinstance(content, str) or not content.strip():
            raise AIResponseError("Model zwrócił pustą odpowiedź końcową")
        return content

    def check_connection(self) -> str:
        if self._runtime_dir and is_loopback_endpoint(self._base_url):
            from signum.ai.local_ollama import start_local_ollama  # noqa: PLC0415

            start_local_ollama(self._base_url, self._runtime_dir)
        try:
            version_response = self._session.get(
                f"{self._base_url}/api/version", timeout=10, allow_redirects=False
            )
            version_response.raise_for_status()
            version = version_response.json()
            if not isinstance(version, dict):
                raise ValueError("niepoprawna odpowiedź endpointu /api/version")
            models = self.list_models(self._base_url, api_key=self._api_key)
        except (requests.exceptions.RequestException, ValueError) as exc:
            raise AIConnectionError(
                f"Brak połączenia z Ollamą pod {self._base_url}: {exc}"
            ) from exc
        if not _model_available(self._model, models):
            raise AIResponseError(
                f"Model {self._model!r} nie jest zainstalowany w Ollamie. "
                f"Dostępne: {', '.join(models) or '(brak)'}. "
                f"Pobierz go poleceniem: ollama pull {self._model}"
            )
        return f"Ollama {version.get('version', '?')} — model {self._model} dostępny"

    def release_resources(self) -> None:
        if not is_loopback_endpoint(self._base_url):
            return
        try:
            response = self._session.post(
                f"{self._base_url}/api/generate",
                json={"model": self._model, "keep_alive": 0},
                timeout=30, allow_redirects=False,
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.warning("Nie udało się zwolnić pamięci modelu Ollamy %s", self._model)

    @staticmethod
    def list_models(base_url: str, timeout_s: int = 10, api_key: str = "") -> list[str]:
        """Lista modeli zainstalowanych w Ollamie (do rozwijanej listy w GUI)."""
        url = normalize_ai_endpoint(base_url, DEFAULT_URL, "Ollamy")
        session = requests.Session()
        session.trust_env = not is_loopback_endpoint(url)
        if api_key:
            session.headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = session.get(f"{url}/api/tags", timeout=timeout_s, allow_redirects=False)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as exc:
            raise AIConnectionError(f"Brak połączenia z Ollamą pod {url}: {exc}") from exc
        finally:
            session.close()
        if not isinstance(data, dict) or not isinstance(data.get("models", []), list):
            raise AIResponseError("Ollama zwróciła niepoprawną listę modeli")
        return sorted(
            str(model["name"])
            for model in data.get("models", [])
            if isinstance(model, dict) and model.get("name")
        )


def _model_available(wanted: str, installed: list[str]) -> bool:
    # Ollama traktuje "model" i "model:latest" zamiennie.
    candidates = {wanted, f"{wanted}:latest"}
    return any(name in candidates for name in installed)
