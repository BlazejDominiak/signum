"""Private JSON-lines bridge, executed by the installed CUDA Python, not the GUI."""

# ruff: noqa: PLC0415 -- heavy imports belong exclusively to the external worker.
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Callable
from typing import Any


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
        from jevk5.prompt import decision_options, messages  # type: ignore[import-not-found]
        from transformers import AutoTokenizer  # type: ignore[import-not-found]

        tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    model = None
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            text, question = payload["text"], payload["question"]
            with contextlib.redirect_stdout(sys.stderr):
                if payload["op"] == "prepare":
                    options = [desc for _, desc in decision_options(question)]

                    def count(
                        state: str,
                        question: dict[str, Any] = question,
                        options: list[str] = options,
                    ) -> int:
                        prompt = tokenizer.apply_chat_template(
                            messages(state, question["instructions"], options),
                            tokenize=False,
                            add_generation_prompt=True,
                            enable_thinking=False,
                        )
                        return len(tokenizer.encode(prompt, add_special_tokens=False))

                    # Small margin for changing repetition digits and model template details.
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
                    response = {"text": text}
                else:
                    from unittest.mock import patch

                    import torch  # type: ignore[import-not-found]
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
                    response = {} if payload["op"] == "load" else model.decide(text, question)
                    torch.cuda.synchronize()
            output.write(json.dumps({"ok": True, "result": response}, ensure_ascii=False) + "\n")
        except Exception as exc:
            output.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False) + "\n")
        output.flush()


if __name__ == "__main__":
    main()
