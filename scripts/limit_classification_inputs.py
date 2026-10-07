"""Apply a common input budget before running any model in a classification benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from benchmark_jevk5_classification import MODEL, OUTPUT, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    args = parser.parse_args()
    if args.max_prompt_tokens < 1024:
        parser.error("Use a budget of at least 1024 tokens")
    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    from jevk5.prompt import decision_options, messages  # noqa: PLC0415
    from transformers import AutoTokenizer  # noqa: PLC0415

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL), local_files_only=True)
    protocol_path = args.output_dir / "protocol.json"
    original_path = args.output_dir / "protocol-before-token-limit.json"
    if not original_path.exists():
        shutil.copy2(protocol_path, original_path)
    protocol = json.loads(original_path.read_text(encoding="utf-8"))
    question = protocol["question"]
    options = [desc for _, desc in decision_options(question)]
    if len(options) > 16:
        raise ValueError("This limiter applies to the one-pass protocol with up to 16 options")
    shortened = []
    for doc in protocol["documents"]:
        original = doc["text"]
        instruction = f"Benchmark measurement 3, document {doc['id']}.\n" + question["instructions"]

        def count(text: str, instruction: str = instruction) -> int:
            prompt = tokenizer.apply_chat_template(
                messages(text, instruction, options),
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            return len(tokenizer.encode(prompt, add_special_tokens=False))

        before = count(original)
        limited = original
        if before > args.max_prompt_tokens:
            low, high = 0, len(original)
            while low < high:
                middle = (low + high + 1) // 2
                if count(original[:middle]) <= args.max_prompt_tokens:
                    low = middle
                else:
                    high = middle - 1
            limited = original[:low]
            shortened.append(
                {
                    "id": doc["id"],
                    "before_tokens": before,
                    "before_characters": len(original),
                    "after_characters": low,
                }
            )
        after = count(limited)
        assert after <= args.max_prompt_tokens
        doc.update(
            text=limited,
            input_characters=len(limited),
            truncated=doc["truncated"] or limited != original,
            token_limit_truncated=limited != original,
            original_prompt_tokens=before,
            jevk5_prompt_tokens=after,
            text_sha256=hashlib.sha256(limited.encode()).hexdigest(),
        )
        (args.output_dir / f"{doc['id']}.txt").write_text(limited, encoding="utf-8")
    protocol["max_jevk5_prompt_tokens"] = args.max_prompt_tokens
    protocol["token_limiter"] = (
        "Same text prefix for all models, budget measured with JevK5 tokenizer"
    )
    write_json(protocol_path, protocol)
    write_json(args.output_dir / "token-limit-adjustments.json", shortened)
    print(json.dumps({"documents": len(protocol["documents"]), "shortened": shortened}, indent=2))


if __name__ == "__main__":
    main()
