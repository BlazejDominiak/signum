"""Private JSON-lines bridge, executed by the installed CUDA Python, not the GUI."""

# ruff: noqa: PLC0415 -- heavy imports belong exclusively to the external worker.
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import sys
from collections.abc import Callable
from typing import Any


def decide_many(model: Any, text: str, questions: dict[str, Any]) -> dict[str, Any]:
    """Batch independent decisions without replacing them with a categorical softmax."""
    import numpy as np  # type: ignore[import-not-found]
    import torch  # type: ignore[import-not-found]
    from jevk5.prompt import answer, decision_options  # type: ignore[import-not-found]

    items = []
    for key, question in questions.items():
        options = decision_options(question)
        if question["type"] != "noul":
            raise ValueError("Pakiet etykiet wymaga niezależnych pytań tak/nie.")
        ids = model.encode(text, question["instructions"], [value for _, value in options])
        items.append((key, question, options, ids))

    if not items:
        raise ValueError("Brak pytań do oceny.")
    prefix_length = 0
    for tokens in zip(*(item[3] for item in items), strict=False):
        if len(set(tokens)) != 1:
            break
        prefix_length += 1
    prefix_length = min(prefix_length, min(len(item[3]) for item in items) - 1)
    with torch.inference_mode():
        # The PDF and common instructions are encoded once for the entire label list.
        prefix = model.model.model(
            input_ids=torch.tensor([items[0][3][:prefix_length]], device=model.device),
            use_cache=True,
        ).past_key_values if prefix_length else None

    def forward(chunk: list[Any]) -> Any:
        with torch.inference_mode():
            tails = [item[3][prefix_length:] for item in chunk]
            ids = torch.zeros((len(chunk), max(map(len, tails))),
                              dtype=torch.long, device=model.device)
            last = torch.tensor([len(tail) - 1 for tail in tails], device=model.device)
            for i, tail in enumerate(tails):
                ids[i, :len(tail)] = torch.tensor(tail, device=model.device)
            if prefix is None:
                logits = model._slot_logits(ids, last)
            else:
                # Each branch must own both attention and recurrent states: evaluation mutates them.
                cache = copy.deepcopy(prefix)
                cache.reorder_cache(torch.zeros(len(chunk), dtype=torch.long, device=model.device))
                hidden = model.model.model(
                    input_ids=ids, past_key_values=cache, use_cache=True,
                ).last_hidden_state
                last_hidden = hidden[torch.arange(len(chunk), device=model.device), last]
                logits = last_hidden @ model.slot_weight.T
            return logits.float().cpu().numpy()

    answers = {}
    batch_size = min(len(items), getattr(model, "signum_batch_size", 4))
    offset = 0
    while offset < len(items):
        chunk = items[offset:offset + batch_size]
        try:
            logits = forward(chunk)
        except torch.cuda.OutOfMemoryError:
            if batch_size == 1:
                raise
            batch_size = max(1, (batch_size + 1) // 2)
            model.signum_batch_size = batch_size
            torch.cuda.empty_cache()
            continue
        for (key, question, options, ids), values in zip(chunk, logits, strict=True):
            scaled = values[:len(options)] / model.temperature
            probs = np.exp(scaled - scaled.max())
            probs /= probs.sum()
            answers[key] = answer(
                question,
                {option: float(value) for (option, _), value in zip(options, probs, strict=True)},
                len(ids),
            )
        offset += len(chunk)
    return {"answers": answers, "batch_size": batch_size, "shared_prefix_tokens": prefix_length}


def prepare_text(tokenizer: Any, text: str, questions: list[dict[str, Any]]) -> str:
    from jevk5.prompt import decision_options, messages

    for question in questions:
        options = [desc for _, desc in decision_options(question)]

        def count(
            state: str, question: dict[str, Any] = question, options: list[str] = options,
        ) -> int:
            prompt = tokenizer.apply_chat_template(
                messages(state, question["instructions"], options),
                tokenize=False, add_generation_prompt=True, enable_thinking=False,
            )
            return len(tokenizer.encode(prompt, add_special_tokens=False))

        budget = 4080
        if count("") >= budget - 128:
            raise ValueError("Skróć prompt lub opisy kategorii — są zbyt długie.")
        low, high = 0, len(text)
        if count(text) > budget:
            while low < high:
                middle = (low + high + 1) // 2
                if count(text[:middle]) <= budget:
                    low = middle
                else:
                    high = middle - 1
            text = text[:low]
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--packages", default="")
    parser.add_argument("--runtime", default="")
    args = parser.parse_args()
    # Embedded Python deliberately ignores PYTHONPATH: use explicit trusted paths.
    sys.path[:0] = [p for p in (args.runtime, args.packages) if p]
    output = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        from transformers import AutoTokenizer  # type: ignore[import-not-found]

        tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    model = None
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            text, question = payload["text"], payload["question"]
            with contextlib.redirect_stdout(sys.stderr):
                if payload["op"] in {"prepare", "prepare_many"}:
                    questions = (list(question.values())
                                 if payload["op"] == "prepare_many" else [question])
                    response = {"text": prepare_text(tokenizer, text, questions)}
                else:
                    from unittest.mock import patch

                    import torch
                    import transformers
                    from jevk5 import JevK5  # type: ignore[import-not-found]

                    if model is None:
                        torch.cuda.set_per_process_memory_fraction(0.8)
                        loader = transformers.Qwen3_5ForCausalLM.from_pretrained

                        def local_loader(
                            *loader_args: Any, loader: Callable[..., Any] = loader, **kwargs: Any
                        ) -> Any:
                            kwargs.pop("device_map", None)
                            return loader(*loader_args, **kwargs).to("cuda")

                        with patch.object(
                            transformers.Qwen3_5ForCausalLM,
                            "from_pretrained",
                            side_effect=local_loader,
                        ):
                            model = JevK5(args.model_dir, graphs=False)
                    if payload["op"] == "load":
                        response = {}
                    elif payload["op"] == "classify_many":
                        response = decide_many(model, text, question)
                    else:
                        response = model.decide(text, question)
                    torch.cuda.synchronize()
            output.write(json.dumps({"ok": True, "result": response}, ensure_ascii=False) + "\n")
        except Exception as exc:
            output.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False) + "\n")
        output.flush()


if __name__ == "__main__":
    main()
