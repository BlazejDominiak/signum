"""Text classification clients for Venice, Ollama and the separate JevK5 runtime."""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from importlib import resources
from pathlib import Path
from typing import Any

import requests

from signum.ai.model_profiles import ModelProfile
from signum.ai.ollama_client import OllamaVisionModel
from signum.ai.parsing import extract_first_json_object
from signum.config import AppConfig, get_api_key
from signum.core.classification import check_cancel
from signum.core.decision import label_questions, probability
from signum.local_components import jevk5_files
from signum.network import is_loopback_endpoint, normalize_ai_endpoint

_CONNECTION_TEXT = "Connection test."
_CONNECTION_QUESTION = {"type": "noul", "instructions": "The input is a connection test."}


def _check_connection_decision(answer: dict[str, Any]) -> None:
    # Verify the protocol, not whether the model agreed with the probe statement.
    if answer.get("type") != "noul":
        raise ValueError("Model nie zwrócił odpowiedzi w formacie Decisions.")
    probability(answer.get("noul"))


def _check_connection_text(content: Any) -> None:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Model nie zwrócił treści odpowiedzi na test połączenia.")


def venice_key(config: AppConfig) -> str:
    key = os.environ.get("VENICE_API_KEY") or get_api_key("venice")
    if key:
        return key
    path = Path(config.classification_env_file)
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "VENICE_API_KEY":
                return value.strip().strip("\"'")
    raise ValueError("Brak klucza Venice. Uzupełnij połączenie lub wybierz plik .env.")


class VeniceTextClassifier:
    def __init__(
        self,
        config: AppConfig,
        cancel: threading.Event,
        progress: Callable[[str], None],
        profile: ModelProfile | None = None,
        api_key: str | None = None,
    ) -> None:
        self.cancel = cancel
        self.progress = progress
        self.session = requests.Session()
        self.url = normalize_ai_endpoint(
            profile.url if profile else "https://api.venice.ai/api/v1", "", "AI"
        )
        self.model = profile.model if profile else "jev-latest"
        self.session.trust_env = not is_loopback_endpoint(self.url)
        key = venice_key(config) if api_key is None else api_key
        if key:
            self.session.headers["Authorization"] = "Bearer " + key
        self.starts: deque[float] = deque()
        self.timeout = config.timeout_s

    def classify(self, text: str, question: dict[str, Any]) -> dict[str, Any]:
        questions = label_questions(question) if question["type"] == "multilabel" else {
            "document_type": question
        }
        waiting = 0.0
        for attempt in range(3):
            check_cancel(self.cancel)
            now = time.monotonic()
            while self.starts and now - self.starts[0] >= 61:
                self.starts.popleft()
            if "api.venice.ai/" in self.url + "/" and len(self.starts) >= 100:
                waiting += self._wait(max(0, 61 - (now - self.starts[0])))
                self.starts.popleft()
            self.starts.append(time.monotonic())
            response = self.session.post(
                self.url + "/decisions",
                json={
                    "model": self.model,
                    "state": text,
                    "questions": questions,
                },
                timeout=(15, self.timeout),
                allow_redirects=False,
            )
            if response.status_code == 429 and attempt < 2:
                try:
                    seconds = float(response.headers.get("Retry-After", "61"))
                except ValueError:
                    seconds = 61
                waiting += self._wait(max(61, min(seconds, 3600)))
                continue
            if response.status_code != 200:
                raise ValueError(f"API zwróciło HTTP {response.status_code}.")
            answers = response.json().get("answers", {})
            if question["type"] == "multilabel":
                if not isinstance(answers, dict) or set(answers) != set(questions):
                    raise ValueError("Brak kompletu ocen etykiet JEV.")
                scores = {}
                for key in questions:
                    answer = answers[key]
                    if not isinstance(answer, dict) or answer.get("type") != "noul":
                        raise ValueError("Niepoprawna ocena etykiety JEV.")
                    scores[key] = probability(answer.get("noul"))
                return {"label_scores": scores, "wait_s": waiting}
            result = answers.get("document_type", {})
            return {**result, "wait_s": waiting}
        raise ValueError("API: przekroczono limit żądań.")

    def check_connection(self) -> None:
        answer = self.classify(_CONNECTION_TEXT, _CONNECTION_QUESTION)
        _check_connection_decision(answer)

    def _wait(self, seconds: float) -> float:
        self.progress(f"Limit API: oczekiwanie {seconds:.0f} s.")
        started = time.perf_counter()
        self.cancel.wait(seconds)
        check_cancel(self.cancel)
        return time.perf_counter() - started

    def close(self) -> None:
        self.session.close()


