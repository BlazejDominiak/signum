"""Same-task Gemma control, fixed before evaluation; one request per full page."""

import base64
import hashlib
import json
import time
from pathlib import Path

import requests
from run_jev50 import PROTOCOL, ROOT

from signum.ai.parsing import extract_first_json_object
from signum.core.rendering import render_pdf_page, to_model_jpeg

CONTROL = json.loads(Path(__file__).with_name("gemma_binary_protocol.json").read_text())


def main():
    output = ROOT / "gemma_binary.jsonl"
    completed = set()
    if output.exists():
        completed = {json.loads(line)["sample"] for line in output.read_text().splitlines()}
    session = requests.Session()
    session.trust_env = False
    tags_response = session.get("http://localhost:11434/api/tags", timeout=10)
    tags_response.raise_for_status()
    pinned = [m for m in tags_response.json()["models"] if m["name"] == CONTROL["request"]["model"]]
    if len(pinned) != 1 or pinned[0]["digest"] != PROTOCOL["gemma_digest"]:
        raise RuntimeError("Gemma model digest differs from the frozen benchmark version")
    try:
        with output.open("a", encoding="utf-8") as handle:
            labels = json.loads((ROOT / "labels.json").read_text(encoding="utf-8"))
            for sample in labels["samples"]:
                if sample["id"] in completed:
                    continue
                image = render_pdf_page(
                    ROOT / "pdf" / f"{sample['document']}.pdf", sample["page"]
                ).image
                jpeg = to_model_jpeg(image, 1120)
                payload = {
                    **CONTROL["request"],
                    "messages": [
                        {
                            "role": "user",
                            "content": CONTROL["prompt"],
                            "images": [base64.b64encode(jpeg).decode("ascii")],
                        }
                    ],
                }
                row = {
                    "sample": sample["id"],
                    "image_sha256": hashlib.sha256(jpeg).hexdigest(),
                }
                start = time.perf_counter()
                try:
                    response = session.post(
                        "http://localhost:11434/api/chat",
                        json=payload,
                        timeout=300,
                    )
                    response.raise_for_status()
                    row["response"] = response.json()
                    answer = extract_first_json_object(row["response"]["message"]["content"])
                    if type(answer.get("has_signature")) is not bool:
                        raise ValueError("Expected a boolean has_signature")
                    row["predicted"] = answer["has_signature"]
                except Exception as exc:
                    row["error"] = repr(exc)
                row["elapsed_s"] = time.perf_counter() - start
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(
                    sample["id"],
                    row.get("predicted", row.get("error")),
                    round(row["elapsed_s"], 2),
                    flush=True,
                )
    finally:
        session.post(
            "http://localhost:11434/api/generate",
            json={"model": CONTROL["request"]["model"], "keep_alive": 0},
            timeout=30,
        )


if __name__ == "__main__":
    main()
