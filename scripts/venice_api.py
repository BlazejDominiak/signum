"""Venice API access for the reproducible classification benchmark and demos."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]


def settings() -> dict[str, str]:
    values = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            name, separator, value = raw.partition("=")
            if separator:
                values[name.strip()] = value.strip().strip("\"'")
    for key in ("VENICE_API_KEY", "VENICE_BASE_URL", "VENICE_CHAT_MODEL", "VENICE_DECISION_MODEL"):
        if key in os.environ:
            values[key] = os.environ[key]
    if not values.get("VENICE_API_KEY"):
        raise RuntimeError("Set VENICE_API_KEY in the gitignored .env or environment")
    values.setdefault("VENICE_BASE_URL", "https://api.venice.ai/api/v1")
    values.setdefault("VENICE_CHAT_MODEL", "zai-org-glm-5-2")
    values.setdefault("VENICE_DECISION_MODEL", "jev-latest")
    parsed = urlparse(values["VENICE_BASE_URL"])
    if parsed.scheme != "https" or parsed.hostname != "api.venice.ai":
        raise RuntimeError("Use the official https://api.venice.ai API endpoint")
    return values


class VeniceClient:
    def __init__(self) -> None:
        self.config = settings()
        self.base_url = self.config["VENICE_BASE_URL"].rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + self.config["VENICE_API_KEY"]})
        self.retry_after = 0.0

    def request(self, method: str, endpoint: str, **kwargs) -> tuple[int, dict]:
        response = self.session.request(
            method,
            f"{self.base_url}/{endpoint.lstrip('/')}",
            timeout=(15, 120),
            allow_redirects=False,
            **kwargs,
        )
        try:
            self.retry_after = float(response.headers.get("Retry-After", "0"))
        except ValueError:
            self.retry_after = 0.0
        try:
            data = response.json()
        except ValueError:
            data = {"error": response.text[:1000]}
        return response.status_code, data

    def decide(self, state: str, question: dict) -> tuple[int, dict]:
        return self.request(
            "POST",
            "decisions",
            json={
                "model": self.config["VENICE_DECISION_MODEL"],
                "state": state,
                "questions": {"document_type": question},
            },
        )

    def chat(self, messages: list[dict], **options) -> tuple[int, dict]:
        """OpenAI-compatible chat; Jev itself uses decide(), not this endpoint."""
        return self.request(
            "POST",
            "chat/completions",
            json={
                "model": self.config["VENICE_CHAT_MODEL"],
                "messages": messages,
                "stream": False,
                **options,
            },
        )