class GemmaTextClassifier:
    def __init__(self, config: AppConfig, api_key: str | None = None) -> None:
        self.loading_s = 0.0
        self.url = normalize_ai_endpoint(
            config.classification_ollama_url, "http://localhost:11434", "Ollamy"
        )
        self.model = config.classification_ollama_model
        self.can_load = is_loopback_endpoint(self.url) and not self.model.lower().endswith("cloud")
        self.timeout = config.timeout_s
        self.session = requests.Session()
        self.session.trust_env = not is_loopback_endpoint(self.url)
        key = (get_api_key("ollama") or "") if api_key is None else api_key
        if key:
            self.session.headers["Authorization"] = "Bearer " + key
        runtime_dir = config.ollama_runtime_dir
        if not runtime_dir and is_loopback_endpoint(self.url):
            executable = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
            if executable.is_file():
                runtime = Path(config.classification_cache_dir) / "ollama"
                runtime.mkdir(parents=True, exist_ok=True)
                (runtime / "runtime.json").write_text(
                    json.dumps({"external_executable": str(executable)}),
                    encoding="utf-8",
                )
                runtime_dir = str(runtime)
        self.manager = OllamaVisionModel(
            self.url,
            self.model,
            api_key=key,
            runtime_dir=runtime_dir,
            timeout_s=config.timeout_s,
        )
        try:
            self.manager.check_connection()
        except Exception:
            self.close()
            raise

    def check_connection(self) -> None:
        response = self.session.post(
            self.url + "/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "think": False,
                "keep_alive": "10m",
                "messages": [{"role": "user", "content": "Reply briefly: connection test."}],
                "options": {"num_predict": 32},
            },
            timeout=(15, self.timeout),
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError(f"Ollama zwróciła HTTP {response.status_code}.")
        _check_connection_text(response.json().get("message", {}).get("content"))

    def prepare_model(self) -> None:
        if self.can_load:
            self.manager.load_model()

    def classify(self, text: str, question: dict[str, Any]) -> dict[str, Any]:
        self.loading_s = 0.0
        response = self.session.post(
            self.url + "/api/chat",
            timeout=(15, self.timeout),
            allow_redirects=False,
            json={
                "model": self.model,
                "stream": False,
                "think": False,
                "keep_alive": "10m",
                "messages": [
                    {"role": "system", "content": question["instructions"]
                     + '\nReturn only JSON {"label_scores": {"category ID": number}}. '
                     'For EVERY category, estimate your confidence from 0 to 1 that it applies '
                     'to the document. Assess each category independently; scores need not sum '
                     'to 1. Use scores near 0.5 when uncertain, near 1 when clearly supported, '
                     'and near 0 when clearly unsupported. Include every category ID once.'},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"evidence": text, "categories": question["criteria"]},
                            ensure_ascii=False,
                        ),
                    },
                ],
                "format": {
                    "type": "object",
                    "properties": {
                        "label_scores": {
                            "type": "object",
                            "properties": {
                                key: {"type": "number", "minimum": 0, "maximum": 1}
                                for key in question["criteria"]
                            },
                            "required": list(question["criteria"]),
                            "additionalProperties": False,
                        }
                    },
                    "required": ["label_scores"],
                    "additionalProperties": False,
                },
                "options": {
                    "temperature": 0, "seed": 20261007, "num_ctx": 8192, "num_predict": 512,
                },
            },
        )
        if response.status_code != 200:
            raise ValueError(f"Ollama zwróciła HTTP {response.status_code}.")
        result = response.json()
        if is_loopback_endpoint(self.url) and not self.model.lower().endswith("cloud"):
            self.loading_s = max(0.0, float(result.get("load_duration", 0)) / 1e9)
        if result.get("done_reason") == "length":
            raise ValueError("Model nie dokończył odpowiedzi.")
        if result.get("prompt_eval_count", 0) >= 8100:
            raise ValueError(
                "Tekst zbliża się do granicy kontekstu modelu; skróć dokument lub prompt."
            )
        parsed = json.loads(result.get("message", {}).get("content", ""))
        scores = parsed.get("label_scores")
        if not isinstance(scores, dict) or set(scores) != set(question["criteria"]):
            raise ValueError("Model nie zwrócił ocen wszystkich etykiet z podanej listy.")
        return {"label_scores": {key: probability(value) for key, value in scores.items()},
                "score_source": "declared"}

    def close(self) -> None:
        self.manager.release_resources()
        self.session.close()


class JevK5TextClassifier:
    """Owned subprocess isolates Torch/CUDA from packaged Python and frees VRAM on exit."""

    def __init__(self, config: AppConfig, cancel: threading.Event) -> None:
        self.config = config
        self.cancel = cancel
        self.process: subprocess.Popen[str] | None = None
        self.replies: queue.Queue[str | None] = queue.Queue()

    def available(self) -> bool:
        try:
            jevk5_files(self.config)
            return True
        except ValueError:
            return False

    def _start(self) -> None:
        if self.process is not None:
            return
        if not self.available():
            jevk5_files(self.config)
        cache = Path(self.config.classification_cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        for key in ("PYTHONHOME", "_PYI_APPLICATION_HOME_DIR", "_PYI_PARENT_PROCESS_LEVEL"):
            env.pop(key, None)
        env.update(
            PYTHONPATH=os.pathsep.join(
                (self.config.classification_jev_packages, self.config.classification_jev_runtime)
            ),
            PYTHONUTF8="1",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            TOKENIZERS_PARALLELISM="false",
            HF_HOME=str(cache),
            TORCH_HOME=str(cache),
            TEMP=str(cache),
            TMP=str(cache),
        )
        script = resources.files("signum.ai") / "jevk5_text_worker.py"
        with (cache / "jevk5-text.log").open("a", encoding="utf-8") as log:
            import ctypes  # noqa: PLC0415
            import sys  # noqa: PLC0415

            if os.name == "nt":
                ctypes.windll.kernel32.SetDllDirectoryW(None)
            try:
                self.process = subprocess.Popen(
                    [
                        self.config.classification_jev_python,
                        str(script),
                        "--model-dir",
                        self.config.classification_jev_model_dir,
                        "--packages",
                        self.config.classification_jev_packages,
                        "--runtime",
                        self.config.classification_jev_runtime,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=log,
                    text=True,
                    encoding="utf-8",
                    env=env,
                    cwd=cache,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            finally:
                if os.name == "nt":
                    ctypes.windll.kernel32.SetDllDirectoryW(getattr(sys, "_MEIPASS", None))

        threading.Thread(
            target=self._read_replies, args=(self.process, self.replies), daemon=True
        ).start()

    def _read_replies(
        self, process: subprocess.Popen[str], replies: queue.Queue[str | None]
    ) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            replies.put(line)
        replies.put(None)

    def _request(self, op: str, text: str, question: dict[str, Any]) -> dict[str, Any]:
        check_cancel(self.cancel)
        self._start()
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(
            json.dumps(
                {"op": op, "text": text, "question": question},
                ensure_ascii=False,
            )
            + "\n"
        )
        self.process.stdin.flush()
        deadline = time.monotonic() + self.config.timeout_s
        while time.monotonic() < deadline:
            check_cancel(self.cancel)
            try:
                line = self.replies.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                log_path = Path(self.config.classification_cache_dir) / "jevk5-text.log"
                try:
                    with log_path.open("rb") as log:
                        log.seek(max(0, log_path.stat().st_size - 2000))
                        detail = log.read().decode("utf-8", errors="replace")
                except OSError:
                    detail = ""
                raise ValueError(f"JevK5 zakończył pracę. Log: {log_path}\n{detail}")
            response = json.loads(line)
            if not response.get("ok"):
                raise ValueError(response.get("error", "Błąd lokalnego JevK5"))
            result: dict[str, Any] = response["result"]
            return result
        self.close()
        raise TimeoutError("JevK5: przekroczono czas oczekiwania na odpowiedź.")

    def check_connection(self) -> None:
        answer = self._request("classify", _CONNECTION_TEXT, _CONNECTION_QUESTION)
        _check_connection_decision(answer)

    def prepare_model(self) -> None:
        self._request("load", "", {})

    def prepare(self, text: str, question: dict[str, Any]) -> str:
        if question["type"] == "multilabel":
            return str(self._request("prepare_many", text, label_questions(question))["text"])
        return str(self._request("prepare", text, question)["text"])

    def classify(self, text: str, question: dict[str, Any]) -> dict[str, Any]:
        if question["type"] != "multilabel":
            return self._request("classify", text, question)
        questions = label_questions(question)
        response = self._request("classify_many", text, questions)
        check_cancel(self.cancel)
        answers = response.get("answers")
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise ValueError("Brak kompletu ocen etykiet JevK5.")
        scores = {}
        for key, answer in answers.items():
            if not isinstance(answer, dict) or answer.get("type") != "noul":
                raise ValueError("Niepoprawna ocena etykiety JevK5.")
            scores[key] = probability(answer.get("noul"))
        return {"label_scores": scores}

    def close(self) -> None:
        if self.process is not None:
            process = self.process
            self.process = None
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()
            self.replies = queue.Queue()


def conservative_text_limit(text: str, question: dict[str, Any]) -> str:
    """Offline fallback without the local tokenizer: bound UTF-8 bytes, including instructions."""
    remaining = 7000 - len(json.dumps(question, ensure_ascii=False).encode())
    if remaining < 512:
        raise ValueError("Skróć prompt lub opisy kategorii, aby zmieścić tekst dokumentu.")
    return text.encode()[:remaining].decode("utf-8", errors="ignore")


class APITextClassifier:
    """Text classification through configurable Chat Completions or Messages APIs."""

    def __init__(self, profile: ModelProfile, config: AppConfig, api_key: str) -> None:
        self.profile = profile
        self.url = normalize_ai_endpoint(profile.url, "", "AI")
        self.timeout = config.timeout_s
        self.session = requests.Session()
        self.session.trust_env = not is_loopback_endpoint(self.url)
        if profile.api_format == "anthropic":
            self.session.headers["anthropic-version"] = "2023-06-01"
            if api_key:
                self.session.headers["x-api-key"] = api_key
        elif api_key:
            self.session.headers["Authorization"] = "Bearer " + api_key

    def check_connection(self) -> None:
        payload: dict[str, Any] = {
            "model": self.profile.model,
            "messages": [{"role": "user", "content": "Reply briefly: connection test."}],
        }
        if self.profile.api_format == "anthropic":
            route = "/messages"
            payload["max_tokens"] = 32
        else:
            route = "/chat/completions"
        response = self.session.post(
            self.url + route, json=payload, timeout=(15, self.timeout), allow_redirects=False
        )
        if response.status_code != 200:
            raise ValueError(f"API zwróciło HTTP {response.status_code}.")
        data = response.json()
        content: Any
        if self.profile.api_format == "anthropic":
            content = "\n".join(
                block["text"] for block in data.get("content", []) if block.get("type") == "text"
            )
        else:
            choices = data.get("choices", [])
            content = choices[0].get("message", {}).get("content") if choices else None
        _check_connection_text(content)

    def classify(self, text: str, question: dict[str, Any]) -> dict[str, Any]:
        instructions = (
            question["instructions"]
            + '\nReturn only JSON: {"categories": ["category IDs"]}; '
            'up to 3 matching IDs, highest relevance first, or [].'
        )
        evidence = json.dumps(
            {"evidence": text, "categories": question["criteria"]}, ensure_ascii=False
        )
        payload: dict[str, Any] = {"model": self.profile.model}
        if self.profile.api_format == "anthropic":
            route = "/messages"
            payload.update(
                system=instructions,
                max_tokens=256,
                messages=[{"role": "user", "content": evidence}],
            )
        else:
            route = "/chat/completions"
            payload["messages"] = [
                {"role": "system", "content": instructions},
                {"role": "user", "content": evidence},
            ]
        response = self.session.post(
            self.url + route, json=payload, timeout=(15, self.timeout), allow_redirects=False
        )
        if response.status_code != 200:
            raise ValueError(f"API zwróciło HTTP {response.status_code}.")
        data = response.json()
        if self.profile.api_format == "anthropic":
            if data.get("stop_reason") == "max_tokens":
                raise ValueError("Model nie dokończył odpowiedzi.")
            content = "\n".join(
                block["text"] for block in data.get("content", []) if block.get("type") == "text"
            )
        else:
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("Model nie dokończył odpowiedzi.")
            content = choice["message"]["content"]
        parsed = extract_first_json_object(content)
        return {"choices": parsed.get("categories")}

    def close(self) -> None:
        self.session.close()


def create_text_classifier(
    profile: ModelProfile,
    config: AppConfig,
    cancel: threading.Event,
    progress: Callable[[str], None] = lambda _: None,
    api_key: str | None = None,
) -> JevK5TextClassifier | GemmaTextClassifier | VeniceTextClassifier | APITextClassifier:
    profile.validate()
    if api_key is None:
        api_key = get_api_key(profile.credential_slot) or ""
        if not api_key and profile.key_slot == "venice":
            api_key = venice_key(config)
    if profile.provider == "jevk5":
        return JevK5TextClassifier(
            replace(
                config,
                classification_jev_python=profile.python,
                classification_jev_model_dir=profile.model_dir,
                classification_jev_runtime=profile.runtime,
                classification_jev_packages=profile.packages,
            ),
            cancel,
        )
    if profile.provider == "ollama":
        return GemmaTextClassifier(
            replace(
                config,
                classification_ollama_url=profile.url,
                classification_ollama_model=profile.model,
            ),
            api_key=api_key,
        )
    if profile.api_format == "decisions":
        return VeniceTextClassifier(config, cancel, progress, profile, api_key)
    return APITextClassifier(profile, config, api_key)
